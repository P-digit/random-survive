"""자유 행동 판정과 범죄: 성공 확률 판정, 목격자와 수배도, 원한을 가진 사람, 체포."""
import random

from . import geo, leads as leads_api
from .config import (ATTEMPT_CHANCE, ATTEMPT_FAIL_DAMAGE, CRIMES, MONEY_GAIN_LIMIT, WANTED_AIRPORT_LIMIT,
                     WANTED_ON_FAIL, WANTED_ON_SUCCESS, WITNESS)
from .util import clamp


class CrimeMixin:
    """GameState의 자유 행동 판정과 범죄 규칙. GameState가 상속한다(필드는 GameState에 있다)."""

    def mark_victim(self, who, status):
        """범죄의 피해자를 기록한다. 이후 GM은 이 사람을 이 상태 그대로 다뤄야 한다."""
        person = self.find_character(who)
        if person is None:
            person = {"name": str(who).strip()[:20], "role": "피해자", "look": "", "status": ""}
            self.characters.append(person)
            self.characters = self.characters[-6:]
        person["status"] = status
        enemy = next((e for e in self.enemies if e["name"] == person["name"]), None)
        if enemy is None:
            enemy = {"name": person["name"], "role": person["role"]}
            self.enemies.append(enemy)
            self.enemies = self.enemies[-8:]
        enemy.update(status=status, lat=self.lat, lon=self.lon, place=self.place_name)
        return person

    def enemies_nearby(self, km=30):
        return [e for e in self.enemies if geo.haversine_km(self.lat, self.lon, e["lat"], e["lon"]) <= km]

    def notorious_here(self, km=30):
        return next((n for n in self.notorious
                     if geo.haversine_km(self.lat, self.lon, n["lat"], n["lon"]) <= km), None)

    def crime_aftermath(self):
        """범죄가 남긴 여파. 매 턴 GM에게 전달되어 이후 진행에 반영된다."""
        notes = []
        if self.wanted >= 1:
            notes.append(f"수배도 {self.wanted:.0f}/100" + (" — 공항·항구 검문에서 붙잡힐 수 있다"
                                                           if self.wanted >= WANTED_AIRPORT_LIMIT else ""))
        scene = self.crime_scene
        if scene and (scene["lat"], scene["lon"]) == (self.lat, self.lon):
            ago = self.elapsed_hours - scene["hours"]
            notes.append(f"지금 있는 곳은 {ago:.1f}시간 전에 {scene['crime']}을(를) 저지른 현장이다"
                         + (f" (목격: {scene['witnessed']})" if scene["witnessed"] != "none" else " (목격자 없음)"))
        bad = self.notorious_here()
        if bad and self.place_type in ("마을", "도시"):
            notes.append(f"이 지역에서는 당신이 {bad['crime']}을(를) 저지른 범죄자로 알려져 있다. 사람들이 알아보고 "
                         "피하거나 신고한다. 도움을 주지 않는다.")
        if self.vehicle and self.vehicle.get("stolen"):
            notes.append(f"타고 있는 {self.vehicle['name']}은(는) 훔친 것이다. 경찰이 보면 수상히 여긴다.")
        if self.stolen_items:
            notes.append("훔친 물건을 가지고 있다: " + ", ".join(self.stolen_items) + " (체포되면 압수)")
        return notes

    def attempt(self, action, difficulty="normal", crime="none", witnessed="none", violent=False,
                item="", stealth=False, success_money=0, success_items=None, victim=""):
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
                if crime != "none":
                    self.stolen_items = (self.stolen_items + got)[-10:]
                if got:
                    effects.insert(0, "얻은 물건: " + ", ".join(got))
        self.turn_flags["attempt"] = {"action": str(action)[:40], "chance": chance, "success": success,
                                      "illegal": crime != "none", "crime": crime, "effects": effects,
                                      "victim": str(victim or "").strip()}
        if crime != "none":
            self._record_crime(str(action)[:40], crime, success, witnessed, bool(violent), str(victim or "").strip())
        return {"success": success, "chance": f"{chance * 100:.0f}%", "보정": reasons or ["없음"],
                "엔진이_적용한_결과": effects or ["없음"],
                **({"거부된_물건": rejected} if rejected else {}),
                "안내": ("성공했다. 걸어 둔 돈·물건은 엔진이 이미 넣었다(다시 넣지 마라). 탈것을 얻었다면 "
                        "acquire_vehicle 을 호출하라." if success else
                        "실패했다. 목표를 이루지 못했다. 실패를 그대로 서술하고, 상대의 반응(반격, 신고, 도주)을 "
                        "현실적으로 그려라. 이미 엔진이 적용한 피해를 다시 적용하지 마라.")}

    def _record_crime(self, action, crime, success, witnessed, violent, victim):
        """범죄의 결과를 세계에 남긴다: 피해자의 상태, 게임 내내 유효한 사실, 끝나 버린 제안, 범죄 현장."""
        if victim:
            what = leads_api.eul(crime)              # '차량 절도를', '폭행을'
            if success and violent:
                status = (f"당신에게 {what} 당해 쓰러져 있다(기절·부상). 깨어나면 당신을 적대하고 신고한다. "
                          "당신을 돕지 않고 태워 주지도 않는다.")
            elif success and witnessed == "none":
                status = f"아직 {what} 당한 줄 모른다. 알게 되면 신고할 것이다."
            elif success:
                status = f"당신에게 {what} 당한 것을 안다. 적대적이며 신고하려 한다. 당신을 돕지 않는다."
            else:
                status = (f"당신의 {crime} 시도를 알아챘다. 적대적이고 경계한다. 소리쳐 사람을 부르거나 신고한다. "
                          "당신을 돕지 않는다.")
            self.mark_victim(victim, status)
        result = "성공" if success else "실패"
        self.remember(f"{action} — {result} ({crime}" + (f", 피해자: {victim}" if victim else "")
                      + f", 목격: {witnessed})", "always")
        if self.offer:                       # 그 사람의 제안(태워 주기 등)은 끝났다
            offer_words = [w for w in (self.offer.get("accept", "") + " " + self.offer.get("text", "")).split()
                           if len(w) >= 2]
            target = (action + " " + victim).replace(" ", "")
            if any(w.rstrip("에을를이가은는의로") in target for w in offer_words):
                self.remember(f"범죄 때문에 '{self.offer['accept']}' 제안은 사라졌다.")
                self.offer = None
        self.crime_scene = {"lat": self.lat, "lon": self.lon, "turn": self.turn, "hours": self.elapsed_hours,
                            "crime": crime, "victim": victim, "witnessed": witnessed,
                            "knocked_out": bool(success and violent)}
        if witnessed != "none" and self.place_type in ("마을", "도시"):
            if not self.notorious_here(5):
                self.notorious.append({"place": self.place_name, "lat": self.lat, "lon": self.lon,
                                       "crime": crime, "turn": self.turn})
                self.notorious = self.notorious[-6:]

    def _arrest(self, where):
        """붙잡혔다: 하루를 잃고, 벌금을 내고, 탈것과 표를 압수당한다."""
        fine = round(self.money * 0.5, 2)
        self.money = round(self.money - fine, 2)
        lost = []
        if self.vehicle:
            lost.append(self.vehicle["name"])
            self.vehicle = None
        for item in list(self.stolen_items):
            if item in self.items:
                self.items.remove(item)
                lost.append(item)
        self.stolen_items = []
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
