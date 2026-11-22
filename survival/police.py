"""경찰과 추격: 수배 단계(★1~5), 경찰의 등장, 플레이어의 대응(도주·숨기·뇌물·둘러대기·싸움·자수) 판정, 은신과 변장.

기회(offers)와 같은 방식이다. 경찰이 나타난 턴에는 GM이 그 장면을 서술하고, 플레이어의 다음 입력은 GM을 부르기 전에
엔진이 먼저 판정한다(`resolve_police`). GM은 결과를 받아 서술만 한다. 성패를 GM이 정하지 않는다.
"""
import random
import re

from .config import CRITICAL_CHANCE, WANTED_DECAY_PER_HOUR
from .economy import SAFEHOUSE_LAY_LOW, SAFEHOUSE_POLICE
from .util import clamp

STAGE_FLOORS = (1, 20, 40, 60, 80)          # 수배도가 이 값 이상이면 ★1 ~ ★5
STAGE_NAMES = {0: "", 1: "소문", 2: "수상한 사람", 3: "지명수배", 4: "추적 중", 5: "전국 수배"}
# 한 턴에 경찰이 나타날 기본 확률 (단계별)
ENCOUNTER_CHANCE = {2: 0.10, 3: 0.20, 4: 0.35, 5: 0.50}
PLACE_FACTOR = {"도시": 1.0, "마을": 0.6, "야생": 0.15}
ROAD_FACTOR = 0.4                            # 야생이라도 도로 위면
BRIBE_COST = {1: 20, 2: 40, 3: 80, 4: 150, 5: 300}
DISGUISE_HOURS = 48
LAY_LOW_MULTIPLIER = 4                       # 숨어 지내면 수배도가 이만큼 빨리 내려간다

# 플레이어 입력 → 대응 종류 (앞에 있는 것이 우선)
RESPONSES = (
    ("surrender", ("항복", "자수", "손을 들", "두 손을 들", "순순히", "체포에 응")),
    ("bribe", ("뇌물", "돈을 건네", "돈을 쥐여", "돈을 찔러", "돈으로 해결", "돈을 주고 넘어", "눈감아")),
    ("fight", ("때리", "때려", "싸우", "싸운", "덤비", "덤빈", "제압", "밀치", "밀쳐", "주먹", "공격", "총을")),
    ("hide", ("숨는", "숨어", "숨긴", "숨을", "몸을 숨", "몸을 낮", "은신", "엎드", "웅크")),
    ("flee", ("도망", "달아나", "달아난", "튀어", "튄다", "뛰어", "뛴다", "질주", "따돌", "전속력", "액셀", "밟아",
              "밟는다", "골목으로", "빠져나", "탈출")),
    ("bluff", ("둘러대", "둘러댄", "거짓말", "설득", "관광객", "신분증", "여권을 보여", "모른 척", "모르는 척",
               "태연", "아닌 척", "사람을 잘못")),
)
# 활용형을 함께 적는다: '지낸다'의 '낸'은 '지내'의 '내'와 다른 글자라 '지내'로는 찾지 못한다
LAY_LOW_WORDS = ("숨어 지내", "숨어 지낸", "숨어지내", "숨어지낸", "잠수", "은신처", "몸을 숨기고 쉬", "몸을 숨기고 쉰",
                 "조용히 지내", "조용히 지낸", "숨어서 쉬", "숨어서 쉰", "잠적", "밖에 나가지 않", "숨죽이고")
# 변장: 목적어와 동사 사이에 꾸미는 말이 끼어도 찾는다 ("머리를 짧게 자른다")
DISGUISE_WORDS = re.compile(r"변장|옷을.{0,8}(갈아입|바꿔 ?입)|머리를.{0,8}(자르|자른|잘라|깎|염색)|모자를.{0,6}눌러"
                            r"|선글라스|수염을.{0,6}(밀|민|깎)|얼굴을.{0,8}(가리|가린)")


# 변장에 쓸 물건 (머리·수염은 칼·가위·면도기가 있으면 된다)
DISGUISE_ITEMS = ("모자", "선글라스", "옷", "재킷", "외투", "스카프", "두건", "가발", "마스크", "후드", "목도리", "안경")
HAIR_WORDS = re.compile(r"머리를|수염을")
BLADE_ITEMS = ("칼", "가위", "면도")


def heat_stage(wanted):
    """수배도 → 단계(0~5)."""
    return sum(wanted >= floor for floor in STAGE_FLOORS)


def stars(wanted):
    stage = heat_stage(wanted)
    return "★" * stage + "☆" * (5 - stage)


def classify_response(text):
    """경찰 앞에서 플레이어가 한 행동의 종류. 알 수 없으면 'ignore'(경찰을 무시하고 다른 일을 했다)."""
    text = text or ""
    for kind, words in RESPONSES:
        if any(word in text for word in words):
            return kind
    return "ignore"


def mentions(text, words):
    """입력에 그 말이 있는가. words는 말 목록(띄어쓰기 무시) 또는 정규식."""
    if isinstance(words, re.Pattern):
        return bool(words.search(text or ""))
    compact = re.sub(r"\s+", "", text or "")
    return any(word.replace(" ", "") in compact for word in words)


def police_suggestions(state):
    """경찰이 막 나타난 턴의 추천 행동 3개 (버튼으로 바로 대응할 수 있게)."""
    pursuit = state.pursuit or {}
    if pursuit.get("kind") == "chase":
        flee = f"{state.vehicle['name']}을(를) 몰고 전속력으로 도망친다" if state.vehicle else "골목으로 전력 질주해 도망친다"
        return [flee, "근처에 몸을 숨긴다", "두 손을 들고 자수한다"]
    return ["관광객인 척 태연하게 둘러댄다", "틈을 봐서 골목으로 도망친다", "순순히 손을 들고 자수한다"]


class PoliceMixin:
    """GameState의 경찰과 추격 규칙. GameState가 상속한다(필드는 GameState에 있다)."""

    @property
    def heat(self):
        return heat_stage(self.wanted)

    @property
    def disguised(self):
        return bool(self.disguise) and self.elapsed_hours < self.disguise.get("until", 0)

    def police_encounter_chance(self):
        """이번 턴에 경찰이 나타날 확률."""
        base = ENCOUNTER_CHANCE.get(min(self.heat, 5), 0.0)
        if not base:
            return 0.0
        factor = PLACE_FACTOR.get(self.place_type, 0.15)
        if self.place_type == "야생" and self.flags.get("on_road"):
            factor = ROAD_FACTOR
        if self.is_night:
            factor *= 0.7
        if self.disguised:
            factor *= 0.4
        if self.in_lodging:
            factor *= SAFEHOUSE_POLICE              # 빌린 방(은신처) 안에는 경찰이 잘 찾아오지 않는다
        stolen = bool(self.vehicle and self.vehicle.get("stolen"))
        return round(min(0.9, base * factor + (0.15 if stolen else 0.0)), 3)

    def roll_police(self):
        """턴 시작에 경찰이 나타나는지 굴린다. 나타나면 pursuit 를 만든다(대응은 다음 턴에 판정)."""
        if self.pursuit or self.status != "playing" or random.random() >= self.police_encounter_chance():
            return None
        stage = self.heat
        stolen = bool(self.vehicle and self.vehicle.get("stolen"))
        chase = stage >= 4 or stolen
        if stage >= 5:
            who = "무장 경찰 특공대와 순찰차 여러 대" + (", 머리 위에는 헬기" if self.place_type != "야생" else "")
        elif chase:
            who = "사이렌을 울리는 순찰차"
        else:
            who = "순찰 중인 경찰관 두 명"
        self.pursuit = {"stage": stage, "turn": self.turn, "who": who, "kind": "chase" if chase else "check",
                        "stolen_vehicle": stolen}
        self.turn_flags["police"] = {"phase": "spotted", "who": who, "kind": self.pursuit["kind"], "stage": stage}
        return self.pursuit

    def police_chance(self, kind):
        """대응 종류별 성공 확률과 보정 이유."""
        stage = self.pursuit["stage"] if self.pursuit else self.heat
        night, wild = self.is_night, self.place_type == "야생"
        base = {"flee": 0.55, "hide": 0.50, "bribe": 0.70, "bluff": 0.45, "fight": 0.35}[kind]
        reasons = [f"★{stage} -{stage * 6}%"]
        chance = base - stage * 0.06
        if kind in ("flee", "hide") and night:
            chance += 0.10
            reasons.append("어둠 +10%")
        if kind == "flee" and self.vehicle:
            chance += 0.15
            reasons.append(f"{self.vehicle['name']} +15%")
        if kind == "flee" and self.place_type == "도시":
            chance += 0.05
            reasons.append("붐비는 도시 +5%")
        if kind == "hide" and wild:
            chance += 0.15
            reasons.append("숨을 곳이 많은 야생 +15%")
        if kind == "bluff" and self.disguised:
            chance += 0.25
            reasons.append("변장 +25%")
        if kind == "bluff" and stage >= 4:
            chance -= 0.25
            reasons.append("이미 얼굴이 알려짐 -25%")
        if kind in ("flee", "fight") and self.energy < 30:
            chance -= 0.15
            reasons.append("지쳐 있음 -15%")
        if kind in ("flee", "fight") and self.health < 40:
            chance -= 0.15
            reasons.append("부상 -15%")
        return round(min(0.9, max(0.05, chance)), 2), reasons

    def respond_to_police(self, kind):
        """경찰 앞에서의 대응을 판정하고 결과를 적용한다. kind: flee/hide/bribe/bluff/fight/surrender/ignore"""
        if not self.pursuit:
            return {"success": False, "message": "지금 쫓아오는 경찰은 없다."}
        pursuit, stage = self.pursuit, self.pursuit["stage"]
        effects, chance, reasons, success = [], None, [], False
        if kind == "surrender":
            result = self._arrest("자수", fine_rate=0.25, wanted_cut=60, hours=12)
            effects.append("자수 — 처벌 경감(벌금 25%, 12시간 구금, 수배도 -60)")
            outcome = "arrested"
        elif kind == "ignore":
            caught = random.random() < 0.75
            outcome = "arrested" if caught else "lost"
            effects.append("경찰을 무시했다" + (" — 붙잡힘" if caught else " — 운 좋게 경찰이 다른 데로 갔다"))
            result = self._arrest(pursuit["who"].split(",")[0]) if caught else {}
        else:
            chance, reasons = self.police_chance(kind)
            cost = BRIBE_COST.get(max(1, stage), 300)
            if kind == "bribe" and self.money < cost:
                chance, reasons = 0.0, [f"가진 돈 ${self.money:.0f} < 필요한 돈 ${cost}"]
            roll = random.random()
            success = roll < chance
            critical = success and random.random() >= 1 - CRITICAL_CHANCE
            if success:
                outcome = "escaped"
                if kind == "bribe":
                    self.money = round(self.money - cost, 2)
                    self.turn_flags["paid"] = self.turn_flags.get("paid", 0) + cost
                    self.turn_flags.setdefault("money_log", []).append({"amount": -cost, "why": "경찰 뇌물"})
                    self.wanted = clamp(self.wanted - 25)
                    effects.append(f"뇌물 ${cost} — 경찰이 눈감아 줌, 수배도 -25")
                elif kind == "fight":
                    self.wanted = clamp(self.wanted + 20)
                    self.health = clamp(self.health - 10)
                    effects.append("경찰을 제압하고 달아남 — 경찰 폭행으로 수배도 +20, 체력 -10")
                else:
                    cut = 15 if critical else 5
                    self.wanted = clamp(self.wanted - cut)
                    effects.append(f"{'영화 같은 탈출! ' if critical else ''}경찰을 따돌림 — 수배도 -{cut}")
                result = {}
            else:
                outcome = "arrested"
                if kind == "bribe" and chance > 0:
                    self.wanted = clamp(self.wanted + 10)
                    effects.append("뇌물을 내밀었다가 괘씸죄 — 수배도 +10")
                if kind == "fight":
                    self.health = clamp(self.health - 20)
                    effects.append("경찰과 몸싸움 끝에 제압당함 — 체력 -20")
                    self._check_death("경찰과의 격렬한 몸싸움 끝에 쓰러졌다")
                if kind == "flee" and pursuit.get("stolen_vehicle") and self.vehicle:
                    effects.append(f"추격 끝에 {self.vehicle['name']}이(가) 가로막힘")
                result = self._arrest(pursuit["who"].split(",")[0]) if self.status == "playing" else {}
        self.pursuit = None
        self.pass_time(0.5, "other")
        self.turn_flags["time"] = 1            # 시간은 엔진이 흘렸다 (GM이 advance_time 으로 한 번 더 흘리지 못하게)
        record = {"phase": "resolved", "action": kind, "outcome": outcome, "chance": chance, "success": success,
                  "effects": effects, "reasons": reasons, "who": pursuit["who"]}
        message = (f"[엔진 판정] 경찰 대응: {kind} → "
                   + {"escaped": "벗어났다", "arrested": "붙잡혔다", "lost": "경찰이 놓쳤다"}[outcome]
                   + (f" (성공 확률 {chance * 100:.0f}%)" if chance is not None else "") + ". "
                   + " · ".join(effects) + (" " + result["message"] if result.get("message") else ""))
        record["message"] = message
        self.turn_flags["police"] = record
        return {"success": outcome != "arrested", "outcome": outcome, "message": message}

    def lay_low(self, hours):
        """숨어 지낸 시간만큼 수배도를 더 빨리 낮춘다(기본 감소에 더해 LAY_LOW_MULTIPLIER-1 배)."""
        multiplier = SAFEHOUSE_LAY_LOW if self.in_lodging else LAY_LOW_MULTIPLIER   # 은신처면 더 빨리
        cut = WANTED_DECAY_PER_HOUR * (multiplier - 1) * max(0.0, hours)
        before = self.wanted
        self.wanted = max(0.0, self.wanted - cut)
        return round(before - self.wanted, 1)

    def try_disguise(self, how):
        """변장을 시도한다. 쓸 물건이 있어야 된다(머리·수염은 칼·가위). 결과를 turn_flags.disguise 에 남긴다."""
        if HAIR_WORDS.search(how or ""):        # 머리·수염을 바꾸려면 칼·가위·면도기
            tools = [i for i in self.items if any(w in i for w in BLADE_ITEMS)]
        else:
            tools = [i for i in self.items if any(w in i for w in DISGUISE_ITEMS)]
        if not tools and self.place_type == "야생":
            self.turn_flags["disguise"] = {"ok": False, "why": "변장할 물건(모자·선글라스·옷 등)이 없다"}
            return False
        if not tools:
            self.turn_flags["disguise"] = {"ok": False,
                                           "why": "변장할 물건이 없다. 가게에서 모자·옷·선글라스 등을 먼저 사야 한다"}
            return False
        self.put_on_disguise(how)
        self.turn_flags["disguise"] = {"ok": True, "with": tools[:2]}
        return True

    def put_on_disguise(self, how):
        self.disguise = {"until": self.elapsed_hours + DISGUISE_HOURS, "how": str(how)[:40]}
        return self.disguise

    def police_status(self):
        """GM 입력용 요약. 수배되지 않았으면 None."""
        if self.wanted < 1 and not self.pursuit:
            return None
        parts = [f"수배 {stars(self.wanted)} ({STAGE_NAMES[self.heat] or '없음'}, 수배도 {self.wanted:.0f})"]
        if self.disguised:
            parts.append(f"변장 중({self.disguise.get('how', '')}) — 알아보기 어렵다")
        if self.pursuit:
            parts.append(f"경찰이 바로 앞에 있다: {self.pursuit['who']} "
                         f"({'추격' if self.pursuit['kind'] == 'chase' else '검문'})")
        return " · ".join(parts)
