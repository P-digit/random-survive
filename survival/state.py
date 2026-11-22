"""게임 상태와 규칙(엔진). 숫자 계산은 전부 여기서 하고, LLM은 서술만 담당한다."""
import math
import random
from dataclasses import dataclass, field

from . import climate as climate_api
from . import geo, leads as leads_api
from .config import (DIURNAL_AMPLITUDE, EARLY_GAME_HOURS, MAJOR_EVENT_CHANCE, MAJOR_EVENT_PITY_TURNS, MONEY_GAIN_LIMIT,
                     START_ITEMS, START_MONEY, VITALS_DRAIN, WANTED_AIRPORT_LIMIT, WANTED_DECAY_PER_HOUR)
from .crime import CrimeMixin
from .events import BIOME_HAZARDS, BIOMES, PERSISTENT_OFFERS, classify_biome, roll_event, roll_major_event
from .flags import PlaceFlags, TurnFlags
from .inventory import InventoryMixin
from .journey import JourneyMixin
from .offers import OfferMixin
from .police import PoliceMixin
from .risk_model import predict_risk
from .travel import TravelMixin
from .util import clamp
from .weather import get_weather, weather_category


@dataclass
class GameState(InventoryMixin, CrimeMixin, TravelMixin, JourneyMixin, OfferMixin, PoliceMixin):
    lat: float
    lon: float
    place_name: str
    weather: dict
    biome: str
    place_type: str = "야생"          # 야생 / 마을 / 도시
    health: float = 100.0             # 체력
    satiety: float = 70.0             # 포만감
    hydration: float = 70.0           # 수분
    energy: float = 80.0              # 기력
    money: float = START_MONEY
    items: list = field(default_factory=lambda: list(START_ITEMS))
    start_hour: int = 12              # 시작 시각(출발지 현지 시간)
    start_offset: float = 0.0         # 출발지의 UTC 시차(시간)
    utc_offset: float = 0.0           # 지금 있는 곳의 UTC 시차. 시계는 현재 위치의 현지 시각을 보여 준다
    diurnal: dict = field(default_factory=dict)          # 예보가 없을 때 낮밤 기온을 만드는 기준값
    elapsed_hours: float = 0.0
    start_distance: float = 0.0
    distance: float = 0.0             # 한국까지 남은 거리
    status: str = "playing"           # playing / won / dead
    death_reason: str = ""
    turn: int = 0
    risk: dict = field(default_factory=lambda: {"level": 0, "label": "안전", "probs": [1, 0, 0]})
    event: dict | None = None         # 이번 턴의 돌발 이벤트
    prev_response_id: str | None = None   # Responses API 멀티턴용
    chat: list = field(default_factory=list)
    suggestions: list = field(default_factory=list)
    image_path: str | None = None
    moved_since_image: float = 0.0
    scene_dirty: bool = True          # True면 장면 이미지를 새로 그려야 함
    time_passed_this_turn: bool = False
    forecast: list = field(default_factory=list)   # 현재 위치의 시간별 예보
    weather_origin: float = 0.0       # 예보 0번에 해당하는 elapsed_hours (게임 시작 = 0)
    delta: dict = field(default_factory=dict)      # 지난 턴의 수치 변화 (UI 표시용)
    offer: dict | None = None         # 진행 중인 대형 이벤트(기회). 다음 턴까지 유효
    last_major_turn: int = 0
    image_weather: str = ""           # 현재 장면 이미지가 그려진 날씨 분류
    turn_flags: TurnFlags = field(default_factory=dict)   # 이번 턴에 일어난 일. 키 목록은 flags.py
    # 현재 장면: 플레이어가 지금 서 있는 구체적인 곳 (이미지와 이벤트 판정에 쓰인다)
    scene_setting: str = "outdoor"    # outdoor / indoor
    scene_place: str = ""             # 예: "빈 오두막 안", "버스 터미널", "강가"
    scene_desc: str = ""              # 이미지용 영어 묘사
    scene_features: list = field(default_factory=list)   # GM이 밝힌, 그 장면에 보이는 것들
    scene_seen: list = field(default_factory=list)       # 생성된 이미지를 Vision으로 읽어낸, 실제로 그려진 것들
    scene_seen_en: list = field(default_factory=list)    # 같은 것의 영어 이름 (그림 편집 지시문에 쓴다)
    climate: dict = field(default_factory=dict)          # 이 좌표의 기후 (climate.py)
    climate_at: list = field(default_factory=list)       # 기후를 조회한 좌표 [lat, lon]
    notices: list = field(default_factory=list)          # 이번 턴의 중요 알림 (대화창 표시용)
    tickets: list = field(default_factory=list)          # 예약(결제)해 둔 교통편. 탈 때까지 계속 기억한다
    vehicle: dict | None = None       # 손에 넣은 탈것 (탈취, 구매 등)
    country_code: str = ""            # 지금 있는 나라 (가까운 공관 찾기용, 표지판 언어)
    place_name_en: str = ""           # 영어 지명 (그림 지시문용. 그림에 한글이 들어가지 않게)
    country_en: str = ""
    # 이야기의 개연성: 아직 확인하지 않은 단서와, 이미 확정된 사실
    leads: list = field(default_factory=list)            # [{id, kind, label, clue, target, km, bearing, ...}]
    lead_seq: int = 0
    facts: list = field(default_factory=list)            # [{text, scope: here/always, turn}]
    flags: PlaceFlags = field(default_factory=dict)      # 지금 장소의 사정. 키 목록은 flags.py
    characters: list = field(default_factory=list)       # 이 장소에서 만난 인물 [{name, role, look}]
    journey: dict | None = None       # 여러 턴에 걸친 목적지 이동 {type, name, label, lat, lon, place}
    recent_inputs: list = field(default_factory=list)    # 최근 플레이어 입력 (범죄 의도의 맥락 판단용)
    crime_scene: dict | None = None   # 방금 범죄를 저지른 현장 {lat, lon, turn, hours, crime, victim, witnessed, knocked_out}
    enemies: list = field(default_factory=list)          # 원한이 있는 사람 [{name, role, status, lat, lon, place}]
    notorious: list = field(default_factory=list)        # 범죄자로 알려진 곳 [{place, lat, lon, crime, turn}]
    stolen_items: list = field(default_factory=list)     # 훔친 물건 (체포되면 압수)
    expired_offers: list = field(default_factory=list)   # 지나간 기회 [{id, accept, exit, turn}]
    done_offers: list = field(default_factory=list)      # 받아들이거나 거절해 끝난 기회 [{id, accept, how, turn, lat, lon, note}]
    image_scene: str = ""             # 지금 그림이 그려진 장면 (장소+장면 이름)
    image_night: bool = False         # 지금 그림이 밤 그림인지
    wanted: float = 0.0               # 수배도 0~100 (★단계는 police.heat_stage)
    pursuit: dict | None = None       # 지금 마주친 경찰 {stage, turn, who, kind: check/chase} — 다음 턴 입력으로 판정
    disguise: dict = field(default_factory=dict)   # 변장 {until(경과 시간), how}
    _snapshot: dict = field(default_factory=dict)

    # ---------- 시간 ----------
    @property
    def hour(self):
        """지금 있는 곳의 현지 시각. 시간대가 다른 곳으로 이동하면 시계도 그곳에 맞춰진다."""
        return int(math.floor(self.start_hour - self.start_offset + self.utc_offset + self.elapsed_hours)) % 24

    @property
    def day(self):
        return int(self.start_hour + self.elapsed_hours) // 24 + 1

    @property
    def is_night(self):
        return self.hour < 6 or self.hour >= 20

    @property
    def early(self):
        """게임 초반: 아직 도시·공항·공관으로 갈 수 없다."""
        return self.elapsed_hours < EARLY_GAME_HOURS

    def early_message(self):
        left = max(1, round(EARLY_GAME_HOURS - self.elapsed_hours))
        return (f"아직 이 지역을 벗어날 방법을 찾지 못했다. 앞으로 약 {left}시간은 근처(마을까지)에서 버티며 "
                "길과 사람, 여비를 찾아야 한다.")

    @property
    def biome_name(self):
        return BIOMES[self.biome][0]

    @property
    def hazard(self):
        return BIOME_HAZARDS[self.biome]

    @property
    def indoor(self):
        return self.scene_setting == "indoor"

    def same_place(self, setting, place):
        """지금 장면과 같은 곳인지. '한국 공관 영사과'와 '영사과 창구'처럼 이름이 조금 달라도 같은 곳으로 본다."""
        if setting != self.scene_setting or not self.scene_place or not place:
            return setting == self.scene_setting and place == self.scene_place
        a, b = self.scene_place.replace(" ", ""), place.replace(" ", "")
        if a in b or b in a:
            return True
        words_a = {w for w in self.scene_place.split() if len(w) >= 2}
        words_b = {w for w in place.split() if len(w) >= 2}
        return bool(words_a & words_b)

    def set_scene(self, setting, place, description_en, features=None):
        """장면을 바꾼다. 다른 곳으로 옮겼을 때만 묘사를 바꾸고 그림을 새로 그린다.

        같은 곳에 머무는 동안에는 처음 정한 묘사·보이는 것을 그대로 둔다. 그래야 그림 속 구성과
        인물이 바뀌지 않는다. (보이는 것이 새로 생겼다면 목록에 덧붙이기만 한다)
        """
        setting = setting if setting in ("outdoor", "indoor") else "outdoor"
        place = str(place or "").strip()[:30]
        features = [str(f).strip()[:30] for f in (features or []) if str(f).strip()]
        if self.scene_place and self.same_place(setting, place):
            new = [f for f in features if f not in self.scene_features]
            self.scene_features = (self.scene_features + new)[:8]
            return False
        self.scene_setting, self.scene_place = setting, place
        self.scene_desc = str(description_en or "").strip()[:400]
        self.scene_features = features[:6]
        self.scene_dirty = True
        self.scene_seen = []           # 새 그림이 그려지면 다시 읽어 들인다
        self.scene_seen_en = []
        self.characters = []           # 다른 곳으로 옮기면 그곳의 인물은 새로 만난다
        self.turn_flags["scene_changed"] = True
        self.flags.pop("at_embassy", None)
        return True

    def add_character(self, name, role, look=""):
        """이 장소에서 만난 인물을 기록한다. 같은 사람은 이름·역할·생김새가 바뀌지 않는다."""
        name, role, look = str(name).strip()[:20], str(role).strip()[:30], str(look).strip()[:80]
        if not name:
            return None
        for person in self.characters:
            if person["name"] == name or (role and person["role"] == role):
                return person          # 이미 있는 사람: 처음 정한 모습 그대로
        person = {"name": name, "role": role, "look": look, "status": ""}
        self.characters.append(person)
        self.characters = self.characters[-6:]
        return person

    def find_character(self, who):
        """이름이나 역할로 인물을 찾는다 ('트럭 기사' → 이름이 '아메드'이고 역할이 '트럭 기사'인 사람)."""
        who = str(who or "").strip()
        if not who:
            return None
        flat = who.replace(" ", "")
        for person in self.characters:
            for key in (person["name"], person["role"]):
                k = (key or "").replace(" ", "")
                if k and (k in flat or flat in k):
                    return person
        return None

    def visible_things(self):
        """지금 화면(장면 이미지)에 보이는 것들: GM이 밝힌 것 + 실제 그림에서 읽어낸 것."""
        things = list(self.scene_features)
        things += [s for s in self.scene_seen if s not in things]
        return things

    def refresh_climate(self):
        """기후를 조회한다. 지난번 조회 지점에서 200km 이상 움직였을 때만 다시 조회한다."""
        if self.climate and self.climate_at and \
                geo.haversine_km(self.lat, self.lon, *self.climate_at) < 200:
            return
        self.climate = climate_api.get_climate(self.lat, self.lon, self.weather)
        self.climate_at = [self.lat, self.lon]

    @property
    def in_extreme_wild(self):
        return self.place_type == "야생" and self.hazard["extreme"]

    # ---------- 날씨 ----------
    def set_weather(self, weather):
        """새 위치의 날씨를 적용한다. 시간별 예보는 따로 보관하고, 게임 시계와 맞춘다."""
        weather = dict(weather)
        self.forecast = weather.pop("hourly", [])
        self.utc_offset = float(weather.pop("utc_offset", self.utc_offset))
        self.weather = weather
        # 예보 0번의 현지 시각과 게임의 현지 시각을 맞춘다: forecast[k] 가 지금 시각이 되도록
        first = self.forecast[0].get("hour") if self.forecast else None
        k = (self.hour - first) % 24 if first is not None else 0
        self.weather_origin = self.elapsed_hours - k
        # 예보가 없으면 지금 기온을 기준으로 하루 기온 곡선을 만든다
        amp = DIURNAL_AMPLITUDE.get(self.biome, 6) * (0.6 if weather.get("humidity", 50) >= 80 else 1.0)
        shape = math.cos(2 * math.pi * (self.hour - 15) / 24)     # 오후 3시 최고, 새벽 3시 최저
        self.diurnal = {"mean": weather["temperature"] - amp * shape, "amp": amp,
                        "feels_gap": weather["feels_like"] - weather["temperature"]}
        self.sync_weather()

    def sync_weather(self):
        """게임 속 시간에 맞는 날씨를 적용한다. 밤에는 추워지고 낮에는 기온이 오른다.

        예보 범위 안이면 그 시각의 예보를, 범위를 넘으면 마지막 하루의 같은 시각 값을,
        예보가 아예 없으면 지형별 일교차 곡선으로 만든 값을 쓴다.
        """
        if self.forecast:
            index = int(self.elapsed_hours - self.weather_origin)
            n = len(self.forecast)
            if index >= n:
                if n >= 24:     # 예보가 끝나면 마지막 하루의 같은 시각 값을 되풀이한다
                    index = (n - 24) + (index - (n - 24)) % 24
                else:
                    index = n - 1
            self.weather.update({k: v for k, v in self.forecast[max(0, index)].items() if k != "hour"})
        elif self.diurnal:
            d = self.diurnal
            temp = d["mean"] + d["amp"] * math.cos(2 * math.pi * (self.hour - 15) / 24)
            self.weather["temperature"] = round(temp, 1)
            self.weather["feels_like"] = round(temp + d["feels_gap"], 1)
        self.weather["is_day"] = not self.is_night

    def event_context(self):
        """돌발 이벤트를 고르는 데 쓰는 지금 상황."""
        return {"night": self.is_night, "indoor": self.indoor,
                "weather": weather_category(self.weather.get("code", 0)),
                "temp": self.weather.get("feels_like", 15),
                "season": (self.climate or {}).get("season")}

    # ---------- 규칙 ----------
    def pass_time(self, hours, activity="other", sheltered=False):
        """시간이 흐르면서 포만감·수분·기력이 변한다. 수치가 바닥나면 체력이 깎인다.

        야생에서는 지형(BIOME_HAZARDS)과 날씨에 따라 소모와 피해가 커진다.
        sheltered=True(불·쉘터·실내)면 날씨로 인한 피해가 크게 줄어든다.
        """
        hours = clamp(float(hours), 0.25, 12)
        sheltered = sheltered or self.indoor      # 실내에 있으면 날씨를 피하고 있는 것이다
        remaining = hours
        while remaining > 0 and self.status == "playing":
            h = min(1.0, remaining)
            remaining -= h
            self.sync_weather()
            temp = self.weather["feels_like"]
            wild = self.place_type == "야생"
            hz = self.hazard if wild else BIOME_HAZARDS["forest"]   # 마을·도시에서는 환경 위험 없음
            resting = activity in ("rest", "sleep", "ride")

            # --- 소모 ---
            hunger = (1.2 if activity == "sleep" else 2.2) * hz["satiety"] * VITALS_DRAIN
            thirst = (1.5 if activity == "sleep" else 3.0) * VITALS_DRAIN
            if self.biome == "desert" and wild:
                thirst *= hz["hydration"] if not self.is_night else 1.2   # 사막의 낮
            else:
                thirst *= hz["hydration"]
            if temp >= 30:
                thirst *= 1.5
            energy_rate = {"sleep": 10, "rest": 6, "ride": 1.5, "walk": -5,
                           "work": -5, "forage": -4, "explore": -4}.get(activity, -3)
            if energy_rate < 0:
                energy_rate *= hz["energy"] * VITALS_DRAIN
            elif wild and not sheltered and (temp <= 5 or temp >= 35):
                energy_rate *= 0.5        # 혹독한 날씨에 노출된 채로는 제대로 쉬지 못한다
            before = (self.satiety, self.hydration)
            self.satiety = clamp(self.satiety - hunger * h)
            self.hydration = clamp(self.hydration - thirst * h)
            self.energy = clamp(self.energy + energy_rate * h)
            drain = self.turn_flags.setdefault("drain", {"satiety": 0.0, "hydration": 0.0})
            drain["satiety"] += before[0] - self.satiety
            drain["hydration"] += before[1] - self.hydration

            # --- 피해 ---
            damage = 0.0
            if self.satiety <= 0:
                damage += 2.0
            if self.hydration <= 0:
                damage += 4.0
            if self.energy <= 0:
                damage += 1.0
            exposure = 0.0
            if wild:                                   # 야외 노출: 극단적일수록 피해가 커진다
                if temp <= 0:
                    exposure += 1.0 + (-temp) / 10     # 체감 -20도 → 시간당 3
                elif temp >= 35:
                    exposure += 0.8 + (temp - 35) * 0.2
                if temp < 10 and self.weather["precipitation"] > 0:
                    exposure += 0.6                    # 젖은 채 추우면 저체온
                if self.biome == "jungle":
                    exposure += 0.3                    # 벌레·감염
                if activity == "sleep" and temp <= 0:
                    exposure *= 1.5                    # 혹한 속 노숙
                if sheltered:
                    exposure *= 0.25
                if self.weather["elevation"] >= 3500:
                    exposure += 0.5                    # 고산병은 쉘터로 막을 수 없다
            damage += exposure
            if damage == 0 and resting and self.satiety > 40 and self.hydration > 40:
                self.health = clamp(self.health + 1.5 * h)   # 잘 먹고 쉬면 회복
            else:
                self.health = clamp(self.health - damage * h)
            self.elapsed_hours += h
            self.wanted = max(0.0, self.wanted - WANTED_DECAY_PER_HOUR * h)
            if self.turn_flags.get("laying_low"):
                self.lay_low(h)                    # 숨어 지내면 수배도가 더 빨리 내려간다
            self._check_death("탈수·굶주림·혹독한 환경을 버티지 못했다")
        self.sync_weather()
        self.time_passed_this_turn = True

    def apply_delta(self, health=0, satiety=0, hydration=0, energy=0, money=0, reason=""):
        """행동/이벤트의 결과를 반영한다. LLM이 과하게 바꾸지 못하도록 범위를 제한한다."""
        self.health = clamp(self.health + clamp(health, -40, 30))
        self.satiety = clamp(self.satiety + clamp(satiety, -40, 60))
        self.hydration = clamp(self.hydration + clamp(hydration, -40, 60))
        self._note_gain("satiety", clamp(satiety, -40, 60))
        self._note_gain("hydration", clamp(hydration, -40, 60))
        self.energy = clamp(self.energy + clamp(energy, -40, 40))
        before = self.money
        self.money = round(max(0.0, self.money + clamp(money, -100000, MONEY_GAIN_LIMIT)), 2)
        if self.money < before:
            self.turn_flags["paid"] = self.turn_flags.get("paid", 0) + before - self.money
        elif self.money > before:
            self.turn_flags["earned"] = self.turn_flags.get("earned", 0) + self.money - before
        if self.money != before:
            self.turn_flags.setdefault("money_log", []).append({"amount": round(self.money - before, 2),
                                                                "why": reason or "상황 변화"})
        self._check_death(reason or "치명적인 부상을 입었다")

    # ---------- 이야기의 개연성: 사실과 단서 ----------
    def remember(self, text, scope="here"):
        """확정된 사실을 기록한다. here: 이 장소에서만 유효(이동하면 지움), always: 게임 내내 유효."""
        text = str(text).strip()[:120]
        if not text or any(f["text"] == text for f in self.facts):
            return
        scope = scope if scope in ("here", "always") else "here"
        self.facts.append({"text": text, "scope": scope, "turn": self.turn})
        for s, limit in (("here", 12), ("always", 12)):        # 너무 길어지지 않게 오래된 것부터 지운다
            same = [f for f in self.facts if f["scope"] == s]
            for old in same[:-limit]:
                self.facts.remove(old)

    def add_lead(self, kind, clue, bearing=None):
        """단서를 기록한다. 정체·방향·거리는 지금 정해지고, 따라가면 그대로 나타난다."""
        if kind not in leads_api.LEAD_KINDS:
            return None
        for lead in self.leads:                                   # 같은 단서를 두 번 만들지 않는다
            if lead["kind"] == kind and lead["clue"] == str(clue)[:80]:
                return lead
        self.lead_seq += 1
        lead = leads_api.make_lead(kind, clue, self.biome, bearing=bearing)
        lead.update(id=f"L{self.lead_seq}", turn=self.turn,
                    direction=leads_api.compass(lead["bearing"]))
        self.leads.append(lead)
        self.leads = self.leads[-5:]
        self.turn_flags["new_lead"] = lead["id"]
        return lead

    def find_lead(self, lead_id):
        return next((l for l in self.leads if l["id"] == str(lead_id).strip().upper()), None)

    def follow_lead(self, lead_id):
        """단서를 따라간다. 미리 정해 둔 정체가 그 방향·거리에 반드시 있다."""
        lead = self.find_lead(lead_id)
        if lead is None:
            return {"success": False, "message": f"그런 단서({lead_id})는 없다. [단서] 목록의 id 를 써라."}
        if self.turn_flags.get("travel"):
            return {"success": False, "message": "이번 턴에는 이미 이동했다."}
        speed = self.hazard["walk_speed"] if self.place_type == "야생" else 4.0
        if self.is_night:
            speed *= 0.65                                         # 밤에는 더디다
        if self.vehicle and self.vehicle.get("kind") != "boat":
            speed = max(speed, 25.0)                              # 탈것이 있으면 금방 간다
        hours = round(lead["km"] / speed, 2)
        self.pass_time(hours, "walk" if speed < 10 else "ride", sheltered=speed >= 10)
        self.turn_flags["travel"] = 1
        self.turn_flags["time"] = 1
        if self.status != "playing":
            return {"success": False, "message": "가는 도중 쓰러졌다."}
        self.lat, self.lon = geo.destination(self.lat, self.lon, lead["bearing"], lead["km"])
        found = leads_api.reveal(lead, self.biome, self.is_night)
        before = self.place_type
        self.place_type = found["place_type"]
        self.set_scene(found["setting"], found["scene"], found["description_en"], found["features"])
        if before != self.place_type:
            self.scene_dirty = True
        for effect in found["effects"]:
            if effect in ("on_road", "can_call"):
                self.flags[effect] = True
        self.leads.remove(lead)
        self.remember(f"{lead['direction']} {lead['km']}km를 걸어 {lead['label']}의 정체를 확인함: {found['text']}")
        self.turn_flags["lead_result"] = {"label": lead["label"], "scene": found["scene"], "text": found["text"],
                                          "hours": hours, "danger": "danger" in found["effects"]}
        return {"success": True, "걸린_시간": f"{hours:.1f}시간", "도착한_곳": found["scene"],
                "장소유형": self.place_type, "확정된_사실": found["text"],
                "보이는_것": found["features"],
                "안내": "이 사실과 어긋나지 않게 도착 장면을 서술하라. 장면은 엔진이 이미 바꿨으니 set_scene 은 부르지 않는다."}

    def _check_death(self, reason):
        if self.health <= 0 and self.status == "playing":
            self.status = "dead"
            self.death_reason = reason

    # ---------- 턴 진행 ----------
    def where(self):
        """지금 위치·장소의 요약 (턴 사이에 무엇이 바뀌었는지 비교용)."""
        return {"lat": self.lat, "lon": self.lon, "place_type": self.place_type, "place_name": self.place_name,
                "biome": self.biome}

    def place_changed(self):
        before = self._snapshot.get("where")
        return bool(before) and before["place_type"] != self.place_type

    def guard_unrequested_move(self):
        """안전장치: 이번 턴에 이동이 일어나지 않았는데(이동 툴이 성공하지 않았는데) 위치나 장소 유형이 바뀌었다면
        원래대로 되돌린다. 정상이라면 일어나지 않는 일이다. 되돌렸으면 True."""
        before = self._snapshot.get("where")
        if not before or self.turn_flags.get("travel"):
            return False
        now = self.where()
        if (now["lat"], now["lon"], now["place_type"]) == (before["lat"], before["lon"], before["place_type"]):
            return False
        print(f"[안전장치] 요청 없이 바뀐 위치를 되돌립니다: {before['place_type']} → {now['place_type']}")
        self.lat, self.lon = before["lat"], before["lon"]
        self.place_type, self.place_name, self.biome = before["place_type"], before["place_name"], before["biome"]
        self.distance = geo.distance_to_korea(self.lat, self.lon)
        return True

    def _tracked(self):
        return {"health": self.health, "satiety": self.satiety, "hydration": self.hydration,
                "energy": self.energy, "money": self.money, "wanted": self.wanted, "distance": self.distance,
                "hours": self.elapsed_hours}

    def begin_turn(self):
        """턴 시작: ML 모델로 위험도를 계산하고, 그에 따라 돌발 이벤트를 굴린다."""
        self.turn += 1
        self.time_passed_this_turn = False
        self.turn_flags = {"travel": 0, "time": 0, "intake": False, "consumed": False}
        self._snapshot = self._tracked()
        self._snapshot["night"] = self.is_night
        self._snapshot["where"] = self.where()
        self.refresh_risk()
        # 극한 지형의 야생에서는 이벤트 판정을 한 단계 더 위험하게 한다
        level = min(2, self.risk["level"] + 1) if self.in_extreme_wild else self.risk["level"]
        self.event = roll_event(self.biome, self.place_type, level, context=self.event_context())
        if self.event:
            lead = self.add_lead(self.event["lead"], self.event["text"]) if self.event.get("lead") else None
            if lead:
                self.event["lead_id"] = lead["id"]
                self.event["direction"] = lead["direction"]
            where = f" ({self.event['direction']} 방향)" if self.event.get("direction") else ""
            self.remember(f"{self.day}일차 {self.hour}시: {self.event['text']}{where}")
        scene = self.crime_scene
        here = scene and (scene["lat"], scene["lon"]) == (self.lat, self.lon)
        reaction = None
        if here and self.turn - scene["turn"] <= 4:
            who = scene["victim"] or "피해자"
            ago = self.elapsed_hours - scene["hours"]
            if scene["knocked_out"] and ago >= 2 and not scene.get("woke"):
                scene["woke"] = True               # 기절시킨 사람은 두어 시간 뒤 깨어난다
                reaction = f"쓰러져 있던 {who}이(가) 정신을 차리고 일어나 당신을 향해 소리친다."
            elif scene["witnessed"] != "none" and (self.turn == scene["turn"] + 1 or random.random() < 0.5):
                reaction = (f"{who}이(가) 사람들을 데리고 돌아와 당신을 찾고 있다." if self.place_type != "도시"
                            else "경찰차 사이렌 소리가 가까워진다. 누군가 신고한 것이다.")
        elif self.notorious_here() and self.place_type in ("마을", "도시") and random.random() < 0.35:
            reaction = "사람들이 당신을 알아보고 수군거린다. 누군가 경찰을 부르러 달려간다."
        if reaction:
            self.event = {"kind": "danger", "text": reaction}
        else:
            self.roll_police()                     # 수배 ★2 이상이면 경찰이 나타날 수 있다 (대응은 다음 턴에 판정)
        # 대형 이벤트(기회): 확률로 발생하고, 오래 안 나오면 반드시 나온다
        waited = self.turn - self.last_major_turn
        if self.offer is None and self.turn >= 3 and not reaction and (
                random.random() < MAJOR_EVENT_CHANCE or waited >= MAJOR_EVENT_PITY_TURNS):
            self.offer = roll_major_event(self.place_type, self.in_extreme_wild, self.indoor,
                                          allowed_needs=self.offer_needs())
            if self.offer and self.notorious_here() and self.offer["id"] in ("korean", "news", "trucker", "convoy"):
                self.offer = None                  # 범죄자로 알려진 곳에서는 아무도 돕겠다고 나서지 않는다
            if self.offer and (self.recently_expired(self.offer["id"]) or self.offer_closed(self.offer["id"])):
                self.offer = None                  # 방금 놓쳤거나 끝낸 기회가 곧바로 다시 찾아오지는 않는다
            if self.offer:
                self.offer = self.plan_offer(self.offer)
            if self.offer:               # 지금 장면에 맞는 기회가 없으면 다음 턴에 다시 시도한다
                self.offer["turn"] = self.turn
                self.last_major_turn = self.turn
                self.event = None        # 기회가 온 턴에는 일반 이벤트를 겹치지 않는다

    def end_turn(self, default_hours=0.5, default_activity="other"):
        """턴 종료: LLM이 시간을 흘리지 않았다면 엔진이 대신 흘리고, 수치 변화를 기록한다."""
        if not self.time_passed_this_turn and self.status == "playing" and default_hours > 0:
            self.pass_time(default_hours, default_activity)
        self.refresh_risk()
        if self.offer and self.offer.get("turn", 0) < self.turn and self.offer.get("id") not in PERSISTENT_OFFERS:
            self.expire_offer()          # 제안은 나온 다음 턴까지만 유효하다
        now = self._tracked()
        self.delta = {k: round(now[k] - self._snapshot.get(k, now[k]), 2) for k in now}
        # 낮↔밤 변화는 장면이 바뀐 것이 아니다. 그림은 같은 장면을 편집해 빛만 바꾼다 (app.py)

    def refresh_risk(self):
        self.risk = predict_risk(self.weather, self.health, self.satiety, self.hydration,
                                 self.energy, self.is_night, self.place_type == "야생")

    def summary(self):
        """LLM에게 매 턴 전달하는 현재 상태 요약."""
        w = self.weather
        return {
            "위치": f"{self.place_name} (위도 {self.lat}, 경도 {self.lon})",
            "장소유형": self.place_type,
            "지형": self.biome_name,
            "기후": climate_api.describe(self.climate),
            "시각": f"{self.day}일차 {self.hour}시 ({'밤' if self.is_night else '낮'})",
            "날씨": f"{w['description']}, 기온 {w['temperature']}도(체감 {w['feels_like']}도), "
                    f"습도 {w['humidity']}%, 풍속 {w['wind_speed']}km/h, 강수 {w['precipitation']}mm",
            "체력": round(self.health), "포만감": round(self.satiety),
            "수분": round(self.hydration), "기력": round(self.energy),
            "소지금_USD": self.money, "소지품": self.items,
            "한국까지_km": round(self.distance),
            "위험등급": self.risk["label"],
            "환경위험": self.hazard["desc"] if self.place_type == "야생" else "없음 (사람 사는 곳)",
            "보유_탈것": (f"{self.vehicle['name']} (연료로 약 {self.vehicle['range_km']}km"
                         + (", 훔친 차량" if self.vehicle.get("stolen") else "") + ")") if self.vehicle else "없음",
            "수배도": f"{self.wanted:.0f}/100 ({'★' * self.heat or '없음'})" + (" - 공항·항구 검문에서 붙잡힐 수 있음" if self.wanted >= WANTED_AIRPORT_LIMIT else ""),
            "초반_제한": (f"앞으로 약 {max(1, round(EARLY_GAME_HOURS - self.elapsed_hours))}시간은 도시·공항·공관으로 갈 수 "
                         "없다(마을까지만)") if self.early else "없음",
            "범죄의_여파": self.crime_aftermath() or "없음",
            "진행_중인_여정": (f"{self.journey['label']}까지 약 "
                               f"{geo.haversine_km(self.lat, self.lon, self.journey['lat'], self.journey['lon']):.0f}km 남음"
                               if self.journey else "없음"),
            "예약한_교통편": [f"{t['item']} (결제 완료, 탑승 대기 중)" for t in self.tickets] or "없음",
            "현재장면": f"{'실내' if self.indoor else '야외'}" + (f" - {self.scene_place}" if self.scene_place else ""),
        }


def create_game():
    """랜덤 육지 좌표에서 새 게임을 만든다."""
    lat, lon, _ = geo.pick_random_land()
    weather = get_weather(lat, lon)
    place = geo.reverse_geocode(lat, lon)
    distance = geo.distance_to_korea(lat, lon)
    state = GameState(
        lat=lat, lon=lon,
        place_name=place["name"] if place else "이름 모를 땅",
        weather=dict(weather),
        biome=classify_biome(lat, weather),
        start_hour=weather["local_hour"],
        start_offset=float(weather.get("utc_offset", 0)),
        utc_offset=float(weather.get("utc_offset", 0)),
        start_distance=distance, distance=distance,
    )
    state.country_code = (place or {}).get("country_code", "")
    state.place_name_en = (place or {}).get("name_en", "")
    state.country_en = (place or {}).get("country_en", "")
    state.set_weather(weather)
    state.refresh_climate()
    state.biome = classify_biome(lat, state.weather, state.climate)
    state.refresh_risk()
    return state
