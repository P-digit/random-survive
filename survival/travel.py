"""이동 수단으로 가기: 도보·히치하이킹·버스·기차·배·비행기, 표 예매, 탈것, 새 장소에 도착."""
import random

from . import geo, leads as leads_api, places
from .config import (ARRIVAL_RADIUS_KM, EARLY_MAX_TRAVEL_KM, LAND_METHODS, TRAVEL_RULES, VEHICLES,
                     WANTED_AIRPORT_LIMIT)
from .events import PERSISTENT_OFFERS, classify_biome
from .util import clamp
from .weather import get_weather


def arrival_place(method, city):
    """이동한 뒤 도착한 곳의 장소 유형. 주사위가 아니라 규칙으로 정한다.

    - 걷기·운전(내 탈것): 길 위의 어딘가 → 야생. 단, 실제 도시(15km 이내) 근처면 도시.
    - 버스·히치하이킹: 버스는 정류장에, 차를 얻어 타면 기사가 사람 사는 곳에 내려 준다 → 마을.
      실제 도시(30km 이내) 근처면 도시.
    - 기차·배·비행기: 역·항구·공항은 도시에 있다 → 도시.
    사람 사는 곳에 '우연히' 도착하는 일은 없다. 마을은 go_to·단서로 찾아가야 한다.
    """
    near = city["km"] if city else 10 ** 9
    if method in ("train", "ship", "flight"):
        return "도시"
    if method in ("bus", "hitchhike", "offer"):
        return "도시" if near <= 30 else "마을"
    return "도시" if near <= 15 else "야생"


class TravelMixin:
    """GameState의 이동 수단으로 가기 규칙. GameState가 상속한다(필드는 GameState에 있다)."""

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
        if attempt["illegal"] and attempt.get("victim"):
            person = self.find_character(attempt["victim"])
            if person and "빼앗" not in person.get("status", ""):
                person["status"] = f"당신에게 {leads_api.eul(label)} 빼앗겼다. " + person.get("status", "")
        self.turn_flags["vehicle"] = dict(self.vehicle)
        return {"success": True,
                "message": f"{label}을(를) 손에 넣었다. 연료로 약 {fuel}km를 갈 수 있다. "
                           "플레이어가 운전해서 가겠다고 하면 다음 턴부터 travel(method='drive') 로 이동한다."}

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
        arrived = self._relocate(new_lat, new_lon, km, "drive")
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
        if method == "walk" and float(km) < 5:
            return {"success": False,
                    "message": "5km도 안 되는 짧은 이동은 장거리 이동(travel)이 아니다. 같은 지역 안에서 자리를 옮긴 "
                               "것이므로 advance_time 과 set_scene 으로 처리하라. 장소유형은 그대로다."}
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
                "도착한_장소유형": self.place_type,
                "message": f"{rule['label']}(으)로 {km:.0f}km 이동했다. 요금 ${cost:.0f}. "
                           f"도착한 곳: {self.place_name} ({self.place_type}, {self.biome_name}). "
                           f"한국까지 {self.distance:.0f}km 남았다. 서술은 이 장소유형({self.place_type})에서 끝나야 한다."
                           + (" 사람 사는 곳이 아니다. 마을을 만난 것처럼 쓰지 마라." if self.place_type == "야생" else "")}

    def _relocate(self, new_lat, new_lon, km, method):
        """좌표를 옮기고 새 장소 정보를 갱신한다. 한국에 도착했으면 True."""
        self.lat, self.lon = new_lat, new_lon
        self.distance = geo.distance_to_korea(new_lat, new_lon)
        self.moved_since_image += km
        if km >= 300:
            self.wanted = clamp(self.wanted - 15)     # 멀리 떠나면 쫓는 사람이 줄어든다
        self.turn_flags["scene_changed"] = True
        self.scene_setting, self.scene_place, self.scene_desc = "outdoor", "", ""   # 새 장소의 야외에서 시작
        self.scene_features, self.scene_seen, self.scene_seen_en = [], [], []
        if km >= 3:
            self.crime_scene = None          # 범죄 현장을 떠났다
            if self.offer and self.offer.get("id") in PERSISTENT_OFFERS:
                self.offer = None            # 두고 온 보급 상자는 그 자리에 남는다
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
        before = self.place_type
        self.place_type = arrival_place(method, places.nearest_city(self.lat, self.lon))
        if self.place_type != before:
            self.scene_dirty = True
