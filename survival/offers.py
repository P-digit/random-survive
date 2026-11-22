"""대형 이벤트(기회): 등장 조건, 받아들이기·거절·만료, 같은 기회의 반복 방지."""
import random
import re

from . import geo, leads as leads_api, places
from .config import AIRPORT_OPEN_DAY, EARLY_MAX_TRAVEL_KM
from .events import OFFER_DONE, OFFER_EXIT, PERSISTENT_OFFERS
from .util import clamp


class OfferMixin:
    """GameState의 대형 이벤트(기회) 규칙. GameState가 상속한다(필드는 GameState에 있다)."""

    def expire_offer(self):
        """기회가 지나갔다: 제안한 사람·탈것은 떠나고, 장면에서도 사라진다."""
        offer, self.offer = self.offer, None
        if not offer:
            return
        exit_text, ko_words, en_words = OFFER_EXIT.get(offer.get("id"), ("기회는 지나갔다.", (), ()))
        self.expired_offers = (self.expired_offers + [{"id": offer.get("id"), "accept": offer.get("accept", ""),
                                                      "exit": exit_text, "turn": self.turn}])[-5:]
        self.remember(exit_text)
        self.turn_flags["offer_expired"] = {"accept": offer.get("accept", ""), "exit": exit_text}
        # 장면에서 지운다: 보이는 것, 그림에서 읽은 것, 등장인물, 그림 묘사의 해당 문장
        gone = lambda s: any(w in s for w in ko_words)               # noqa: E731
        had = any(gone(s) for s in self.scene_features + self.scene_seen)
        self.scene_features = [s for s in self.scene_features if not gone(s)]
        self.scene_seen = [s for s in self.scene_seen if not gone(s)]
        if en_words:
            self.scene_seen_en = [s for s in self.scene_seen_en if not any(w in s.lower() for w in en_words)]
        elif had:
            self.scene_seen_en = []    # 영어로 가릴 수 없으면 GM의 묘사로 돌아간다
        self.characters = [c for c in self.characters if not (gone(c["role"]) or gone(c["name"]))]
        if en_words and any(w in self.scene_desc.lower() for w in en_words):
            sentences = re.split(r"(?<=[.!?])\s+", self.scene_desc)
            self.scene_desc = " ".join(s for s in sentences if not any(w in s.lower() for w in en_words))
            had = True
        if had:
            self.scene_dirty = True      # 그림에 남아 있던 트럭 등을 지우려면 다시 그린다

    def recently_expired(self, offer_id, turns=6):
        return any(e["id"] == offer_id and self.turn - e["turn"] <= turns for e in self.expired_offers)

    def offer_closed(self, offer_id, turns=8, km=20):
        """같은 기회를 이미 받아들였거나 거절했다: 그곳에서는 다시 나오지 않고, 다른 곳에서도 한동안 나오지 않는다."""
        return any(d["id"] == offer_id and (self.turn - d["turn"] <= turns
                                            or geo.haversine_km(self.lat, self.lon, d["lat"], d["lon"]) < km)
                   for d in self.done_offers)

    def closed_offers_here(self, turns=6, km=5):
        """지금 이 자리에서(또는 방금) 끝난 기회들. GM에게 '다시 할 수 없다'고 알린다."""
        return [d for d in self.done_offers
                if self.turn - d["turn"] <= turns or geo.haversine_km(self.lat, self.lon, d["lat"], d["lon"]) < km]

    def _close_offer(self, offer, how):
        accepted_note, declined_note = OFFER_DONE.get(offer.get("id"), (
            f"'{offer.get('accept', '')}' 제안은 이미 받아들여 끝났다.", f"'{offer.get('accept', '')}' 제안은 거절했다."))
        note = accepted_note if how == "accepted" else declined_note
        self.done_offers = (self.done_offers + [{"id": offer.get("id"), "accept": offer.get("accept", ""), "how": how,
                                                 "turn": self.turn, "lat": self.lat, "lon": self.lon,
                                                 "note": note, "items": list(offer.get("items") or [])}])[-10:]
        self.remember(note)
        return note

    def decline_offer(self):
        """플레이어가 기회를 거절했다. 다시 받아들일 수 없다."""
        offer = self.offer
        if not offer:
            return {"ok": False, "message": "지금 거절할 제안이 없다."}
        note = self._close_offer(offer, "declined")
        if offer.get("id") in PERSISTENT_OFFERS:
            self.offer = None                    # 상자는 그 자리에 그대로 있지만, 열지 않기로 했다
        else:
            self.expire_offer()                  # 제안한 사람·탈것은 떠난다
            self.turn_flags.pop("offer_expired", None)
        self.turn_flags["offer_declined"] = {"accept": offer.get("accept", ""), "text": note}
        return {"ok": True, "message": note + " 이 기회는 다시 받아들일 수 없다."}

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
                (self.flags.get("embassy_visited") or self.day >= AIRPORT_OPEN_DAY):
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
            done = self.closed_offers_here()
            if done:
                d = done[-1]
                return {"success": False,
                        "message": f"{d['note']} 같은 기회('{d['accept']}')는 다시 할 수 없다. 다시 한 것처럼 서술하거나 "
                                   "물건·수치를 다시 주지 마라."}
            last = self.expired_offers[-1] if self.expired_offers else None
            if last and self.turn - last["turn"] <= 3:
                return {"success": False,
                        "message": f"그 기회('{last['accept']}')는 이미 지나갔다. {last['exit']} "
                                   "타거나 받아들였다고 서술하지 마라. 이미 떠나고 없다."}
            return {"success": False, "message": "지금 받아들일 수 있는 제안이 없다."}
        self.offer = None
        self._close_offer(offer, "accepted")
        if offer.get("id") == "supply":          # 장면 속 상자는 이제 열린 빈 상자다
            self.scene_features = [f for f in self.scene_features if "상자" not in f] + ["열린 빈 보급 상자"]
            self.scene_seen = [f for f in self.scene_seen if "상자" not in f]
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
