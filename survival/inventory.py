"""소지품과 돈: 물건 넣고 빼기, 먹고 마시기(용량이 적힌 물의 일부만 마시기 포함), 돈 쓰기."""
import re

from .config import CONSUMABLES, HYDRATION_PER_LITER, SIP_ML
from .util import clamp

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

VOLUME = re.compile(r"(\d+(?:\.\d+)?)\s*(ml|mL|ML|밀리리터|L|l|리터)(?![A-Za-z])")

# 일부만 마신다는 표현. '반'은 '반드시·반대' 같은 말과 섞이지 않게 붙는 말까지 본다
SIP_WORDS = re.compile(r"(?:한|두|세|몇|\d+)\s*모금|살짝|아껴|조금(?:만|씩)?\s*(?:마시|마셔|마신|들이|목을)|입만\s*축")

HALF_WORDS = re.compile(r"절반|반쯤|반만|반\s*병|반\s*정도|반을\s*(?:마시|마셔|마신|들이)")


def liquid_ml(name):
    """'물 1L' → 1000, '생수 500ml' → 500. 용량이 적혀 있지 않으면 None."""
    match = VOLUME.search(name)
    if not match:
        return None
    value = float(match.group(1))
    return round(value if match.group(2).lower() in ("ml", "밀리리터") else value * 1000)


def with_volume(name, ml):
    """이름의 용량을 바꾼다: ('물 1L', 750) → '물 750ml', ('물 2L', 1500) → '물 1.5L'."""
    label = f"{ml / 1000:g}L" if ml >= 1000 else f"{ml}ml"
    return VOLUME.sub(label, name, count=1)


def partial_portion(text, ml):
    """플레이어가 일부만 마신다고 했으면 이번에 마시는 양(ml). 다 마시면 None."""
    text = text or ""
    if HALF_WORDS.search(text):
        used = ml // 2
    elif SIP_WORDS.search(text):
        used = SIP_ML
    else:
        return None
    return used if 0 < used < ml else None


def consumable_effect(name):
    """먹거나 마시는 물건이면 (오르는 수치, 기본 회복량). 아니면 None.

    용량이 적힌 마실 것은 용량에 비례한다(1L = +45, 500ml = +22). 한 번에 오르는 양은 8~60.
    """
    for words, stat, amount in CONSUMABLES:
        if any(w in name for w in words):
            ml = liquid_ml(name) if stat == "hydration" else None
            if ml:
                amount = max(8, min(60, round(HYDRATION_PER_LITER * ml / 1000)))
            return stat, amount
    return None


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
    """'에너지바 2개', '빗물(1회분)', '물 750ml' → '에너지바', '빗물', '물' : 수량과 괄호를 뗀 물건 이름."""
    core = re.sub(r"\(.*?\)|\d+(?:\.\d+)?\s*(?:개|병|ml|mL|ML|밀리리터|L|l|리터|회분|모금|장|통|캔|봉지|알)?", "", name)
    return core.replace(" ", "")


class InventoryMixin:
    """GameState의 소지품과 돈 규칙. GameState가 상속한다(필드는 GameState에 있다)."""

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

    def sip_item(self, item):
        """플레이어가 '조금·한 모금·반만' 마신다고 했으면 용량만 줄이고 True. 아니면 False.

        '물 1L'을 조금 마시면 '물 750ml'가 남고, 마신 양만큼만 회복한다.
        """
        effect = consumable_effect(item)
        ml = liquid_ml(item)
        if not effect or effect[0] != "hydration" or not ml:
            return False
        used = partial_portion(self.turn_flags.get("player_text", ""), ml)
        if not used:
            return False
        left = with_volume(item, ml - used)
        self.items[self.items.index(item)] = left
        self.turn_flags["consumed"] = True
        amount = max(1, round(HYDRATION_PER_LITER * used / 1000))
        self.turn_flags.setdefault("eaten", []).append({"item": item_core(item) or item, "stat": "hydration",
                                                        "amount": amount, "partial": True})
        self.turn_flags.setdefault("partial", []).append(f"{item} → {left} ({used}ml 마심)")
        return True

    def consume_item(self, name):
        """물건을 한 번 써서 없앤다. '에너지바 2개'처럼 수량이 있으면 하나만 줄인다.

        용량이 적힌 마실 것을 일부만 마신다고 했으면 용량만 줄인다(sip_item).
        """
        item = self.find_item(name)
        if item is None:
            return False
        if self.sip_item(item):
            return True
        count = re.search(r"(\d+)\s*(개|병|장|캔|봉지|알)", item)
        index = self.items.index(item)
        if count and int(count.group(1)) > 1:
            left = int(count.group(1)) - 1
            self.items[index] = item[:count.start(1)] + str(left) + item[count.end(1):]
        else:
            self.items.pop(index)
        self.turn_flags["consumed"] = True
        effect = consumable_effect(item)
        if effect:
            self.turn_flags.setdefault("eaten", []).append({"item": item_core(item) or item, "stat": effect[0],
                                                            "amount": effect[1],
                                                            "measured": liquid_ml(item) is not None})
        return True

    def settle_consumption(self):
        """먹고 마신 것의 회복을 보장한다. GM이 회복을 빠뜨리거나 작게 줬으면 기본 회복량까지 채운다."""
        eaten = self.turn_flags.get("eaten") or []
        given = self.turn_flags.get("gm_gain") or {}
        for stat in ("hydration", "satiety"):
            need = sum(e["amount"] for e in eaten if e["stat"] == stat)
            short = need - given.get(stat, 0)
            if need and short > 0:
                setattr(self, stat, clamp(getattr(self, stat) + short))
                given[stat] = need
        self.turn_flags["gm_gain"] = given

    def _note_gain(self, stat, amount):
        if amount > 0:
            gains = self.turn_flags.setdefault("gm_gain", {})
            gains[stat] = gains.get(stat, 0) + amount

    def update_items(self, add=None, remove=None):
        """소지품을 추가/제거한다. 넣을 수 없는 것은 거부하고 그 목록을 반환한다."""
        rejected = []
        added = {item_core(str(e.get("name", "") if isinstance(e, dict) else e)) for e in add or []}
        for name in remove or []:
            item = self.find_item(name)
            # GM이 '물 1L'을 지우기만 했는데 플레이어는 조금만 마셨다: 남은 물을 남긴다
            # (GM이 직접 '물 750ml'를 넣어 주는 경우는 GM의 처리를 따른다)
            if item and item_core(item) not in added and self.sip_item(item):
                continue
            if item:
                self.items.remove(item)
                self.turn_flags["consumed"] = True
                self.turn_flags.setdefault("removed_items", []).append(item)
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
        self.turn_flags.setdefault("money_log", []).append({"amount": -amount, "why": purpose or "값"})
        return {"success": True, "message": f"{purpose or '값'}으로 ${amount:.0f}을(를) 냈다. 남은 돈 ${self.money:.0f}."}
