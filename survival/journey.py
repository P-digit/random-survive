"""목적지로 가기: 마을·도시·공관·공항으로 여러 턴에 걸쳐 가는 여정과 공관의 도움."""
import random

from . import geo, leads as leads_api, places
from .config import ARRIVAL_RADIUS_KM, JOURNEY_MAX_HOURS, TRAVEL_RULES, VILLAGE_DISTANCE, WANTED_AIRPORT_LIMIT


class JourneyMixin:
    """GameState의 목적지로 가기 규칙. GameState가 상속한다(필드는 GameState에 있다)."""

    def seek_help(self, kind, go_now=True):
        """귀국을 위한 도움. 공관·공항으로 가는 것은 go_to 와 같다(지금 상황에서 갈 수 있는 만큼 간다)."""
        if kind == "repatriation":
            return self.repatriate()
        if kind in ("embassy", "airport"):
            return self.go_to(kind)
        return {"success": False, "message": "kind 는 embassy, airport, repatriation 중 하나다."}

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
        if target == "mission":
            m = self.mission
            if not m:
                return {"success": False, "message": "맡은 의뢰가 없다."}
            if self.early:
                return {"success": False, "message": self.early_message()}
            dest = {"type": "city", "name": m["target"], "label": f"의뢰 목적지 {m['target']}", "lat": m["lat"],
                    "lon": m["lon"], "place": "도시"}
            return self._start_journey(dest, notes)
        return {"success": False, "message": "target 은 village, city, embassy, airport, mission, continue 중 하나다."}

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
