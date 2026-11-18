"""플레이어 입력에 범죄 의도가 있는지 판정한다.

- explicit : 입력 자체가 범죄를 말한다 ("트럭을 빼앗는다", "기사를 기절시킨다", "지갑을 훔친다")
- context  : 입력은 모호하지만("트럭을 타려고 시도한다"), 직전 추천 행동이나 최근 입력에서 같은 대상에 대한
             범죄를 이미 고려했다 ("트럭을 훔칠까?" → "트럭을 타려고 시도한다")
- none     : 범죄 의도가 없다. 모호한 행동은 합법적인 방법(부탁, 흥정, 요금 지불)으로 해석한다.

게임 마스터가 '트럭을 타려 한다'를 마음대로 '트럭을 훔친다'로 바꾸지 못하게 하려는 장치다.
"""
import re


# 그 자체로 범죄를 뜻하는 말 (활용형까지 고려해 앞부분만)
CRIME_WORDS = (
    # 훔치기
    "훔치", "훔쳐", "훔칠", "훔친", "훔쳤", "도둑질", "슬쩍", "소매치기", "빼돌", "가로채", "가로챌", "가로챘",
    # 빼앗기·강도
    "빼앗", "뺏", "강탈", "탈취", "약탈", "털어", "털자", "털겠", "털고", "털었", "강도",
    # 협박·폭력
    "협박", "위협하", "위협해", "위협한", "때리", "때려", "때릴", "때렸", "폭행", "기절시", "제압", "공격하", "공격해",
    "공격한", "찌르", "찔러", "목을조", "칼을들이", "칼로위협", "납치", "인질",
    # 몰래 타기·침입 (무임승차, 밀항, 무단 침입)
    "몰래타", "몰래탄", "몰래탈", "몰래탔", "몰래올라", "숨어타", "숨어탄", "숨어탈", "숨어탔", "숨어들", "몰래들어",
    "무임", "밀항", "밀입국", "침입", "부수고", "부숴", "깨고들어", "자물쇠를따",
    # 속이기
    "속이", "속여", "속일", "속였", "사기",
    # 방화·뇌물·위조·밀수
    "불을지르", "불을질러", "불을지를", "불을질렀", "불을놓", "방화", "뇌물", "위조", "가짜여권", "가짜서류", "밀수",
    # 무단 운전
    "시동을걸어", "시동을걸고", "직결",
)
# '남의 것을 가져간다'처럼 '누구의 것인지'와 '가져가는 행동'이 함께 있으면 절도로 본다
OWNER_WORDS = ("남의", "주인몰래", "주인이없는틈", "주인없는틈", "허락없이", "허락도없이", "몰래", "아무도안볼때",
               "보는사람이없을때", "값을치르지않고", "돈을내지않고", "돈안내고", "계산하지않고")
TAKE_WORDS = ("가져", "챙겨", "챙기", "캐가", "캐서가", "캐간", "따가", "따간", "따서가", "들고가", "들고간", "들고도망",
              "갖고가", "가지고가", "가지고간", "몰고가", "몰고간", "타고가", "타고간", "주머니에넣", "품에넣", "배낭에넣",
              "먹어치", "마셔버", "꺼내", "빼내")
# 범죄 낱말이 들어 있어도 다른 뜻인 것 (띄어쓰기 없이 비교)
NOT_CRIME = ("훔쳐보", "훔쳐본", "훔쳐봤", "훔쳐볼", "속이안좋", "속이좋지", "속이메스", "속이뒤틀", "속이쓰",
             "위협을피", "위협적인", "공격을피", "공격을막", "공격당", "공격해오", "공격해온",
             "모닥불", "장작에불", "불을피", "불을붙여몸", "사기가올라", "사기가떨어", "사기를북돋", "남의도움", "남의말")

JOSA = ("에서", "으로", "에게", "한테", "이", "가", "을", "를", "은", "는", "의", "에", "로", "와", "과", "도")
STOP = ("시도", "시도한다", "한다", "하려고", "하자", "해", "본다", "그것", "저것", "이것", "어떻게", "잠깐", "조금", "다시",
        "몰래", "얼른", "빨리", "같이")


def _any_batchim(syllable):
    """한 글자의 받침만 바꾼 모든 글자 ('르' → '르른를름…', '기' → '기긴길김…'). 한글이 아니면 그 글자만."""
    code = ord(syllable) - 0xAC00
    if not 0 <= code < 11172:
        return re.escape(syllable)
    base = code - code % 28
    return "[" + "".join(chr(0xAC00 + base + i) for i in range(28)) + "]"


def _pattern(words):
    """마지막 글자는 받침이 붙어도 같은 말로 본다: '불을지르' 는 '불을지른', '챙기' 는 '챙긴', '숨어타' 는 '숨어탄'."""
    return re.compile("|".join(re.escape(w[:-1]) + _any_batchim(w[-1]) for w in words if w))


_CRIME = None
_OWNER = None
_TAKE = None


def has_crime_words(text):
    """띄어쓰기와 상관없이 범죄를 뜻하는 말이 있는지."""
    flat = (text or "").replace(" ", "").replace("?", "")
    for safe in NOT_CRIME:
        flat = flat.replace(safe, "|")
    global _CRIME, _OWNER, _TAKE
    if _CRIME is None:
        _CRIME, _OWNER, _TAKE = _pattern(CRIME_WORDS), _pattern(OWNER_WORDS), _pattern(TAKE_WORDS)
    if _CRIME.search(flat):
        return True
    return bool(_OWNER.search(flat) and _TAKE.search(flat))


def nouns(text):
    """대상을 가리키는 명사 쪽 낱말(두 글자 이상, 조사 떼고, 동사·흔한 말 제외)."""
    words = []
    for raw in (text or "").split():
        w = raw.strip(".,!?\"'()“”~")
        for josa in JOSA:
            if w.endswith(josa) and len(w) - len(josa) >= 2:
                w = w[: -len(josa)]
                break
        if len(w) >= 2 and not w.endswith(("다", "까", "자", "고", "려", "며", "서")) and w not in STOP:
            words.append(w)
    return words


def crime_intent(text, prev_suggestions=(), recent_inputs=()):
    """(판정, 근거) 를 돌려준다. 판정: 'explicit' / 'context' / 'none'."""
    if has_crime_words(text):
        return "explicit", text
    targets = set(nouns(text))
    if targets:
        for source in list(prev_suggestions) + list(recent_inputs):
            if has_crime_words(source) and targets & set(nouns(source)):
                return "context", source
    return "none", ""
