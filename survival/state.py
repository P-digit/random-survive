"""게임 상태와 규칙(엔진). 숫자 계산은 전부 여기서 하고, LLM은 서술만 담당한다."""
import random
import re
from dataclasses import dataclass, field

from . import climate as climate_api
from . import geo
from .config import (ARRIVAL_RADIUS_KM, LAND_METHODS, MAJOR_EVENT_CHANCE,
                     MAJOR_EVENT_PITY_TURNS, START_ITEMS, START_MONEY, TRAVEL_RULES,
                     VITALS_DRAIN)
from .events import (BIOME_HAZARDS, BIOMES, classify_biome, roll_event,
                     roll_major_event)
from .risk_model import predict_risk
from .weather import get_weather


def clamp(value, low=0.0, high=100.0):
    return max(low, min(high, value))


# 소지품이 될 수 없는 것들 (LLM이 넣으려 해도 엔진이 거부한다)
NOT_CARRYABLE = ("오두막", "건물", "동굴", "쉘터", "움막", "대피소", "오아시스", "개울", "호수",
                 "우물", "물줄기", "웅덩이", "모닥불", "마을", "도시", "자동차", "트럭", "헬기",
                 "나룻배", "화물선", "야자수", "과일나무", "발자국", "임도", "도로", "신호")
IMPOSSIBLE = ("텔레포트", "순간이동", "마법", "타임머신", "워프", "포탈", "요술", "초능력",
              "제트팩", "광선", "무한", "소원", "투명", "부활", "치트")


TICKET_WORDS = ("티켓", "항공권", "탑승권", "승차권", "승선권", "버스표", "기차표", "열차표", "배표", "비행기표")


def item_problem(name):
    """소지품으로 넣을 수 없는 이름이면 그 이유를, 문제없으면 None을 반환한다."""
    if any(word in name for word in TICKET_WORDS):
        return "교통편 표는 buy_ticket 으로만 구매할 수 있음"
    if any(word in name for word in IMPOSSIBLE):
        return "현실에 존재하지 않는 물건"
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
    start_hour: int = 12              # 시작 시각(현지 시간)
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
    _snapshot: dict = field(default_factory=dict)

    # ---------- 시간 ----------
    @property
    def hour(self):
        return int(self.start_hour + self.elapsed_hours) % 24

    @property
    def day(self):
        return int(self.start_hour + self.elapsed_hours) // 24 + 1

    @property
    def is_night(self):
        return self.hour < 6 or self.hour >= 20

    @property
    def biome_name(self):
        return BIOMES[self.biome][0]

    @property
    def hazard(self):
        return BIOME_HAZARDS[self.biome]

    @property
    def indoor(self):
        return self.scene_setting == "indoor"

    def set_scene(self, setting, place, description_en, features=None):
        """장면을 바꾼다. 실내외가 바뀌거나 다른 곳으로 옮겼으면 이미지를 새로 그리게 한다."""
        setting = setting if setting in ("outdoor", "indoor") else "outdoor"
        place = str(place or "").strip()[:30]
        changed = setting != self.scene_setting or place != self.scene_place
        self.scene_setting, self.scene_place = setting, place
        self.scene_desc = str(description_en or "").strip()[:400]
        self.scene_features = [str(f).strip()[:30] for f in (features or []) if str(f).strip()][:6]
        if changed:
            self.scene_dirty = True
            self.scene_seen = []       # 새 그림이 그려지면 다시 읽어 들인다
        return changed

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
        """새 위치의 날씨를 적용한다. 시간별 예보는 따로 보관한다."""
        weather = dict(weather)
        self.forecast = weather.pop("hourly", [])
        self.weather = weather
        self.sync_weather()   # 예보의 0번은 '게임 시작 시각'이므로, 지금까지 흐른 시간만큼 건너뛴다

    def sync_weather(self):
        """게임 속 시간이 흐른 만큼 예보에서 그 시각의 날씨를 꺼내 적용한다. (밤에는 추워진다)"""
        if self.forecast:
            index = min(int(self.elapsed_hours - self.weather_origin), len(self.forecast) - 1)
            self.weather.update(self.forecast[max(0, index)])

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
            self._check_death("탈수·굶주림·혹독한 환경을 버티지 못했다")
        self.sync_weather()
        self.time_passed_this_turn = True

    def apply_delta(self, health=0, satiety=0, hydration=0, energy=0, money=0, reason=""):
        """행동/이벤트의 결과를 반영한다. LLM이 과하게 바꾸지 못하도록 범위를 제한한다."""
        self.health = clamp(self.health + clamp(health, -40, 30))
        self.satiety = clamp(self.satiety + clamp(satiety, -40, 60))
        self.hydration = clamp(self.hydration + clamp(hydration, -40, 60))
        self.energy = clamp(self.energy + clamp(energy, -40, 40))
        self.money = round(max(0.0, self.money + clamp(money, -100000, 120)), 2)
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
        if method not in TRAVEL_RULES:
            return {"success": False, "message": f"알 수 없는 이동 수단: {method}"}
        rule = TRAVEL_RULES[method]
        ticket = self.find_ticket(method)
        if self.place_type not in rule["places"]:
            return {"success": False,
                    "message": f"{rule['label']}은(는) {'/'.join(rule['places'])}에서만 이용할 수 있다. "
                               f"현재 위치는 {self.place_type}."
                               + (f" ({ticket['item']}은(는) 그대로 가지고 있다.)" if ticket else "")}
        km = clamp(float(km), 1, min(rule["max_km"], self.distance))
        if ticket:
            km = min(float(ticket["km"]), self.distance)   # 예약해 둔 구간만큼 간다
        if method == "flight":
            km = self.distance            # 비행기는 언제나 한국까지 직항이다 (중간 기착 없음)
        cost = 0.0 if ticket else self.fare(method, km)   # 이미 결제한 표가 있으면 요금을 다시 받지 않는다
        if cost > self.money:
            return {"success": False,
                    "message": f"돈이 부족하다. {rule['label']} {km:.0f}km 요금 ${cost:.0f}, 보유 ${self.money:.0f}."}
        hitch_chance = self.hazard["hitch"] if self.place_type == "야생" else 0.6
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
        self.scene_setting, self.scene_place, self.scene_desc = "outdoor", "", ""   # 새 장소의 야외에서 시작
        self.scene_features, self.scene_seen = [], []
        self.scene_dirty = True
        if self.distance <= ARRIVAL_RADIUS_KM:
            self.distance = 0.0
            self.place_name, self.place_type = "대한민국, 서울", "도시"
            self.scene_dirty = True
            if self.status == "playing":
                self.status = "won"
            return True
        self._arrive_at_new_place(method)
        return False

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
        km = float(offer.get("ride_km", 0)) * (bad.get("ride_frac", 0) if is_bad else 1)
        if km > 0 and self.status == "playing":
            km = min(km, self.distance)
            self.pass_time(km / offer["speed"], "ride", sheltered=True)
            new_lat, new_lon = geo.move_toward_korea(self.lat, self.lon, km)
            arrived = self._relocate(new_lat, new_lon, km, "offer")
            if not arrived:
                self.place_type = plan.get("dest", offer.get("dest", self.place_type))
                results.append(f"{km:.0f}km를 이동해 {self.place_name}({self.place_type})에 내렸다. "
                               f"한국까지 {self.distance:.0f}km 남았다")
        self.turn_flags["travel"] = self.turn_flags.get("travel", 0) + 1
        self.time_passed_this_turn = True
        story = bad["text"] if is_bad else "제안은 진짜였고, 약속대로 이루어졌다."
        self.turn_flags["offer_result"] = {"bad": is_bad, "title": offer["accept"],
                                           "text": story + " " + " / ".join(results)}
        return {"success": True, "outcome": "나쁜 결과" if is_bad else "좋은 결과",
                "arrived_in_korea": arrived,
                "message": f"{offer['text']} → {story} " + " / ".join(results)}

    def _arrive_at_new_place(self, method):
        """이동 후 새 위치의 날씨·지명·지형·장소 유형을 갱신한다."""
        village_chance = self.hazard["village"]      # 떠나온 지형 기준
        self.set_weather(get_weather(self.lat, self.lon))
        place = geo.reverse_geocode(self.lat, self.lon)
        self.place_name = place["name"] if place else "이름 모를 땅"
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
                "energy": self.energy, "money": self.money, "distance": self.distance,
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
        self.event = roll_event(self.biome, self.place_type, level)
        if self.indoor and self.place_type == "야생":
            self.event = None            # 동굴·오두막 안에서는 야외 이벤트(눈보라, 짐승 등)가 직접 닥치지 않는다
        # 대형 이벤트(기회): 확률로 발생하고, 오래 안 나오면 반드시 나온다
        waited = self.turn - self.last_major_turn
        if self.offer is None and self.turn >= 3 and (
                random.random() < MAJOR_EVENT_CHANCE or waited >= MAJOR_EVENT_PITY_TURNS):
            self.offer = roll_major_event(self.place_type, self.in_extreme_wild, self.indoor)
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
        if self._snapshot.get("night") is not None and self._snapshot["night"] != self.is_night:
            self.scene_dirty = True      # 낮↔밤이 바뀌면 장면을 다시 그린다

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
        start_distance=distance, distance=distance,
    )
    state.set_weather(weather)
    state.refresh_climate()
    state.biome = classify_biome(lat, state.weather, state.climate)
    state.refresh_risk()
    return state
