"""게임 상태와 규칙(엔진). 숫자 계산은 전부 여기서 하고, LLM은 서술만 담당한다."""
import math
import random
import re
from dataclasses import dataclass, field

from . import climate as climate_api
from . import geo, leads as leads_api, places
from .config import (ARRIVAL_RADIUS_KM, ATTEMPT_CHANCE, ATTEMPT_FAIL_DAMAGE, CRIMES,
                     EARLY_GAME_HOURS, EARLY_MAX_TRAVEL_KM, MONEY_GAIN_LIMIT,
                     JOURNEY_MAX_HOURS, VILLAGE_DISTANCE,
                     DIURNAL_AMPLITUDE, LAND_METHODS, WITNESS,
                     MAJOR_EVENT_CHANCE, VEHICLES, WANTED_AIRPORT_LIMIT, WANTED_DECAY_PER_HOUR,
                     WANTED_ON_FAIL, WANTED_ON_SUCCESS,
                     MAJOR_EVENT_PITY_TURNS, START_ITEMS, START_MONEY, TRAVEL_RULES,
                     VITALS_DRAIN)
from .events import (BIOME_HAZARDS, BIOMES, classify_biome, roll_event,
                     roll_major_event)
from .risk_model import predict_risk
from .weather import get_weather, weather_category


def clamp(value, low=0.0, high=100.0):
    return max(low, min(high, value))


# 소지품이 될 수 없는 것들 (LLM이 넣으려 해도 엔진이 거부한다)
NOT_CARRYABLE = ("오두막", "건물", "동굴", "쉘터", "움막", "대피소", "오아시스", "개울", "호수",
                 "우물", "물줄기", "웅덩이", "모닥불", "마을", "도시", "자동차", "트럭", "헬기",
                 "나룻배", "화물선", "야자수", "과일나무", "발자국", "임도", "도로", "신호")
# 탈것과 큰 동물: 소지품이 아니라 acquire_vehicle 로 얻는다
VEHICLE_WORDS = ("차량", "승용차", "자동차", "트럭", "픽업", "지프", "밴", "버스", "택시", "오토바이", "스쿠터",
                 "자전거", "보트", "카누", "카약", "뗏목", "요트", "트랙터", "헬기", "헬리콥터", "비행기",
                 "나룻배", "화물선", "설상차", "썰매", "말 한 마리", "낙타", "당나귀", "노새", "야크")
IMPOSSIBLE = ("텔레포트", "순간이동", "마법", "타임머신", "워프", "포탈", "요술", "초능력",
              "제트팩", "광선", "무한", "소원", "투명", "부활", "치트")


TICKET_WORDS = ("티켓", "항공권", "탑승권", "승차권", "승선권", "버스표", "기차표", "열차표", "배표", "비행기표")


def item_problem(name):
    """소지품으로 넣을 수 없는 이름이면 그 이유를, 문제없으면 None을 반환한다."""
    if any(word in name for word in TICKET_WORDS):
        return "교통편 표는 buy_ticket 으로만 구매할 수 있음"
    if any(word in name for word in IMPOSSIBLE):
        return "현실에 존재하지 않는 물건"
    if any(k in name for k in ("열쇠", "키", "모형", "장난감", "사진", "그림", "부품")):
        return None                  # '트럭 열쇠', '배 모형'처럼 탈것·장소 이름이 들어간 작은 물건
    if any(word in name for word in VEHICLE_WORDS):
        return "탈것은 소지품이 아님 — 탈것을 얻었다면 acquire_vehicle 로 처리"
    if any(word in name for word in NOT_CARRYABLE):
        return "들고 다닐 수 없는 장소·지형·탈것"
    return None


def item_core(name):
    """'에너지바 2개', '빗물(1회분)' → '에너지바', '빗물' : 수량과 괄호를 뗀 물건 이름."""
    core = re.sub(r"\(.*?\)|\d+(?:\.\d+)?\s*(?:개|병|L|l|리터|회분|모금|장|통|캔|봉지|알)?", "", name)
    return core.replace(" ", "")


@dataclass
class GameState:
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
    turn_flags: dict = field(default_factory=dict)   # 이번 턴에 한 일 (툴 남용 방지용)
    # 현재 장면: 플레이어가 지금 서 있는 구체적인 곳 (이미지와 이벤트 판정에 쓰인다)
    scene_setting: str = "outdoor"    # outdoor / indoor
    scene_place: str = ""             # 예: "빈 오두막 안", "버스 터미널", "강가"
    scene_desc: str = ""              # 이미지용 영어 묘사
    scene_features: list = field(default_factory=list)   # GM이 밝힌, 그 장면에 보이는 것들
    scene_seen: list = field(default_factory=list)       # 생성된 이미지를 Vision으로 읽어낸, 실제로 그려진 것들
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
    flags: dict = field(default_factory=dict)            # on_road, can_call, embassy_visited, at_airport, at_embassy
    characters: list = field(default_factory=list)       # 이 장소에서 만난 인물 [{name, role, look}]
    journey: dict | None = None       # 여러 턴에 걸친 목적지 이동 {type, name, label, lat, lon, place}
    image_scene: str = ""             # 지금 그림이 그려진 장면 (장소+장면 이름)
    image_night: bool = False         # 지금 그림이 밤 그림인지
    wanted: float = 0.0               # 수배도 0~100
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
        person = {"name": name, "role": role, "look": look}
        self.characters.append(person)
        self.characters = self.characters[-6:]
        return person

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
            self.satiety = clamp(self.satiety - hunger * h)
            self.hydration = clamp(self.hydration - thirst * h)
            self.energy = clamp(self.energy + energy_rate * h)

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
            self._check_death("탈수·굶주림·혹독한 환경을 버티지 못했다")
        self.sync_weather()
        self.time_passed_this_turn = True

    def apply_delta(self, health=0, satiety=0, hydration=0, energy=0, money=0, reason=""):
        """행동/이벤트의 결과를 반영한다. LLM이 과하게 바꾸지 못하도록 범위를 제한한다."""
        self.health = clamp(self.health + clamp(health, -40, 30))
        self.satiety = clamp(self.satiety + clamp(satiety, -40, 60))
        self.hydration = clamp(self.hydration + clamp(hydration, -40, 60))
        self.energy = clamp(self.energy + clamp(energy, -40, 40))
        before = self.money
        self.money = round(max(0.0, self.money + clamp(money, -100000, MONEY_GAIN_LIMIT)), 2)
        if self.money < before:
            self.turn_flags["paid"] = self.turn_flags.get("paid", 0) + before - self.money
        elif self.money > before:
            self.turn_flags["earned"] = self.turn_flags.get("earned", 0) + self.money - before
        self._check_death(reason or "치명적인 부상을 입었다")

    def find_item(self, name):
        """소지품에서 물건을 찾는다. 정확한 이름 → 핵심 이름 → 포함 관계 순으로 느슨하게 맞춰 본다."""
        name = str(name).strip()
        core = item_core(name)
        tests = [
            lambda item: item == name,
            lambda item: bool(core) and item_core(item) == core,
            lambda item: name in item or item in name,
            lambda item: len(core) >= 2 and len(item_core(item)) >= 2
                         and (core in item_core(item) or item_core(item) in core),
        ]
        for test in tests:
            for item in self.items:
                if test(item):
                    return item
        return None

    def consume_item(self, name):
        """물건을 한 번 써서 없앤다. '에너지바 2개'처럼 수량이 있으면 하나만 줄인다."""
        item = self.find_item(name)
        if item is None:
            return False
        count = re.search(r"(\d+)\s*(개|병|장|캔|봉지|알)", item)
        index = self.items.index(item)
        if count and int(count.group(1)) > 1:
            left = int(count.group(1)) - 1
            self.items[index] = item[:count.start(1)] + str(left) + item[count.end(1):]
        else:
            self.items.pop(index)
        self.turn_flags["consumed"] = True
        return True

    def update_items(self, add=None, remove=None):
        """소지품을 추가/제거한다. 넣을 수 없는 것은 거부하고 그 목록을 반환한다."""
        rejected = []
        for name in remove or []:
            item = self.find_item(name)
            if item:
                self.items.remove(item)
                self.turn_flags["consumed"] = True
        for entry in add or []:
            # {"name": ..., "carryable": ...} 또는 그냥 문자열
            name = str(entry.get("name", "") if isinstance(entry, dict) else entry).strip()[:30]
            carryable = entry.get("carryable", True) if isinstance(entry, dict) else True
            if not name:
                continue
            problem = item_problem(name) or (None if carryable else "들고 다닐 수 없는 것")
            if problem:
                rejected.append(f"{name} ({problem})")
            elif len(self.items) >= 15:
                rejected.append(f"{name} (배낭이 가득 참)")
            else:
                self.items.append(name)
        return rejected

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

    # ---------- 자유 행동 ----------
    def attempt(self, action, difficulty="normal", crime="none", witnessed="none", violent=False,
                item="", stealth=False, success_money=0, success_items=None):
        """결과가 불확실한 행동을 판정한다. 성공 확률은 엔진이 계산하고 주사위를 굴린다.

        GM은 난이도, 범죄 종류, 목격자, 폭력 여부만 정하고 성공 여부는 정하지 못한다.
        수배도는 현실에서 범죄인 행동을 누군가 목격했을 때만 오른다.
        """
        if self.turn_flags.get("attempt"):
            return {"error": "이번 턴에는 이미 시도 판정을 했다. 한 턴에는 시도 하나만 판정한다."}
        difficulty = difficulty if difficulty in ATTEMPT_CHANCE else "normal"
        chance = ATTEMPT_CHANCE[difficulty]
        reasons = []
        if self.energy < 30:
            chance -= 0.15
            reasons.append("지쳐 있음 -15%")
        if self.health < 40:
            chance -= 0.15
            reasons.append("부상 -15%")
        used = self.find_item(item) if item else None
        if used:
            chance += 0.15
            reasons.append(f"{used} 사용 +15%")
        if stealth and self.is_night:
            chance += 0.10
            reasons.append("어둠을 틈탐 +10%")
        chance = round(min(0.95, max(0.05, chance)), 2)
        success = random.random() < chance

        effects = []
        if not success and violent:
            damage = ATTEMPT_FAIL_DAMAGE[difficulty]
            self.health = clamp(self.health - damage)
            effects.append(f"몸싸움 끝에 체력 -{damage}")
            self._check_death("무모한 시도가 마지막이 되었다")
        crime = crime if crime in CRIMES else "none"
        witnessed = witnessed if witnessed in WITNESS else "none"
        if crime != "none":
            if not success and witnessed == "none":
                witnessed = "victim"       # 실패하면 들키기 마련이다 (피해자·관계자가 알아챔)
            gain = round((WANTED_ON_SUCCESS if success else WANTED_ON_FAIL) * CRIMES[crime] * WITNESS[witnessed])
            if gain > 0:
                self.wanted = clamp(self.wanted + gain)
                effects.append(f"{crime} 목격됨 → 수배도 +{gain} (현재 {self.wanted:.0f})")
            else:
                effects.append(f"{crime} — 목격자 없음, 수배되지 않음")
        rejected = []
        if success:                       # 성공의 대가: 미리 걸어 둔 돈·물건을 엔진이 직접 넣는다
            gain = round(clamp(float(success_money or 0), 0, MONEY_GAIN_LIMIT), 2)
            if gain:
                self.money = round(self.money + gain, 2)
                self.turn_flags["earned"] = self.turn_flags.get("earned", 0) + gain
                effects.insert(0, f"+${gain:,.0f}")
            if success_items:
                before = list(self.items)
                rejected = self.update_items(add=list(success_items))
                got = [i for i in self.items if i not in before]
                if got:
                    effects.insert(0, "얻은 물건: " + ", ".join(got))
        self.turn_flags["attempt"] = {"action": str(action)[:40], "chance": chance, "success": success,
                                      "illegal": crime != "none", "crime": crime, "effects": effects}
        return {"success": success, "chance": f"{chance * 100:.0f}%", "보정": reasons or ["없음"],
                "엔진이_적용한_결과": effects or ["없음"],
                **({"거부된_물건": rejected} if rejected else {}),
                "안내": ("성공했다. 걸어 둔 돈·물건은 엔진이 이미 넣었다(다시 넣지 마라). 탈것을 얻었다면 "
                        "acquire_vehicle 을 호출하라." if success else
                        "실패했다. 목표를 이루지 못했다. 실패를 그대로 서술하고, 상대의 반응(반격, 신고, 도주)을 "
                        "현실적으로 그려라. 이미 엔진이 적용한 피해를 다시 적용하지 마라.")}

    def pay(self, amount, purpose=""):
        """물건·서비스 값을 낸다. 돈이 모자라면 아무것도 내지 않고 실패한다."""
        amount = round(max(0.0, float(amount)), 2)
        if amount <= 0:
            return {"success": False, "message": "낼 금액이 0이다."}
        if amount > self.money:
            return {"success": False,
                    "message": f"돈이 모자란다. {purpose or '값'} ${amount:.0f}, 가진 돈 ${self.money:.0f}. "
                               "사지 못했다고 서술하라."}
        self.money = round(self.money - amount, 2)
        self.turn_flags["paid"] = self.turn_flags.get("paid", 0) + amount
        return {"success": True, "message": f"{purpose or '값'}으로 ${amount:.0f}을(를) 냈다. 남은 돈 ${self.money:.0f}."}

    def acquire_vehicle(self, kind, name=""):
        """탈것을 손에 넣는다. 같은 턴에 성공한 시도(탈취, 구매 협상 등)가 있어야 한다."""
        attempt = self.turn_flags.get("attempt")
        if not attempt or not attempt["success"]:
            return {"success": False,
                    "message": "탈것을 얻으려면 같은 턴에 attempt_action 으로 시도해서 성공해야 한다."}
        if kind not in VEHICLES:
            return {"success": False, "message": f"알 수 없는 탈것 종류: {kind}"}
        spec = VEHICLES[kind]
        label = str(name or spec["label"]).strip()[:20]
        fuel = round(spec["range"] * random.uniform(0.4, 0.9))   # 연료는 얼마나 남아 있을지 모른다
        self.vehicle = {"kind": kind, "name": label, "speed": spec["speed"], "range_km": fuel,
                        "sea": spec["sea"], "stolen": attempt["illegal"]}
        if self.offer and self.offer.get("id") in ("trucker", "convoy"):
            self.offer = None             # 태워 주겠다던 차를 빼앗았다면 그 제안은 끝난 것이다
        self.remember(f"{label}을(를) 손에 넣음" + (" (훔친 것)" if attempt["illegal"] else ""), "always")
        self.turn_flags["vehicle"] = dict(self.vehicle)
        return {"success": True,
                "message": f"{label}을(를) 손에 넣었다. 연료로 약 {fuel}km를 갈 수 있다. "
                           "플레이어가 운전해서 가겠다고 하면 다음 턴부터 travel(method='drive') 로 이동한다."}

    def _arrest(self, where):
        """붙잡혔다: 하루를 잃고, 벌금을 내고, 탈것과 표를 압수당한다."""
        fine = round(self.money * 0.5, 2)
        self.money = round(self.money - fine, 2)
        lost = []
        if self.vehicle:
            lost.append(self.vehicle["name"])
            self.vehicle = None
        for ticket in list(self.tickets):
            lost.append(ticket["item"])
            self.tickets.remove(ticket)
            if ticket["item"] in self.items:
                self.items.remove(ticket["item"])
        self.pass_time(12, "rest", sheltered=True)
        self.pass_time(12, "rest", sheltered=True)
        self.wanted = clamp(self.wanted - 40)
        self.turn_flags["arrested"] = {"where": where, "fine": fine, "lost": lost}
        return {"success": False, "arrested": True,
                "message": f"{where}에서 붙잡혔다. 하루 동안 구금된 뒤 벌금 ${fine:.0f}을(를) 내고 풀려났다."
                           + (f" 압수당한 것: {', '.join(lost)}." if lost else "")}

    def arrest(self, reason=""):
        """GM이 경찰에게 붙잡히는 상황을 처리할 때 쓴다. 수배도가 있어야 한다."""
        if self.wanted <= 0:
            return {"success": False, "message": "수배된 상태가 아니므로 체포될 이유가 없다."}
        return self._arrest(reason or "검문")

    def _drive(self, km):
        """손에 넣은 탈것으로 한국 방향으로 이동한다. 장소 유형 제한도, 요금도 없다."""
        v = self.vehicle
        if not v:
            return {"success": False, "message": "운전할 탈것이 없다."}
        km = clamp(float(km), 1, min(v["range_km"], self.distance))
        if self.early:
            km = min(km, EARLY_MAX_TRAVEL_KM)
        new_lat, new_lon = geo.move_toward_korea(self.lat, self.lon, km)
        arriving = geo.distance_to_korea(new_lat, new_lon) <= ARRIVAL_RADIUS_KM
        if not v["sea"] and not arriving and geo.is_land(new_lat, new_lon) is False:
            return {"success": False, "message": "그 방향은 바다로 막혀 있다. 이 탈것으로는 건널 수 없다."}
        self.pass_time(km / v["speed"], "ride", sheltered=True)
        v["range_km"] = round(v["range_km"] - km)
        name = v["name"]
        empty = v["range_km"] <= 5
        if empty:
            self.vehicle = None
        arrived = self._relocate(new_lat, new_lon, km, "hitchhike")
        self.turn_flags["moved"] = {"how": name, "km": round(km), "cost": 0, "ticket": None}
        tail = f" 연료가 바닥나 {name}을(를) 버려야 했다." if empty else f" 남은 연료로 약 {v['range_km']}km를 더 갈 수 있다."
        if arrived:
            return {"success": True, "arrived_in_korea": True,
                    "message": f"{name}을(를) 몰고 {km:.0f}km를 달려 마침내 한국에 도착했다!"}
        return {"success": True, "arrived_in_korea": False,
                "message": f"{name}을(를) 몰고 {km:.0f}km를 이동했다. 도착한 곳: {self.place_name} "
                           f"({self.place_type}, {self.biome_name}). 한국까지 {self.distance:.0f}km 남았다." + tail}

    def find_ticket_by_item(self, item):
        return next((t for t in self.tickets if t["item"] == item), None)

    def find_ticket(self, method):
        return next((t for t in self.tickets if t["method"] == method), None)

    def buy_ticket(self, method, km):
        """교통편을 미리 예약(결제)한다. 표는 소지품과 예약 목록에 남고, 탈 때 자동으로 쓰인다."""
        if method not in TRAVEL_RULES or TRAVEL_RULES[method]["per_km"] == 0:
            return {"success": False, "message": "표를 살 수 있는 교통편은 버스, 기차, 배, 비행기뿐이다."}
        rule = TRAVEL_RULES[method]
        if self.place_type not in rule["places"]:
            return {"success": False,
                    "message": f"{rule['label']} 표는 {'/'.join(rule['places'])}에서만 살 수 있다. "
                               f"현재 위치는 {self.place_type}."}
        if self.find_ticket(method):
            return {"success": False, "message": f"이미 {self.find_ticket(method)['item']}을(를) 가지고 있다."}
        km = clamp(float(km), 1, min(rule["max_km"], self.distance))
        if method == "flight":
            km = self.distance
        cost = self.fare(method, km)
        if cost > self.money:
            return {"success": False,
                    "message": f"돈이 부족하다. {rule['label']} {km:.0f}km 요금 ${cost:.0f}, 보유 ${self.money:.0f}."}
        self.money = round(self.money - cost, 2)
        self.turn_flags["paid"] = self.turn_flags.get("paid", 0) + cost
        item = "한국행 항공권" if method == "flight" else f"{rule['label']} 티켓({km:.0f}km)"
        self.tickets.append({"method": method, "km": round(km), "item": item, "price": cost})
        self.items.append(item)
        self.turn_flags["ticket"] = {"item": item, "price": cost}
        return {"success": True, "cost": cost,
                "message": f"{item}을(를) ${cost:.0f}에 구매했다. 아직 타지는 않았다. "
                           f"플레이어가 탑승하겠다고 하면 travel(method='{method}') 을 호출하면 된다(추가 요금 없음)."}

    def fare(self, method, km):
        rule = TRAVEL_RULES[method]
        return round(rule["base"] + rule["per_km"] * km, 2)

    def travel(self, method, km):
        """한국 방향으로 이동한다. 결과(성공 여부와 설명)를 딕셔너리로 반환한다."""
        if method == "drive":
            return self._drive(km)
        if method not in TRAVEL_RULES:
            return {"success": False, "message": f"알 수 없는 이동 수단: {method}"}
        rule = TRAVEL_RULES[method]
        ticket = self.find_ticket(method)
        if self.place_type not in rule["places"]:
            return {"success": False,
                    "message": f"{rule['label']}은(는) {'/'.join(rule['places'])}에서만 이용할 수 있다. "
                               f"현재 위치는 {self.place_type}."
                               + (f" ({ticket['item']}은(는) 그대로 가지고 있다.)" if ticket else "")}
        if self.early and method in ("train", "ship", "flight"):
            return {"success": False, "message": self.early_message()}
        km = clamp(float(km), 1, min(rule["max_km"], self.distance))
        if self.early:
            km = min(km, EARLY_MAX_TRAVEL_KM)
        if ticket:
            km = min(float(ticket["km"]), self.distance)   # 예약해 둔 구간만큼 간다
        if method == "flight":
            km = self.distance            # 비행기는 언제나 한국까지 직항이다 (중간 기착 없음)
        cost = 0.0 if ticket else self.fare(method, km)   # 이미 결제한 표가 있으면 요금을 다시 받지 않는다
        if cost > self.money:
            return {"success": False,
                    "message": f"돈이 부족하다. {rule['label']} {km:.0f}km 요금 ${cost:.0f}, 보유 ${self.money:.0f}."}
        if method == "flight" and not self.flags.get("at_airport") and "airport" not in self.offer_needs():
            return {"success": False,
                    "message": "이 도시에서 국제선 비행기를 탈 방법을 아직 찾지 못했다. 한국 공관의 도움을 받거나 "
                               "며칠 더 버틴 뒤 공항으로 가는 길을 찾아야 한다."
                               + (f" ({ticket['item']}은(는) 그대로 가지고 있다.)" if ticket else "")}
        if method in ("flight", "ship") and self.wanted >= WANTED_AIRPORT_LIMIT \
                and random.random() < self.wanted / 100:
            return self._arrest("공항 출국 심사" if method == "flight" else "항구 검문")
        hitch_chance = self.hazard["hitch"] if self.place_type == "야생" else 0.6
        if self.flags.get("on_road"):
            hitch_chance = min(0.85, hitch_chance + 0.3)      # 차가 다니는 도로 위
        if self.is_night:
            hitch_chance *= 0.5
        if method == "hitchhike" and random.random() > hitch_chance:
            self.pass_time(1.5, "other")
            return {"success": False, "message": "1시간 반을 기다렸지만 태워주는 차가 없었다."}

        new_lat, new_lon = geo.move_toward_korea(self.lat, self.lon, km)
        arriving = geo.distance_to_korea(new_lat, new_lon) <= ARRIVAL_RADIUS_KM
        if method in LAND_METHODS and not arriving and geo.is_land(new_lat, new_lon) is False:
            return {"success": False,
                    "message": "그 방향으로는 바다가 가로막고 있다. 육로로는 더 갈 수 없다. "
                               "도시에서 배나 비행기를 타거나, 더 짧은 거리를 이동해야 한다."}

        self.money = round(self.money - cost, 2)
        if cost:
            self.turn_flags["paid"] = self.turn_flags.get("paid", 0) + cost
        if ticket:             # 표는 타는 순간 쓰고 없어진다
            self.tickets.remove(ticket)
            if ticket["item"] in self.items:
                self.items.remove(ticket["item"])
        if method == "walk":   # 험한 지형에서는 걷는 속도가 느려진다
            speed = self.hazard["walk_speed"] if self.place_type == "야생" else rule["speed"]
            self.pass_time(km / speed, "walk")
        else:
            self.pass_time(km / rule["speed"], "ride", sheltered=True)
        arrived = self._relocate(new_lat, new_lon, km, method)
        self.turn_flags["moved"] = {"how": rule["label"], "km": round(km), "cost": cost,
                                    "ticket": ticket["item"] if ticket else None}
        if arrived:
            return {"success": True, "arrived_in_korea": True,
                    "message": f"{rule['label']}(으)로 {km:.0f}km 이동해 마침내 한국에 도착했다!"}
        return {"success": True, "arrived_in_korea": False, "cost": cost,
                "message": f"{rule['label']}(으)로 {km:.0f}km 이동했다. 요금 ${cost:.0f}. "
                           f"도착한 곳: {self.place_name} ({self.place_type}, {self.biome_name}). "
                           f"한국까지 {self.distance:.0f}km 남았다."}

    def _relocate(self, new_lat, new_lon, km, method):
        """좌표를 옮기고 새 장소 정보를 갱신한다. 한국에 도착했으면 True."""
        self.lat, self.lon = new_lat, new_lon
        self.distance = geo.distance_to_korea(new_lat, new_lon)
        self.moved_since_image += km
        if km >= 300:
            self.wanted = clamp(self.wanted - 15)     # 멀리 떠나면 쫓는 사람이 줄어든다
        self.turn_flags["scene_changed"] = True
        self.scene_setting, self.scene_place, self.scene_desc = "outdoor", "", ""   # 새 장소의 야외에서 시작
        self.scene_features, self.scene_seen = [], []
        if km >= 20:          # 멀리 떠나면 그곳의 단서와 '여기서만' 유효한 사실은 더 이상 의미가 없다
            self.leads = []
            self.facts = [f for f in self.facts if f["scope"] == "always"]
            for flag in ("on_road", "can_call", "at_airport"):
                self.flags.pop(flag, None)
        self.scene_dirty = True
        if self.distance <= ARRIVAL_RADIUS_KM:
            self.distance = 0.0
            self.place_name, self.place_type = "대한민국, 서울", "도시"
            self.place_name_en, self.country_en, self.country_code = "South Korea, Seoul", "South Korea", "kr"
            self.scene_dirty = True
            if self.status == "playing":
                self.status = "won"
            return True
        self._arrive_at_new_place(method)
        return False

    def offer_needs(self):
        """조건이 붙은 기회 중 지금 허용되는 것."""
        needs = []
        if self.early:
            return tuple(needs)
        # 공관과 연락이 닿을 수 있다: 사람 사는 곳에 있거나, 전화가 되는 곳에 있다
        if not self.flags.get("embassy_visited") and (self.place_type in ("마을", "도시") or self.flags.get("can_call")):
            needs.append("contact")
        # 공항: 바로 한국으로 갈 수 있는 곳이라 초반에는 나오지 않는다.
        # 공관을 다녀왔거나(서류·지원금 확보) 충분히 오래 버틴 뒤, 도시에 있을 때만 나온다.
        if self.place_type == "도시" and not self.flags.get("at_airport") and \
                (self.flags.get("embassy_visited") or self.day >= 5):
            needs.append("airport")
        return tuple(needs)

    def plan_offer(self, offer):
        """기회의 목적지를 실제 지도 위에서 정한다. 갈 수 있는 곳이 없으면 None."""
        move = offer.get("move") or {}
        to = move.get("to")
        if not to:
            offer["text"] = offer["text"].replace("{dest}", "")
            return self._finish_offer(offer)
        city = None
        if self.early:
            if to in ("embassy", "airport", "port_toward_korea"):
                return None
            to = "village"                 # 초반에는 가까운 마을까지만 데려다준다
        if to in ("city_or_village", "rescue"):
            limit = 250 if to == "rescue" else move["max_km"]
            city = places.nearest_city(self.lat, self.lon, max_km=limit)
            if city and city["km"] < 15:
                city = None                    # 이미 그 도시에 있다
        elif to == "embassy":
            city = places.nearest_city(self.lat, self.lon, country=self.country_code, mission=True)
            if not city or city["km"] > move["max_km"]:
                return None
        elif to == "airport":
            city = places.nearest_city(self.lat, self.lon, max_km=move["max_km"], airport=True)
            if not city:
                return None
        if city:
            dest = {"type": to, "name": city["name"], "lat": city["lat"], "lon": city["lon"],
                    "km": round(city["km"]), "place": "도시"}
            if to == "embassy":
                dest["label"] = f"{city['name']}의 {places.mission_label(city)}"
            elif to == "airport":
                dest["label"] = city["name"]
            else:
                dest["label"] = city["name"]
        elif to == "port_toward_korea":
            km = min(random.randint(1200, move["max_km"]), max(1, self.distance - 1))
            lat, lon = geo.move_toward_korea(self.lat, self.lon, km)
            port = places.nearest_city(lat, lon, max_km=400)
            if port:
                lat, lon = port["lat"], port["lon"]
            dest = {"type": to, "name": port["name"] if port else "항구 도시", "lat": lat, "lon": lon,
                    "km": round(geo.haversine_km(self.lat, self.lon, lat, lon)), "place": "도시",
                    "label": f"{port['name']} 항구" if port else "한국 쪽 항구 도시"}
        else:
            # 가까운 도시가 없으면 근처 마을. 마을은 대체로 한국 쪽이지만 꼭 그 방향은 아니다.
            km = (random.randint(20, EARLY_MAX_TRAVEL_KM) if self.early else
                  random.randint(30, 120) if to == "rescue" else random.randint(60, 250))
            base = geo.bearing_deg(self.lat, self.lon, *geo.SEOUL)
            for _ in range(4):
                lat, lon = geo.destination(self.lat, self.lon, base + random.uniform(-100, 100), km)
                if geo.is_land(lat, lon) is not False:
                    break
            dest = {"type": to, "name": "근처 마을", "lat": lat, "lon": lon, "km": km, "place": "마을",
                    "label": f"{leads_api.compass(geo.bearing_deg(self.lat, self.lon, lat, lon))}으로 약 {km}km 떨어진 마을"}
        offer["dest"] = dest
        offer["text"] = offer["text"].replace("{dest}", dest["label"])
        return self._finish_offer(offer)

    def seek_help(self, kind, go_now=True):
        """귀국을 위한 도움. 공관·공항으로 가는 것은 go_to 와 같다(지금 상황에서 갈 수 있는 만큼 간다)."""
        if kind == "repatriation":
            return self.repatriate()
        if kind in ("embassy", "airport"):
            return self.go_to(kind)
        return {"success": False, "message": "kind 는 embassy, airport, repatriation 중 하나다."}

    # ---------- 목적지로 가기 ----------
    def go_to(self, target):
        """플레이어가 목적지(가까운 마을·도시, 한국 공관, 공항)로 가려 할 때.

        지금 있는 곳과 가진 수단(걷기, 탈것, 버스, 기차, 돈)으로 현실적으로 갈 수 있는 만큼만 간다.
        곧장 갈 수 없는 곳이면 먼저 갈 수 있는 곳(마을, 도시)부터 가고, 한 턴에 다 못 가면 중간에서 멈춘다.
        """
        if self.status != "playing":
            return {"success": False, "message": "게임이 끝났다."}
        if self.turn_flags.get("travel"):
            return {"success": False, "message": "이번 턴에는 이미 이동했다. 다음 턴에 이어서 가자."}
        notes = []
        if target == "continue":
            if not self.journey:
                return {"success": False, "message": "이어서 갈 여정이 없다. 어디로 갈지 정해야 한다."}
            return self._advance_journey(notes)

        if target == "village":
            if self.place_type in ("마을", "도시"):
                return {"success": False, "message": f"이미 사람 사는 곳({self.place_type})에 있다."}
            return self._head_to_village(notes)

        if target in ("city", "embassy", "airport") and self.early:
            if self.place_type == "야생" and not (target == "embassy" and self.flags.get("can_call")):
                notes.append(self.early_message() + " 우선 가장 가까운 마을로 향한다.")
                return self._head_to_village(notes)
            if target == "embassy" and self.flags.get("can_call") and not self.flags.get("embassy_contacted"):
                pass                       # 전화 통화는 초반에도 된다 (아래에서 처리)
            else:
                return {"success": False, "message": self.early_message()}

        if target == "city":
            city = places.nearest_city(self.lat, self.lon)
            if city and city["km"] < 15:
                return {"success": False, "message": f"이미 {city['name']}에 있다."}
            dest = {"type": "city", "name": city["name"], "label": city["name"], "lat": city["lat"],
                    "lon": city["lon"], "place": "도시"}
            return self._start_journey(dest, notes)

        if target == "embassy":
            if self.flags.get("embassy_visited"):
                return {"success": False, "message": "이미 공관의 도움을 받았다."}
            if self.place_type in ("마을", "도시") and not self.early:
                return self._go_embassy_now()
            # 야생: 순간이동은 없다. 전화가 되면 통화만 하고, 먼저 사람 사는 곳으로 간다.
            if self.flags.get("can_call") and not self.flags.get("embassy_contacted"):
                self.flags["embassy_contacted"] = True
                self.pass_time(0.5, "other")
                self.remember("공관 영사와 통화했다. 가장 가까운 마을이나 도시에 닿으면 그곳에서 공관까지 오는 "
                              "교통편을 마련해 주기로 했다.", "always")
                notes.append("공관 영사와 통화가 연결되었다. 영사는 가장 가까운 마을이나 도시에 닿으면 그곳에서 "
                             "공관까지 오는 교통편을 마련해 주겠다고 했다.")
            elif not self.flags.get("embassy_contacted"):
                notes.append("여기서는 공관에 연락할 방법이 없다. 먼저 사람 사는 곳으로 가야 한다.")
            else:
                notes.append("영사와는 이미 통화해 두었다. 사람 사는 곳에 닿으면 교통편을 받을 수 있다.")
            return self._head_to_village(notes)

        if target == "airport":
            if self.place_type == "도시":
                return self._go_airport_now()
            notes.append("공항은 도시에 있다. 먼저 도시로 향한다.")
            city = places.nearest_city(self.lat, self.lon, airport=True)
            dest = {"type": "city", "name": city["name"], "label": city["name"], "lat": city["lat"],
                    "lon": city["lon"], "place": "도시"}
            return self._start_journey(dest, notes)
        return {"success": False, "message": "target 은 village, city, embassy, airport, continue 중 하나다."}

    def _head_to_village(self, notes):
        """야생에서 가장 가까운 마을로. 마을로 이어지는 단서가 있으면 그것을 따라간다."""
        lead = next((l for l in self.leads if l["target"] == "village"), None)
        if lead and not self.vehicle:
            result = self.follow_lead(lead["id"])
            result["message"] = " ".join(notes + [f"{lead['label']} 쪽에 마을이 있었다."])
            return result
        lo, hi = VILLAGE_DISTANCE.get(self.biome, (10, 40))
        km = round(random.uniform(lo, hi), 1)
        base = geo.bearing_deg(self.lat, self.lon, *geo.SEOUL)
        for _ in range(4):
            bearing = base + random.uniform(-90, 90)
            lat, lon = geo.destination(self.lat, self.lon, bearing, km)
            if geo.is_land(lat, lon) is not False:
                break
        dest = {"type": "village", "name": "가장 가까운 마을", "lat": lat, "lon": lon, "place": "마을",
                "label": f"{leads_api.compass(bearing)}으로 약 {km:.0f}km 떨어진 마을"}
        return self._start_journey(dest, notes)

    def _start_journey(self, dest, notes):
        self.journey = dest
        return self._advance_journey(notes)

    def _leg_mode(self, remaining):
        """이번 구간에 쓸 수단과 속도, 요금. 지금 있는 곳과 가진 것에 따라 정해진다."""
        if self.vehicle and (self.vehicle["kind"] != "boat"):
            return "drive", self.vehicle["name"], self.vehicle["speed"], 0.0
        if self.place_type == "야생":
            speed = self.hazard["walk_speed"] * (0.65 if self.is_night else 1.0)
            return "walk", "도보", speed, 0.0
        if self.place_type == "도시" and remaining > 150:
            km = min(remaining, TRAVEL_RULES["train"]["speed"] * JOURNEY_MAX_HOURS)
            fare = self.fare("train", km)
            if fare <= self.money:
                return "train", "기차", TRAVEL_RULES["train"]["speed"], fare
        km = min(remaining, TRAVEL_RULES["bus"]["speed"] * JOURNEY_MAX_HOURS)
        fare = self.fare("bus", km)
        if fare <= self.money:
            return "bus", "버스", TRAVEL_RULES["bus"]["speed"], fare
        return "hitchhike", "히치하이킹", 50.0, 0.0

    def _advance_journey(self, notes):
        """여정을 한 턴만큼 진행한다. 목적지에 닿으면 도착 처리를 한다."""
        dest = self.journey
        remaining = geo.haversine_km(self.lat, self.lon, dest["lat"], dest["lon"])
        mode, label, speed, fare = self._leg_mode(remaining)
        if mode == "hitchhike" and random.random() > (0.85 if self.flags.get("on_road") else 0.6) * (0.5 if self.is_night else 1):
            self.pass_time(1.5, "other")
            self.turn_flags["travel"] = 1
            self.turn_flags["time"] = 1
            return {"success": False, "message": " ".join(notes + [
                f"차비가 없어 {dest['label']} 방향으로 차를 얻어 타려 했지만, 1시간 반을 기다려도 태워 주는 차가 없었다. "
                "돈을 벌거나 다시 시도해야 한다."])}
        leg = min(remaining, speed * JOURNEY_MAX_HOURS)
        if mode == "drive":
            leg = min(leg, self.vehicle["range_km"])
        end_lat, end_lon = (dest["lat"], dest["lon"]) if leg >= remaining - 0.5 else \
            geo.move_toward(self.lat, self.lon, dest["lat"], dest["lon"], leg)
        if mode != "walk" and geo.distance_to_korea(end_lat, end_lon) > ARRIVAL_RADIUS_KM \
                and geo.is_land(end_lat, end_lon) is False:
            return {"success": False, "message": " ".join(notes + [
                f"{dest['label']}까지는 바다가 가로막고 있어 육로로는 갈 수 없다. 배나 비행기가 필요하다."])}
        hours = max(0.25, leg / speed)
        if fare:
            self.money = round(self.money - fare, 2)
            self.turn_flags["paid"] = self.turn_flags.get("paid", 0) + fare
        self.pass_time(hours, "walk" if mode == "walk" else "ride", sheltered=mode != "walk")
        if mode == "drive":
            self.vehicle["range_km"] = round(self.vehicle["range_km"] - leg)
            if self.vehicle["range_km"] <= 5:
                notes.append(f"연료가 바닥나 {self.vehicle['name']}을(를) 버려야 했다.")
                self.vehicle = None
        self.turn_flags["travel"] = 1
        self.turn_flags["time"] = 1
        self.turn_flags["moved"] = {"how": label, "km": round(leg), "cost": fare, "ticket": None}
        if self.status != "playing":
            return {"success": False, "message": " ".join(notes + ["가는 도중 쓰러지고 말았다."])}
        arrived_korea = self._relocate(end_lat, end_lon, leg, "walk" if mode == "walk" else "bus")
        if arrived_korea:
            self.journey = None
            return {"success": True, "arrived_in_korea": True, "message": "마침내 한국에 도착했다!"}
        reached = leg >= remaining - 0.5
        if not reached:
            self.place_type = "야생" if mode in ("walk", "drive") else "마을"
            left = geo.haversine_km(self.lat, self.lon, dest["lat"], dest["lon"])
            self.remember(f"{dest['label']}(으)로 가는 중. 남은 거리 약 {left:.0f}km. 이어서 가면 된다.", "always")
            return {"success": True, "도착": False, "수단": label, "걸린_시간": f"{hours:.1f}시간",
                    "message": " ".join(notes + [
                        f"{label}(으)로 {leg:.0f}km를 {hours:.1f}시간 동안 이동했다. {dest['label']}까지 아직 약 "
                        f"{left:.0f}km 남았다. 지금은 {self.place_type}에 있다. 다음 턴에 이어서 갈 수 있다."])}
        return self._arrive_journey(dest, label, hours, notes)

    def _arrive_journey(self, dest, label, hours, notes):
        self.journey = None
        self.place_type = dest["place"]
        if dest["type"] == "village":
            found = leads_api.reveal({"label": "마을로 가는 길", "target": "village"}, self.biome, self.is_night)
            self.set_scene("outdoor", found["scene"], found["description_en"], found["features"])
            story = found["text"]
        else:
            country = self.place_name.split(",")[0] if self.place_name else ""
            self.place_name = f"{country}, {dest['name']}" if country and country != dest["name"] else dest["name"]
            self.set_scene("outdoor", f"{dest['name']} 시내",
                           "A busy street in this city: local shops, traffic and a bus terminal.",
                           ["시내 거리", "버스 터미널", "상점들"])
            story = f"{dest['name']}에 도착했다. 사람과 차가 붐비는 도시다."
        self.remember(f"{dest['label']}에 도착했다.", "always")
        if self.flags.get("embassy_contacted") and self.place_type in ("마을", "도시") \
                and not self.flags.get("embassy_visited"):
            notes.append("영사와 약속한 대로, 여기서 공관까지 가는 교통편을 받을 수 있다(공관으로 간다고 하면 된다).")
        return {"success": True, "도착": True, "수단": label, "걸린_시간": f"{hours:.1f}시간",
                "message": " ".join(notes + [f"{label}(으)로 {hours:.1f}시간 걸려 도착했다. {story}"])}

    def _go_embassy_now(self):
        """마을·도시에서 공관으로: 공관이 교통편을 마련해 이번 턴에 바로 간다."""
        return self._instant_offer("embassy")

    def _go_airport_now(self):
        if "airport" not in self.offer_needs():
            why = ("이미 공항에 있다." if self.flags.get("at_airport") else
                   "아직 공항으로 갈 방법을 찾지 못했다. 공관에서 서류와 지원을 받거나, 며칠 더 버티며 여비를 모아야 한다.")
            return {"success": False, "message": why}
        return self._instant_offer("airport")

    def _instant_offer(self, kind):
        from .events import MAJOR_EVENTS
        template = next(e for e in MAJOR_EVENTS if e["id"] == kind)
        offer = {"id": kind, "text": template["text"], "accept": template["accept"],
                 "hours": template.get("hours", 0), "stats": dict(template.get("stats", {})),
                 "items": list(template.get("items", [])),
                 "money": int(random.randint(*template["money"]) // 10 * 10) if "money" in template else 0,
                 "risk": template["risk"], "bad": dict(template["bad"]), "move": dict(template["move"])}
        offer = self.plan_offer(offer)
        if offer is None:
            return {"success": False,
                    "message": "가까운 곳에 갈 수 있는 " + ("한국 공관이" if kind == "embassy" else "국제공항이") + " 없다."}
        offer["turn"] = self.turn
        self.offer = offer
        self.last_major_turn = self.turn
        self.event = None
        self.journey = None
        result = self.accept_offer()
        result["안내"] = "플레이어가 직접 요청한 일이라 이번 턴에 바로 이동했다. 도착한 곳에서의 상황으로 서술을 마무리하라."
        return result

    def repatriate(self):
        """공관의 귀국 지원: 가족이 보낸 돈(신속해외송금)으로 한국행 항공권을 마련해 준다."""
        if not self.flags.get("at_embassy"):
            return {"success": False,
                    "message": "귀국 지원은 한국 공관 안에서만 받을 수 있다. 먼저 seek_help(kind='embassy') 로 공관에 가야 한다."}
        if self.find_ticket("flight"):
            return {"success": False, "message": "이미 한국행 항공권이 있다. 공항으로 가면 된다."}
        if self.wanted >= WANTED_AIRPORT_LIMIT:
            return {"success": False,
                    "message": "현지 경찰의 수배 기록 때문에 공관도 당장 출국을 도울 수 없다. 수배가 풀릴 때까지 기다려야 한다."}
        fare = self.fare("flight", self.distance)
        self.pass_time(2, "rest", sheltered=True)          # 가족과 통화하고 송금을 받는 시간
        self.tickets.append({"method": "flight", "km": round(self.distance), "item": "한국행 항공권", "price": fare})
        self.items.append("한국행 항공권")
        self.flags["repatriation"] = True
        self.turn_flags["ticket"] = {"item": "한국행 항공권", "price": fare, "sponsored": True}
        self.turn_flags["time"] = 1
        self.remember("공관의 도움으로 가족이 송금한 돈으로 한국행 항공권을 마련했다. 공항으로 가서 타기만 하면 된다.",
                      "always")
        return {"success": True,
                "message": f"영사가 가족과 연락해 신속해외송금으로 한국행 항공권(${fare:,.0f})을 마련해 주었다. "
                           "소지금은 줄지 않았다. 이제 공항으로 가면 된다(seek_help(kind='airport'))."}

    def _finish_offer(self, offer):
        details = []
        dest = offer.get("dest")
        if dest:
            change = round(geo.distance_to_korea(dest["lat"], dest["lon"]) - self.distance)
            way = f"한국까지 {abs(change):,}km {'가까워짐' if change < 0 else '멀어짐'}" if abs(change) >= 10 else "한국과의 거리는 거의 그대로"
            details.append(f"{dest['label']}(약 {dest['km']:,}km)까지 이동, {way}")
        if offer.get("money"):
            details.append(f"${offer['money']} 획득")
        if offer.get("stats"):
            details.append("몸 상태 회복" if sum(offer["stats"].values()) > 0 else "기력 소모")
        if offer.get("items"):
            details.append("물품: " + ", ".join(offer["items"]))
        offer["detail"] = " · ".join(details)
        return offer

    def accept_offer(self):
        """대형 이벤트(기회)를 받아들인다. 좋은 결과일지 나쁜 결과일지는 엔진이 굴려서 정한다."""
        offer = self.offer
        if not offer or self.status != "playing":
            return {"success": False, "message": "지금 받아들일 수 있는 제안이 없다. (이미 지나갔거나 없었다)"}
        self.offer = None
        bad = offer.get("bad") or {}
        is_bad = bool(bad) and random.random() < bad.get("chance", 0)
        plan = bad if is_bad else offer          # 실제로 적용할 효과
        results = []

        hours = plan.get("hours", 0)
        while hours > 0 and self.status == "playing":
            step = min(12, hours)
            self.pass_time(step, "rest", sheltered=True)
            hours -= step
        for key, amount in plan.get("stats", {}).items():
            setattr(self, key, clamp(getattr(self, key) + amount))
        self._check_death("기회라고 믿었던 선택이 마지막이 되었다")

        if is_bad:
            gain = offer.get("money", 0) * bad.get("money_frac", 0) + bad.get("money", 0)
            lost = round(self.money * bad.get("lose_money_frac", 0), 2)
            self.money = round(max(0.0, self.money + gain - lost), 2)
            if lost:
                results.append(f"${lost:.0f}을(를) 잃었다")
            if gain > 0:
                results.append(f"${gain:.0f}만 받았다")
            elif gain < 0:
                results.append(f"${-gain:.0f}을(를) 냈다")
            if bad.get("lose_item"):
                losable = [i for i in self.items if "여권" not in i]
                if losable:
                    stolen = random.choice(losable)
                    self.items.remove(stolen)
                    results.append(f"'{stolen}'도 사라졌다")
        else:
            if offer.get("money"):
                self.money = round(self.money + offer["money"], 2)
                results.append(f"${offer['money']}을(를) 받았다")
            if offer.get("items"):
                self.update_items(add=offer["items"])
                results.append("얻은 물건: " + ", ".join(offer["items"]))

        arrived = False
        dest = offer.get("dest")
        if dest and self.status == "playing":
            route = geo.haversine_km(self.lat, self.lon, dest["lat"], dest["lon"])
            frac = bad.get("ride_frac", 1.0) if is_bad else 1.0
            km = route * frac
            self.pass_time(min(km / offer["move"]["speed"], 12) or 0.25, "ride", sheltered=True)
            if km >= route - 0.5:
                new_lat, new_lon = dest["lat"], dest["lon"]
            else:
                new_lat, new_lon = geo.move_toward(self.lat, self.lon, dest["lat"], dest["lon"], km)
            arrived = self._relocate(new_lat, new_lon, km, "offer")
            if not arrived:
                reached = km >= route - 0.5
                self.place_type = dest["place"] if reached else bad.get("dest", "야생")
                if reached and dest["type"] in ("city_or_village", "rescue", "airport", "embassy", "port_toward_korea") \
                        and dest["name"] != "근처 마을":
                    self.place_name = f"{self.place_name.split(',')[0]}, {dest['name']}" if self.place_name else dest["name"]
                if reached and dest["type"] == "embassy":
                    self.flags["embassy_visited"] = True
                    self.flags["at_embassy"] = True
                    self.set_scene("indoor", "한국 공관 영사과", "Inside a small consular office: a service counter, "
                                   "a Korean flag, waiting chairs and document forms.", ["민원 창구", "태극기", "대기 의자"])
                    self.flags["at_embassy"] = True        # set_scene 이 지운 표시를 다시 남긴다
                    self.remember(f"{dest['label']}에 도착해 영사 지원을 받음. 여행증명서를 발급받을 수 있다.", "always")
                    self.last_major_turn = self.turn - 5          # 다음 기회(공항 등)가 머지않아 온다
                elif reached and dest["type"] == "airport":
                    self.flags["at_airport"] = True
                    self.set_scene("indoor", "국제공항 출국장", "Inside an international airport departure hall: "
                                   "check-in counters, departure boards, large windows to the runway.",
                                   ["항공사 카운터", "출발 안내판", "활주로가 보이는 창"])
                    self.remember(f"{dest['name']} 국제공항에 있다. 항공권만 있으면 한국행 비행기를 탈 수 있다.")
                elif reached:
                    self.remember(f"{offer['accept']} — {dest['label']}에 도착함")
                results.append(f"{km:.0f}km를 이동해 {self.place_name}({self.place_type})에 내렸다. "
                               f"한국까지 {self.distance:.0f}km 남았다")
        self.turn_flags["travel"] = self.turn_flags.get("travel", 0) + 1
        self.time_passed_this_turn = True
        story = bad["text"] if is_bad else "제안은 진짜였고, 약속대로 이루어졌다."
        self.remember(f"기회 '{offer['accept']}'를 받아들임 → {'나쁜' if is_bad else '좋은'} 결과", "always")
        self.turn_flags["offer_result"] = {"bad": is_bad, "title": offer["accept"],
                                           "text": story + " " + " / ".join(results)}
        return {"success": True, "outcome": "나쁜 결과" if is_bad else "좋은 결과",
                "arrived_in_korea": arrived,
                "message": f"{offer['text']} → {story} " + " / ".join(results)}

    def _arrive_at_new_place(self, method):
        """이동 후 새 위치의 날씨·지명·지형·장소 유형을 갱신한다. 초반에는 도시에 닿지 않는다."""
        self._place_new_location(method)
        if self.early and self.place_type == "도시":
            self.place_type = "마을"

    def _place_new_location(self, method):
        village_chance = self.hazard["village"]      # 떠나온 지형 기준
        self.set_weather(get_weather(self.lat, self.lon))
        place = geo.reverse_geocode(self.lat, self.lon)
        self.place_name = place["name"] if place else "이름 모를 땅"
        self.country_code = (place or {}).get("country_code", "") or self.country_code
        self.place_name_en = (place or {}).get("name_en", "")
        self.country_en = (place or {}).get("country_en", "") or self.country_en
        self.refresh_climate()
        self.biome = classify_biome(self.lat, self.weather, self.climate)
        roll = random.random()
        before = self.place_type
        if method == "walk":
            if before == "야생":
                self.place_type = "마을" if roll < village_chance else "야생"
            elif before == "마을":
                self.place_type = "야생" if roll < 0.6 else "마을"
            else:
                self.place_type = "마을" if roll < 0.4 else ("야생" if roll < 0.7 else "도시")
        elif method == "hitchhike":
            self.place_type = "마을" if roll < 0.5 else ("도시" if roll < 0.8 else "야생")
        elif method == "bus":
            self.place_type = "도시" if roll < 0.55 else "마을"
        else:
            self.place_type = "도시"
        if self.place_type != before:
            self.scene_dirty = True

    def _check_death(self, reason):
        if self.health <= 0 and self.status == "playing":
            self.status = "dead"
            self.death_reason = reason

    # ---------- 턴 진행 ----------
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
        if self.place_type in ("마을", "도시") and self.wanted >= 20 and random.random() < self.wanted / 150:
            self.event = {"kind": "danger",
                          "text": "경찰이 수배 전단 속 얼굴과 당신을 번갈아 보더니 다가온다."
                                  + (" 당신이 몰고 온 차량도 신고된 것이다." if self.vehicle and self.vehicle.get("stolen") else "")}
        # 대형 이벤트(기회): 확률로 발생하고, 오래 안 나오면 반드시 나온다
        waited = self.turn - self.last_major_turn
        if self.offer is None and self.turn >= 3 and (
                random.random() < MAJOR_EVENT_CHANCE or waited >= MAJOR_EVENT_PITY_TURNS):
            self.offer = roll_major_event(self.place_type, self.in_extreme_wild, self.indoor,
                                          allowed_needs=self.offer_needs())
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
        if self.offer and self.offer.get("turn", 0) < self.turn:
            self.offer = None            # 제안은 나온 다음 턴까지만 유효하다
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
            "수배도": f"{self.wanted:.0f}/100" + (" - 공항·항구 검문에서 붙잡힐 수 있음" if self.wanted >= WANTED_AIRPORT_LIMIT else ""),
            "초반_제한": (f"앞으로 약 {max(1, round(EARLY_GAME_HOURS - self.elapsed_hours))}시간은 도시·공항·공관으로 갈 수 "
                         "없다(마을까지만)") if self.early else "없음",
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
