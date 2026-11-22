"""의뢰(사이드 미션): 마을·도시에서 의뢰인이 일을 맡긴다. 실제 도시까지 짐을 옮기면 엔진이 보수를 준다.

- 배달(합법): 소포를 목적지 도시까지. 보수 보통.
- 밀수(불법): 밀수품 꾸러미를 다른 나라의 도시까지. 보수가 크지만, 나라를 넘을 때 세관·국경 경비대에 걸릴 수 있고
  체포되면 압수당한다(훔친 물건처럼 다룬다).

기회·경찰과 같은 방식이다. 의뢰는 엔진이 정해 등장시키고(GM은 의뢰인이 제안하는 장면을 서술), 플레이어의 다음
입력으로 수락 여부를 판정한다. 완료(목적지 30km 안 도착)와 실패(기한 초과, 짐을 잃음)도 엔진이 판정한다.
"""
import random
import re

from . import geo, places

MISSION_CHANCE = {"도시": 0.15, "마을": 0.10}   # 한 턴에 의뢰인이 나타날 확률
SMUGGLE_SHARE = 0.35                          # 의뢰 중 밀수의 비율 (수배 중이면 0.6 — 뒷골목 사람들이 먼저 접근한다)
DELIVERY_RANGE = (80, 900)                    # 목적지까지 거리(km)
ARRIVE_KM = 30                                # 목적지 도시의 이 거리 안에 들면 완료
CUSTOMS_CHANCE = 0.35                         # 밀수품을 가지고 대중교통으로 나라를 넘을 때 세관에 걸릴 확률
GIVERS = {"deliver": ("잡화점 주인", "화물 중개인", "우체국 직원", "식당 주인", "선교사"),
          "smuggle": ("수상한 남자", "뒷골목 중개인", "밀수꾼", "선원 출신 사내")}
PACKAGE = {"deliver": "의뢰받은 소포", "smuggle": "밀수품 꾸러미"}
ACCEPT_WORDS = re.compile(r"의뢰를?\s*(받|맡|수락)|맡겠|맡을게|맡는다|맡아|수락|받아들|하겠다|할게|좋아|좋다|"
                          r"그러죠|그러겠|배달하겠|운반하겠|가져다주겠|가져다 주겠|가져가겠")
DECLINE_WORDS = re.compile(r"거절|사양|싫|안 해|안해|안 하|하지 않|못 하|못하|됐어|관심 없")


def reward_for(kind, km):
    return round((40 + 0.15 * km) if kind == "deliver" else (150 + 0.4 * km))


def deadline_hours(kind, km):
    return round(km / (40 if kind == "deliver" else 50) + 24)


def pick_destination(lat, lon, need_other_country="", rng=random):
    """목적지 도시: 거리 범위 안에서, 가능하면 한국에 더 가까워지는 곳 중 하나."""
    here_to_korea = geo.distance_to_korea(lat, lon)
    options = []
    for city in places.CITY_LIST:
        km = geo.haversine_km(lat, lon, city["lat"], city["lon"])
        if not DELIVERY_RANGE[0] <= km <= DELIVERY_RANGE[1]:
            continue
        if need_other_country and city["country"] == need_other_country:
            continue
        gain = here_to_korea - geo.distance_to_korea(city["lat"], city["lon"])
        options.append((gain, km, city))
    if not options:
        return None, 0
    options.sort(key=lambda o: -o[0])
    toward = [o for o in options if o[0] > 0][:5] or options[:5]
    _, km, city = rng.choice(toward)
    return city, round(km)


def accepts_mission(text):
    text = text or ""
    return bool(ACCEPT_WORDS.search(text)) and not DECLINE_WORDS.search(text)


class MissionMixin:
    """GameState의 의뢰 규칙. GameState가 상속한다(필드는 GameState에 있다)."""

    def roll_mission(self):
        """턴 시작에 의뢰인이 나타나는지 굴린다 (마을·도시, 진행 중인 의뢰나 제안이 없을 때)."""
        if self.mission or self.mission_offer or self.status != "playing" or self.pursuit:
            return None
        if random.random() >= MISSION_CHANCE.get(self.place_type, 0):
            return None
        kind = "smuggle" if random.random() < (0.6 if self.wanted >= 20 else SMUGGLE_SHARE) else "deliver"
        here = places.nearest_city(self.lat, self.lon)
        home_country = (here or {}).get("country", "") if kind == "smuggle" else ""
        city, km = pick_destination(self.lat, self.lon, need_other_country=home_country)
        if not city:
            return None
        self.mission_offer = {
            "kind": kind, "giver": random.choice(GIVERS[kind]), "item": PACKAGE[kind],
            "target": city["name"], "lat": city["lat"], "lon": city["lon"], "country": city["country"],
            "km": km, "direction": None, "reward": reward_for(kind, km), "hours": deadline_hours(kind, km),
            "turn": self.turn,
        }
        from .leads import compass
        self.mission_offer["direction"] = compass(geo.bearing_deg(self.lat, self.lon, city["lat"], city["lon"]))
        self.turn_flags["mission"] = {"phase": "offered", **self.mission_offer}
        return self.mission_offer

    def resolve_mission_offer(self, player_text):
        """지난 턴에 나온 의뢰에 대한 플레이어의 대답을 판정한다. 받으면 짐을 받고 의뢰가 시작된다."""
        offer = self.mission_offer
        if not offer or offer["turn"] >= self.turn:
            return None
        self.mission_offer = None
        if not accepts_mission(player_text):
            self.turn_flags["mission"] = {"phase": "passed", **offer}
            return {"accepted": False}
        self.mission = {**offer, "deadline": self.elapsed_hours + offer["hours"], "accepted_turn": self.turn}
        self.items.append(offer["item"])
        if offer["kind"] == "smuggle":
            self.stolen_items.append(offer["item"])   # 체포되면 압수된다
        self.turn_flags["mission"] = {"phase": "accepted", **self.mission}
        return {"accepted": True, "mission": self.mission}

    @property
    def carrying_contraband(self):
        return bool(self.mission and self.mission["kind"] == "smuggle" and self.mission["item"] in self.items)

    def check_mission(self):
        """턴 끝에 의뢰의 완료·실패를 판정한다."""
        m = self.mission
        if not m or self.status != "playing":
            return None
        if m["item"] not in self.items:                          # 짐을 잃었다 (압수·판매·분실)
            self.mission = None
            self.turn_flags["mission"] = {"phase": "failed", "why": f"{m['item']}을(를) 잃었다", **m}
            return "failed"
        if geo.haversine_km(self.lat, self.lon, m["lat"], m["lon"]) <= ARRIVE_KM:
            self.items.remove(m["item"])
            if m["item"] in self.stolen_items:
                self.stolen_items.remove(m["item"])
            self.money = round(self.money + m["reward"], 2)
            self.turn_flags["earned"] = self.turn_flags.get("earned", 0) + m["reward"]
            self.turn_flags.setdefault("money_log", []).append({"amount": m["reward"], "why": "의뢰 보수", "shown": True})
            self.mission = None
            self.turn_flags["mission"] = {"phase": "done", **m}
            self.remember(f"{m['giver']}의 의뢰({m['item']})를 {m['target']}에서 마치고 보수 ${m['reward']:,}을(를) 받았다",
                          "always")
            return "done"
        if self.elapsed_hours > m["deadline"]:
            self.items.remove(m["item"])
            if m["item"] in self.stolen_items:
                self.stolen_items.remove(m["item"])
            self.mission = None
            self.turn_flags["mission"] = {"phase": "failed", "why": "기한이 지났다(의뢰인이 짐을 회수해 갔다)", **m}
            return "failed"
        return None

    def customs_check(self, country_before):
        """밀수품을 가지고 나라를 넘었다: 세관·국경에서 걸릴 수 있다(경찰과 같은 방식으로 다음 턴에 판정)."""
        if not self.carrying_contraband or self.pursuit or not country_before or not self.country_code \
                or country_before == self.country_code or random.random() >= CUSTOMS_CHANCE:
            return None
        stage = max(self.heat, 3)
        self.pursuit = {"stage": stage, "turn": self.turn, "who": "짐을 뒤지려는 세관원과 국경 경찰", "kind": "check",
                        "stolen_vehicle": False}
        self.turn_flags["police"] = {"phase": "spotted", "who": self.pursuit["who"], "kind": "check", "stage": stage}
        return self.pursuit

    def mission_status(self):
        """GM 입력용 의뢰 요약."""
        m = self.mission
        if not m:
            return None
        left = m["deadline"] - self.elapsed_hours
        km = geo.haversine_km(self.lat, self.lon, m["lat"], m["lon"])
        return (f"{m['giver']}의 의뢰({'밀수 — 불법' if m['kind'] == 'smuggle' else '배달'}): {m['item']}을(를) "
                f"{m['target']}까지 (지금부터 약 {km:,.0f}km), 보수 ${m['reward']:,}, 남은 시간 {left:.0f}시간. "
                "도착하면 엔진이 보수를 준다(GM이 주지 않는다).")
