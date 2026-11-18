"""단서(lead): 이야기의 개연성을 지키기 위한 장치.

'멀리서 엔진 소리가 들린다' 같은 단서가 생기는 순간, 엔진이 그 소리의 정체(도로, 마을, 벌목장 등)와
방향·거리를 지형과 시간에 맞게 미리 정해 둔다. 플레이어가 그쪽으로 가면 정해 둔 정체가 반드시 나타난다.
그래서 '소리를 따라갔더니 아무것도 없었다' 같은 일이 생기지 않는다.
"""
import random

# 단서 종류: 이름, 정체 후보(가중치), 거리 범위(km)
LEAD_KINDS = {
    "engine":   {"label": "엔진 소리", "targets": {"road": 6, "village": 3, "logging": 1}, "km": (1, 5)},
    "smoke":    {"label": "연기", "targets": {"camp": 5, "village": 4, "wildfire": 1}, "km": (2, 10)},
    "light":    {"label": "불빛", "targets": {"house": 4, "village": 4, "camp": 2}, "km": (2, 8)},
    "settlement": {"label": "멀리 보이는 마을", "targets": {"village": 1}, "km": (4, 15)},
    "tracks":   {"label": "바퀴 자국", "targets": {"road": 6, "village": 3, "camp": 1}, "km": (3, 15)},
    "power":    {"label": "송전탑", "targets": {"road": 5, "village": 5}, "km": (5, 20)},
    "river":    {"label": "강물", "targets": {"village": 5, "fishing": 3, "bridge": 3}, "km": (4, 15)},
    "trail":    {"label": "사람이 낸 길 표시", "targets": {"village": 5, "road": 3, "house": 2}, "km": (5, 15)},
    "herd":     {"label": "가축 떼와 방울 소리", "targets": {"camp": 7, "village": 3}, "km": (2, 8)},
    "chainsaw": {"label": "전기톱 소리", "targets": {"logging": 1}, "km": (1, 4)},
    "caravan":  {"label": "대상 행렬", "targets": {"caravan": 1}, "km": (2, 6)},
    "signal":   {"label": "휴대폰 신호", "targets": {"high_ground": 1}, "km": (1, 3)},
    "water":    {"label": "물이 있다는 표시", "targets": {"water": 1}, "km": (1, 4)},
}

# 지형에 맞지 않는 정체는 다른 것으로 바꾼다 (예: 사막에 벌목장은 없다)
NOT_IN_BIOME = {
    "logging": ("desert", "snow", "savanna", "alpine"),
    "fishing": ("desert",),
    "wildfire": ("snow", "alpine", "jungle"),
}

# 지형별 '캠프'의 모습
CAMP_BY_BIOME = {
    "snow": ("순록 유목민의 천막", ["원뿔 모양 가죽 천막", "순록 떼", "장작 더미"]),
    "alpine": ("목동의 돌 움막", ["돌 움막", "야크 떼", "말린 똥 연료 더미"]),
    "desert": ("유목민 천막", ["검은 천막", "낙타", "물 가죽 부대"]),
    "savanna": ("목축민의 울타리 마을", ["가시나무 울타리", "흙집", "소 떼"]),
    "jungle": ("채집꾼 캠프", ["나뭇잎 지붕 움막", "모닥불", "말리는 생선"]),
    "forest": ("사냥꾼 캠프", ["방수포 천막", "모닥불 자리", "사냥 도구"]),
}

def eul(word):
    """받침에 맞는 목적격 조사: '불빛을', '엔진 소리를'."""
    last = str(word).strip()[-1:]
    if "가" <= last <= "힣":
        return word + ("을" if (ord(last) - 0xAC00) % 28 else "를")
    return word + "을(를)"


DIRECTIONS = ["북쪽", "북동쪽", "동쪽", "남동쪽", "남쪽", "남서쪽", "서쪽", "북서쪽"]


def compass(bearing):
    return DIRECTIONS[int(((bearing % 360) + 22.5) // 45) % 8]


def make_lead(kind, clue, biome, rng=random, bearing=None):
    """단서를 만들고, 그 정체·방향·거리를 지금 정해 둔다."""
    spec = LEAD_KINDS[kind]
    targets = {t: w for t, w in spec["targets"].items() if biome not in NOT_IN_BIOME.get(t, ())}
    targets = targets or {"village": 1}
    target = rng.choices(list(targets), weights=list(targets.values()), k=1)[0]
    lo, hi = spec["km"]
    return {"kind": kind, "label": spec["label"], "clue": str(clue)[:80], "target": target,
            "km": round(rng.uniform(lo, hi), 1),
            "bearing": round(rng.uniform(0, 360) if bearing is None else bearing)}


def reveal(lead, biome, night, rng=random):
    """단서를 따라가 도착했을 때 무엇이 있는지. 지형과 도착 시각(밤/낮)에 따라 모습이 달라진다.

    반환: place_type(장소 유형), scene(장면 이름), setting, features(보이는 것들),
          description_en(그림용), text(GM에게 줄 사실), effects(엔진 효과 이름들)
    """
    t = lead["target"]
    if t == "road":
        paved = rng.random() < 0.5
        name = "포장도로 가장자리" if paved else "비포장 도로"
        traffic = ("가끔 트럭과 승용차가 지나간다. 히치하이킹을 해 볼 만하다." if not night
                   else "밤이라 차가 거의 다니지 않는다. 아주 드물게 헤드라이트가 보인다.")
        return dict(place_type="야생", scene=name, setting="outdoor",
                    features=["도로", "도로 표지판"] + (["멀리 지나가는 트럭"] if not night else []),
                    description_en=f"A lonely {'asphalt' if paved else 'dirt'} road crossing the wilderness, a faded road sign.",
                    text=f"{lead['label']}의 정체는 도로였다. {traffic}", effects=["on_road"])
    if t == "village":
        mood = ("사람들이 오가고 아이들이 뛰어논다. 가게와 우물이 있다." if not night
                else "대부분 잠들었지만 불이 켜진 집이 몇 채 있다. 개 짖는 소리가 난다.")
        return dict(place_type="마을", scene="마을 입구", setting="outdoor",
                    features=["마을 입구", "작은 집들", "우물"],
                    description_en="The entrance of a small rural village with simple local houses and a well.",
                    text=f"{eul(lead['label'])} 따라가자 마을이 나왔다. {mood}", effects=[])
    if t == "house":
        mood = "집 앞에서 주인이 경계하며 바라본다." if not night else "창문에 불이 켜져 있고, 안에서 인기척이 난다."
        return dict(place_type="야생", scene="외딴 농가", setting="outdoor",
                    features=["외딴 농가", "가축 우리", "장작 더미"],
                    description_en="A lone farmhouse in the wilderness with a small animal pen and a woodpile.",
                    text=f"{lead['label']}의 정체는 외딴 농가였다. {mood}", effects=[])
    if t == "camp":
        name, features = CAMP_BY_BIOME.get(biome, CAMP_BY_BIOME["forest"])
        mood = "사람들이 일하다가 낯선 당신을 쳐다본다." if not night else "모닥불 곁에 사람들이 모여 있다."
        return dict(place_type="야생", scene=name, setting="outdoor", features=list(features),
                    description_en=f"A small traditional camp of local herders or hunters: {', '.join(features)}.",
                    text=f"{lead['label']}의 정체는 {name}였다. {mood} 먹을 것과 물을 얻거나 물건을 바꿀 수 있을지 모른다.",
                    effects=[])
    if t == "logging":
        mood = ("벌목꾼들이 일하고 있고, 통나무를 실은 트럭이 서 있다. 트럭은 곧 마을로 내려간다." if not night
                else "일은 끝났고 경비원 한 명이 컨테이너 숙소를 지킨다. 트럭이 세워져 있다.")
        return dict(place_type="야생", scene="벌목장", setting="outdoor",
                    features=["벌목장", "통나무 운반 트럭", "컨테이너 숙소"],
                    description_en="A logging site in the forest: stacked logs, a log truck and a container cabin.",
                    text=f"{lead['label']}의 정체는 벌목장이었다. {mood}", effects=["on_road"])
    if t == "fishing":
        return dict(place_type="야생", scene="강가의 어부 오두막", setting="outdoor",
                    features=["어부 오두막", "나무배", "그물"],
                    description_en="A fishermen's hut on a riverbank with wooden boats and nets.",
                    text="강을 따라 내려가자 어부들의 오두막과 배가 나왔다. 하류의 마을로 가는 배가 있을지 모른다.",
                    effects=[])
    if t == "bridge":
        return dict(place_type="야생", scene="다리가 놓인 도로", setting="outdoor",
                    features=["다리", "도로"],
                    description_en="A bridge over the river carrying a road.",
                    text="강을 따라가자 다리와 도로가 나왔다. 차가 다니는 길이다.", effects=["on_road"])
    if t == "caravan":
        mood = "상인들이 짐을 꾸리고 있다." if not night else "모닥불 곁에서 상인들이 차를 끓인다."
        return dict(place_type="야생", scene="대상 행렬의 야영지", setting="outdoor",
                    features=["낙타 행렬", "짐 꾸러미", "천막"],
                    description_en="A desert caravan camp with camels, bundles of goods and tents.",
                    text=f"대상 행렬을 따라잡았다. {mood} 물과 먹을 것을 나누거나 함께 이동할 수 있을지 모른다.",
                    effects=[])
    if t == "high_ground":
        return dict(place_type="야생", scene="전파가 잡히는 언덕 위", setting="outdoor",
                    features=["언덕 꼭대기"],
                    description_en="The top of a hill with a wide view over the surrounding land.",
                    text="언덕에 오르자 휴대폰 신호가 안정적으로 잡힌다. 전화를 걸 수 있다(배터리가 남아 있다면).",
                    effects=["can_call"])
    if t == "water":
        return dict(place_type="야생", scene="물가", setting="outdoor",
                    features=["물웅덩이"],
                    description_en="A small pool of water among rocks and plants.",
                    text="물이 고인 곳을 찾았다. 정수하면 마실 수 있다.", effects=[])
    # wildfire
    return dict(place_type="야생", scene="들불이 번지는 언덕", setting="outdoor",
                features=["번지는 들불", "검게 탄 풀밭"],
                description_en="A wildfire spreading across dry grass, thick smoke rising.",
                text="연기의 정체는 사람이 아니라 번지는 들불이었다. 바람이 이쪽으로 분다.", effects=["danger"])
