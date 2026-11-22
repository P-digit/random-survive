"""경제: 일자리와 기술, 물건 팔기(시세), 방 빌리기(숙소·은신처), 도박.

돈의 액수는 엔진이 정한다. GM은 무엇을 하는지만 정하고(일의 종류, 몇 시간, 무엇을 팔지, 판돈), 시급·시세·결과는
여기서 계산한다. 일해서 번 돈과 판 돈은 이 툴들로만 들어온다(tools.gain_problem).
"""
import random

from .config import CRITICAL_CHANCE

# 일자리: (이름, 마을 시급, 도시 시급, 시간당 기력 소모 활동, 설명)
JOBS = {
    "labor": ("막노동", 2.0, 4.0, "work", "짐 나르기, 공사장, 농사일, 하역"),
    "service": ("서비스", 2.5, 5.0, "work", "식당, 가게, 청소, 숙소 일"),
    "skilled": ("기술직", 4.0, 8.0, "work", "수리, 운전, 통역, 장부 정리 — 기술 레벨이 오를수록 유리"),
    "street": ("길거리 일", 1.5, 3.5, "work", "노래·공연, 구두닦이, 짐꾼, 길 안내"),
}
SKILL_HOURS = 8                 # 이만큼 일하면 그 일의 기술이 한 단계 오른다
SKILL_MAX = 5
SKILL_BONUS = 0.15              # 기술 한 단계마다 시급 +15%
NIGHT_HOURS = range(0, 6)       # 이 시간에 시작하면 일자리가 거의 없다(길거리 일만 가능)
MAX_WORK_HOURS = 10

# 물건 시세(USD): 이름에 이 말이 들어 있으면 이 값. 위에서부터 먼저 맞는 것
ITEM_VALUES = (
    (("스마트폰", "휴대폰", "핸드폰"), 60), (("노트북", "카메라"), 120), (("시계", "금목걸이", "반지", "보석"), 50),
    (("자전거",), 40), (("다용도 칼", "칼", "나이프"), 6), (("라이터",), 1), (("텐트", "침낭"), 25),
    (("손전등", "랜턴"), 5), (("배낭", "가방"), 8), (("옷", "외투", "재킷", "신발", "부츠", "모자"), 6),
    (("연료", "기름", "휘발유"), 10), (("약", "구급", "붕대"), 5), (("통조림", "비상식량", "빵", "에너지바"), 2),
    (("물", "생수"), 1), (("지도", "나침반"), 4), (("가죽", "모피"), 15), (("고기", "생선"), 4),
)
DEFAULT_VALUE = 3
UNSELLABLE = ("여권", "티켓", "항공권", "승차권", "버스표", "기차표", "배표")
CITY_PRICE, VILLAGE_PRICE = 0.8, 0.6      # 시세에 대한 실제 판매가 비율 (중고)
FENCE_RATE = 0.5                          # 훔친 물건(장물)은 반값

ROOM_PRICE = {"마을": 8, "도시": 20}       # 1박 요금(USD)
SAFEHOUSE_LAY_LOW = 6                     # 숙소에서 숨어 지내면 수배도 감소 배수 (기본 4배 대신)
SAFEHOUSE_POLICE = 0.3                    # 숙소 안에 있으면 경찰이 찾아올 확률 배수

GAMBLE_WIN_CHANCE = 0.45                  # 이기면 판돈만큼 번다
JACKPOT_CHANCE = 0.03                     # 영화적 연출이면 드물게 판돈의 5배 (realistic이면 없음)
GAMBLE_MAX_STAKE = 200


def item_value(name):
    """물건의 시세(USD). 팔 수 없는 것은 None."""
    if any(word in name for word in UNSELLABLE):
        return None
    for words, value in ITEM_VALUES:
        if any(word in name for word in words):
            return value
    return DEFAULT_VALUE


class EconomyMixin:
    """GameState의 경제 규칙. GameState가 상속한다(필드는 GameState에 있다)."""

    # ---------- 일 ----------
    def work_wage(self, job):
        """시간당 임금(USD)과 그 이유. 일자리가 없으면 0."""
        name, village, city, _, _ = JOBS[job]
        if self.place_type == "야생":
            return 0.0, ["야생에는 일자리가 없다"]
        if self.hour in NIGHT_HOURS and job != "street":
            return 0.0, ["한밤중이라 일자리가 없다(길거리 일만 가능)"]
        base = city if self.place_type == "도시" else village
        level = self.skills.get(job, 0)
        wage = round(base * (1 + SKILL_BONUS * level), 2)
        reasons = [f"{self.place_type} {name} 시급 ${base:g}"] + ([f"기술 Lv{level} +{level * 15}%"] if level else [])
        if self.notorious_here():
            wage = round(wage * 0.5, 2)
            reasons.append("범죄자로 알려진 곳 -50%")
        return wage, reasons

    def work(self, job, hours):
        """일을 하고 임금을 받는다. 시간이 흐르고, 기술 경험이 쌓인다."""
        job = job if job in JOBS else "labor"
        hours = max(1.0, min(float(hours or 1), MAX_WORK_HOURS))
        wage, reasons = self.work_wage(job)
        if wage <= 0:
            return {"success": False, "message": reasons[0] + ". 일하지 못했다고 서술하라."}
        self.pass_time(hours, JOBS[job][3])
        self.turn_flags["time"] = 1
        pay = round(wage * hours, 2)
        self.money = round(self.money + pay, 2)
        self.turn_flags["earned"] = self.turn_flags.get("earned", 0) + pay
        self.turn_flags.setdefault("money_log", []).append({"amount": pay, "why": f"{JOBS[job][0]} {hours:g}시간",
                                                                 "shown": True})
        before = self.skills.get(job, 0)
        self.work_hours[job] = self.work_hours.get(job, 0) + hours
        self.skills[job] = min(SKILL_MAX, int(self.work_hours[job] // SKILL_HOURS))
        leveled = self.skills[job] > before
        self.turn_flags["economy"] = {"kind": "work", "job": JOBS[job][0], "hours": hours, "amount": pay,
                                      "level": self.skills[job], "leveled": leveled}
        return {"success": True, "earned": pay, "wage": wage, "보정": reasons,
                "message": f"{JOBS[job][0]} {hours:g}시간 → ${pay:.0f} (시급 ${wage:g}). 돈과 시간은 엔진이 반영했다"
                           + (f". {JOBS[job][0]} 기술이 Lv{self.skills[job]}로 올랐다" if leveled else "")
                           + ". 서술의 금액을 이와 같게 하라."}

    # ---------- 팔기 ----------
    def sell_item(self, name):
        """소지품을 판다. 값은 시세 × 장소(도시 80%, 마을 60%), 훔친 물건은 그 반값."""
        if self.place_type == "야생":
            return {"success": False, "message": "야생에는 살 사람이 없다. 마을이나 도시에서 팔 수 있다."}
        item = self.find_item(name)
        if item is None:
            return {"success": False, "message": f"'{name}'은(는) 소지품에 없다."}
        value = item_value(item)
        if value is None:
            return {"success": False, "message": f"{item}은(는) 팔 수 없다(팔면 귀국할 수 없다)."}
        rate = CITY_PRICE if self.place_type == "도시" else VILLAGE_PRICE
        stolen = item in self.stolen_items
        price = round(max(1.0, value * rate * (FENCE_RATE if stolen else 1)), 2)
        self.items.remove(item)
        if stolen:
            self.stolen_items.remove(item)
        self.money = round(self.money + price, 2)
        self.turn_flags["earned"] = self.turn_flags.get("earned", 0) + price
        self.turn_flags.setdefault("money_log", []).append({"amount": price, "why": f"{item} 판매", "shown": True})
        self.turn_flags["economy"] = {"kind": "sell", "item": item, "amount": price, "stolen": stolen}
        return {"success": True, "earned": price,
                "message": f"{item}을(를) ${price:.0f}에 팔았다" + (" (장물이라 헐값)" if stolen else "")
                           + ". 돈은 엔진이 반영했다. 서술의 금액을 이와 같게 하라."}

    # ---------- 숙소 ----------
    @property
    def in_lodging(self):
        """빌린 방에 있는가 (같은 곳, 기간 안, 실내)."""
        room = self.lodging
        return bool(room) and self.elapsed_hours < room.get("until", 0) and \
            (room.get("lat"), room.get("lon")) == (self.lat, self.lon) and self.indoor

    def rent_room(self, nights=1):
        """방을 빌린다. 숙소 안에서는 날씨를 피해 쉬고, 은신처가 된다(수배도가 더 빨리 내려가고 경찰이 덜 찾아옴)."""
        price = ROOM_PRICE.get(self.place_type)
        if not price:
            return {"success": False, "message": "야생에는 빌릴 방이 없다."}
        nights = max(1, min(int(nights or 1), 7))
        cost = price * nights
        paid = self.pay(cost, f"숙박 {nights}박")
        if not paid["success"]:
            return paid
        self.turn_flags["money_log"][-1]["shown"] = True     # 숙소 알림이 따로 있다
        self.lodging = {"lat": self.lat, "lon": self.lon, "place": self.place_name,
                        "until": self.elapsed_hours + 24 * nights, "nights": nights}
        self.set_scene("indoor", f"{self.place_name}의 빌린 방", "a small rented room with a simple bed",
                       ["침대", "작은 창문"])
        self.turn_flags["economy"] = {"kind": "room", "nights": nights, "amount": -cost}
        return {"success": True, "message": f"방을 {nights}박 ${cost}에 빌렸다. 장면은 그 방 안으로 바뀌었다. "
                                            "이곳은 은신처로 쓸 수 있다."}

    # ---------- 도박 ----------
    def gamble(self, stake, game=""):
        """판돈을 걸고 도박을 한다(마을·도시). 이기면 판돈만큼, 드물게 잭팟(5배)."""
        if self.place_type == "야생":
            return {"success": False, "message": "야생에는 도박판이 없다."}
        stake = round(max(1.0, min(float(stake or 0), GAMBLE_MAX_STAKE, self.money)), 2)
        if self.money < 1:
            return {"success": False, "message": "걸 돈이 없다."}
        roll = random.random()
        jackpot = roll >= 1 - JACKPOT_CHANCE * (1 if CRITICAL_CHANCE else 0)
        won = jackpot or roll < GAMBLE_WIN_CHANCE
        change = stake * 5 if jackpot else (stake if won else -stake)
        self.money = round(self.money + change, 2)
        if change > 0:
            self.turn_flags["earned"] = self.turn_flags.get("earned", 0) + change
        else:
            self.turn_flags["paid"] = self.turn_flags.get("paid", 0) - change
        self.turn_flags.setdefault("money_log", []).append({"amount": change, "why": f"도박({game or '내기'})",
                                                                 "shown": True})
        self.pass_time(1, "other")
        self.turn_flags["time"] = 1
        self.turn_flags["economy"] = {"kind": "gamble", "game": game, "stake": stake, "amount": change,
                                      "jackpot": jackpot}
        return {"success": won, "jackpot": jackpot, "change": change,
                "message": ("잭팟! " if jackpot else "") + (f"판돈 ${stake:.0f}을(를) 걸어 "
                           + (f"${change:.0f}을(를) 땄다" if won else "잃었다"))
                           + f". 남은 돈 ${self.money:.0f}. 결과는 엔진이 정했다. 그대로 서술하라."}
