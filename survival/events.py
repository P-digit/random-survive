"""지형(바이옴) 판별과 지형별 돌발 이벤트."""
import random

# 바이옴: (한글 이름, 이미지 프롬프트용 영어)
BIOMES = {
    "snow":     ("설원", "frozen snowy tundra"),
    "alpine":   ("고산지대", "high rocky alpine mountains"),
    "desert":   ("사막", "arid desert with dunes and rocks"),
    "jungle":   ("열대우림", "dense tropical rainforest"),
    "savanna":  ("초원", "wide open savanna grassland"),
    "forest":   ("온대림", "temperate forest and hills"),
}


# 지형별 환경 위험 (야생에 있을 때만 적용)
#   satiety/hydration/energy : 시간당 소모 배율      walk_speed : 도보 속도(km/h)
#   hitch : 히치하이킹 성공 확률                      village : 도보 이동 후 마을을 발견할 확률
#   extreme : True면 극한 지형 → 이벤트 판정 시 위험 등급이 한 단계 올라간다
BIOME_HAZARDS = {
    "snow":    {"desc": "혹한 — 열량·기력 소모가 크고, 불이나 쉘터 없이 버티면 동사한다",
                "satiety": 1.5, "hydration": 1.0, "energy": 1.3, "walk_speed": 2.5,
                "hitch": 0.25, "village": 0.12, "extreme": True},
    "alpine":  {"desc": "희박한 공기 — 기력이 빠르게 바닥나고, 고도 3,500m 이상에서는 고산병으로 체력이 깎인다",
                "satiety": 1.2, "hydration": 1.2, "energy": 1.6, "walk_speed": 2.5,
                "hitch": 0.25, "village": 0.12, "extreme": True},
    "desert":  {"desc": "건조와 폭염 — 낮에는 수분이 2배로 빠지고, 밤에는 급격히 추워진다",
                "satiety": 1.0, "hydration": 2.0, "energy": 1.2, "walk_speed": 3.0,
                "hitch": 0.25, "village": 0.10, "extreme": True},
    "jungle":  {"desc": "고온다습 — 땀으로 수분·기력이 빠지고, 벌레와 감염으로 체력이 서서히 깎인다",
                "satiety": 1.1, "hydration": 1.4, "energy": 1.3, "walk_speed": 2.5,
                "hitch": 0.30, "village": 0.18, "extreme": True},
    "savanna": {"desc": "건조한 초원 — 그늘이 적어 수분 소모가 조금 크다",
                "satiety": 1.0, "hydration": 1.15, "energy": 1.0, "walk_speed": 4.0,
                "hitch": 0.55, "village": 0.30, "extreme": False},
    "forest":  {"desc": "온화한 숲 — 특별한 환경 위험은 없다",
                "satiety": 1.0, "hydration": 1.0, "energy": 1.0, "walk_speed": 4.0,
                "hitch": 0.60, "village": 0.30, "extreme": False},
}


def classify_biome(latitude, weather, climate=None):
    """지형을 판별한다. 기후대가 있으면 그것을 따르고, 없으면 위도와 날씨로 추정한다.

    단, 지금 실제로 영하의 날씨라면 기후대와 상관없이 설원으로 본다(온대·냉대의 한겨울 등).
    """
    temp, humidity, elevation = weather["temperature"], weather["humidity"], weather["elevation"]
    lat = abs(latitude)
    if climate:
        biome = climate["biome"]
        if temp <= -3 and biome in ("forest", "savanna"):
            return "snow"
        return biome
    if temp <= -3 or lat >= 62:
        return "snow"
    if elevation >= 2500:
        return "alpine"
    if humidity < 35 and temp >= 18:
        return "desert"
    if lat < 15 and humidity >= 65:
        return "jungle"
    if lat < 35:
        return "savanna"
    return "forest"


# kind: danger(위험) / lucky(행운) / neutral(중립)
COMMON_EVENTS = [
    ("lucky", "누군가 버리고 간 배낭을 발견했다."),
    ("lucky", "깨끗해 보이는 물줄기를 발견했다."),
    ("neutral", "멀리서 연기가 피어오르는 것이 보인다."),
    ("neutral", "스마트폰에 아주 약한 신호가 잠깐 잡혔다."),
    ("danger", "발을 헛디뎌 발목을 접질렸다."),
    ("danger", "가지고 있던 물건 하나가 보이지 않는다."),
]

BIOME_EVENTS = {
    "snow": [
        ("danger", "눈보라가 몰아치기 시작했다."),
        ("danger", "손끝의 감각이 없어지고 있다. 동상 초기 증상이다."),
        ("danger", "발밑의 얼음이 갈라지는 소리가 난다."),
        ("lucky", "사냥꾼이 쓰던 빈 오두막을 발견했다."),
        ("neutral", "눈 위에 큰 짐승의 발자국이 나 있다."),
    ],
    "alpine": [
        ("danger", "머리가 깨질 듯 아프다. 고산병 증세다."),
        ("danger", "위쪽에서 돌이 굴러떨어진다."),
        ("danger", "기온이 급격히 떨어지고 있다."),
        ("lucky", "산악인들이 남긴 비상식량 캐시를 발견했다."),
        ("neutral", "양 떼를 모는 목동이 멀리 보인다."),
    ],
    "desert": [
        ("danger", "모래폭풍이 다가오고 있다."),
        ("danger", "전갈이 신발 근처를 기어 다닌다."),
        ("danger", "극심한 더위에 어지럼증이 몰려온다."),
        ("lucky", "야자수가 있는 작은 오아시스가 보인다."),
        ("neutral", "낙타를 끌고 가는 대상 행렬이 지평선에 보인다."),
    ],
    "jungle": [
        ("danger", "독사가 덤불 속에서 고개를 들었다."),
        ("danger", "갑자기 스콜이 쏟아져 온몸이 젖었다."),
        ("danger", "모기떼에 물린 자리가 부어오른다."),
        ("lucky", "잘 익은 야생 과일나무를 발견했다."),
        ("neutral", "강 건너편에 나룻배가 묶여 있다."),
    ],
    "savanna": [
        ("danger", "멀리서 맹수의 울음소리가 들린다."),
        ("danger", "마른 풀밭에 들불이 번지고 있다."),
        ("danger", "마신 물 때문인지 배가 심하게 아프다."),
        ("lucky", "유목민 가족이 손짓하며 부른다."),
        ("neutral", "흙길에 타이어 자국이 선명하게 나 있다."),
    ],
    "forest": [
        ("danger", "야생 멧돼지와 마주쳤다."),
        ("danger", "비에 젖은 몸이 떨린다. 저체온증이 걱정된다."),
        ("danger", "먹음직스러운 버섯을 발견했지만 독버섯일 수도 있다."),
        ("lucky", "등산객이 떨어뜨린 지갑에서 현금을 발견했다."),
        ("neutral", "숲 사이로 오래된 임도가 이어져 있다."),
    ],
}

TOWN_EVENTS = [
    ("danger", "소매치기가 주머니를 노리고 있다."),
    ("danger", "현지 경찰이 신분증을 요구한다."),
    ("danger", "길거리 음식을 먹고 속이 좋지 않다."),
    ("lucky", "한국어를 조금 할 줄 아는 현지인을 만났다."),
    ("lucky", "일당을 주는 짐 나르기 일을 제안받았다."),
    ("lucky", "한국인 여행자가 도와주겠다고 말을 걸어왔다."),
    ("neutral", "시장 한쪽에 환전소와 버스 매표소가 보인다."),
]

# 위험 등급(0 안전, 1 주의, 2 위험)별 이벤트 발생 확률과 '위험 이벤트' 비중
EVENT_CHANCE = {0: 0.20, 1: 0.40, 2: 0.60}
DANGER_SHARE = {0: 0.25, 1: 0.50, 2: 0.75}


def roll_event(biome, place_type, risk_level, rng=random):
    """이번 턴에 일어날 이벤트를 뽑는다. 아무 일도 없으면 None."""
    if rng.random() > EVENT_CHANCE.get(risk_level, 0.3):
        return None
    pool = TOWN_EVENTS if place_type in ("마을", "도시") else BIOME_EVENTS[biome] + COMMON_EVENTS
    want_danger = rng.random() < DANGER_SHARE.get(risk_level, 0.5)
    if want_danger:
        candidates = [e for e in pool if e[0] == "danger"]
    else:
        candidates = [e for e in pool if e[0] != "danger"]
    kind, text = rng.choice(candidates or pool)
    return {"kind": kind, "text": text}


# ---------- 대형 이벤트(기회) ----------
# 플레이어가 받아들이면(accept_offer 툴) 엔진이 결과를 굴려서 직접 적용한다.
# 기회는 항상 좋게 끝나지 않는다: bad["chance"] 확률로 나쁜 결과가 나온다.
#   where: 발생 가능한 장소 유형     extreme_only: 극한 지형의 야생에서만
#   outdoor_only: 실내에 있을 때는 발생하지 않음 (지나가는 차량 등)
#   ride_km: 한국 방향 무료 이동 거리 범위, speed: 이동 속도, dest: 도착지 유형
#   money: 받는 돈 범위($), hours: 걸리는 시간, stats: 수치 변화, items: 얻는 물건
#   risk: 플레이어에게 보여 주는 위험 힌트
#   bad: 나쁜 결과. ride_frac(이동 거리 비율), dest, hours, stats, money(증감),
#        money_frac(약속된 돈 중 받는 비율), lose_money_frac(가진 돈을 잃는 비율), lose_item
MAJOR_EVENTS = [
    {"id": "trucker", "where": ["야생", "마을", "도시"], "outdoor_only": True,
     "text": "장거리 화물 트럭이 속도를 줄이더니 멈춰 선다. 기사가 마침 가는 길이라며 태워 주겠다고 한다.",
     "accept": "트럭에 올라탄다", "ride_km": (200, 500), "speed": 60, "dest": "마을",
     "risk": "낯선 사람의 차다. 어디로 데려갈지는 타 봐야 안다",
     "bad": {"chance": 0.30, "ride_frac": 0.2, "dest": "야생", "lose_money_frac": 0.7,
             "stats": {"health": -10},
             "text": "기사는 인적 없는 곳에 차를 세우더니 돈을 요구했다. 가진 돈 대부분을 빼앗기고 길가에 버려졌다."}},
    {"id": "convoy", "where": ["야생", "마을"], "outdoor_only": True,
     "text": "구호단체 차량 행렬이 당신을 발견하고 멈춘다. 큰 도시의 본부까지 데려다주겠다고 한다.",
     "accept": "구호 차량에 탄다", "ride_km": (300, 700), "speed": 60, "dest": "도시",
     "stats": {"satiety": 30, "hydration": 40},
     "risk": "분쟁 지역을 지나는 길이라 끝까지 간다는 보장은 없다",
     "bad": {"chance": 0.20, "ride_frac": 0.4, "dest": "야생", "hours": 5,
             "text": "행렬은 도중에 무장 검문소에 막혀 되돌아가야 했다. 당신은 허허벌판 중간 지점에 내려야 했다."}},
    {"id": "rescue", "where": ["야생"], "extreme_only": True, "outdoor_only": True,
     "text": "수색 중이던 구조 헬기가 당신을 발견하고 내려온다. 가장 가까운 마을까지 이송해 주겠다고 한다.",
     "accept": "구조 헬기에 탄다", "ride_km": (100, 250), "speed": 200, "dest": "마을",
     "stats": {"health": 30, "satiety": 30, "hydration": 40},
     "risk": "민간 구조대다. 이송 비용을 청구할 수 있다",
     "bad": {"chance": 0.20, "ride_frac": 1.0, "dest": "마을", "lose_money_frac": 0.6,
             "stats": {"health": 30, "satiety": 30, "hydration": 40},
             "text": "무사히 이송되었지만, 착륙하자마자 거액의 구조 비용이 청구되었다. 가진 돈의 절반 이상이 사라졌다."}},
    {"id": "supply", "where": ["야생"], "outdoor_only": True,
     "text": "낙하산이 달린 구호물자 상자가 근처에 떨어져 있다. 봉인은 뜯기지 않았다.",
     "accept": "보급 상자를 연다", "hours": 0.5,
     "stats": {"satiety": 45, "hydration": 45, "energy": 10},
     "items": ["비상식량 2개", "생수 2병", "보온 담요"],
     "risk": "언제 떨어진 상자인지 알 수 없다",
     "bad": {"chance": 0.30, "hours": 3, "stats": {"health": -20, "hydration": -20, "satiety": 10},
             "text": "상자 속 식량은 오래전에 상해 있었다. 허기에 못 이겨 먹고 난 뒤 심한 복통과 구토가 찾아왔다."}},
    {"id": "korean", "where": ["마을", "도시"],
     "text": "이곳에 산다는 한국인이 사정을 듣고 집으로 초대한다. 따뜻한 밥과 잠자리, 여비까지 챙겨 주겠다고 한다.",
     "accept": "초대를 받아들인다", "hours": 10, "money": (40, 90),
     "stats": {"health": 30, "satiety": 70, "hydration": 70, "energy": 70},
     "risk": "처음 보는 사람이다. 호의가 진심인지는 알 수 없다",
     "bad": {"chance": 0.25, "hours": 8, "stats": {"satiety": 30, "energy": 50},
             "lose_money_frac": 0.8, "lose_item": True,
             "text": "아침에 눈을 떠 보니 그 사람도, 당신의 돈도 사라지고 없었다. 교민이 아니라 여행자를 노리는 사기꾼이었다."}},
    {"id": "news", "where": ["마을", "도시"],
     "text": "현지 방송국 기자가 당신의 사연을 취재하고 싶어 한다. 출연료와 시청자 후원금을 약속한다.",
     "accept": "인터뷰에 응한다", "hours": 3, "money": (120, 250),
     "risk": "얼굴이 알려지면 당국의 눈에도 띈다",
     "bad": {"chance": 0.25, "hours": 10, "money": -40, "stats": {"energy": -20},
             "text": "방송이 나간 직후 이민 당국이 찾아왔다. 긴 조사 끝에 벌금을 내고서야 풀려났고, 출연료는 받지 못했다."}},
    {"id": "embassy", "where": ["도시"],
     "text": "대한민국 영사관과 연락이 닿았다. 담당 영사가 긴급 지원금을 전달해 주겠다고 한다.",
     "accept": "영사관의 도움을 받는다", "hours": 4, "money": (150, 300),
     "risk": "서류 절차가 얼마나 걸릴지 모른다",
     "bad": {"chance": 0.20, "hours": 24, "money_frac": 0.3, "stats": {"energy": -10},
             "text": "신원 확인과 서류 절차에 꼬박 하루가 걸렸고, 지원금은 약속된 금액의 일부만 나왔다."}},
    {"id": "cargo", "where": ["도시"], "outdoor_only": True,
     "text": "한국 방향으로 떠나는 화물선의 선장이 일손이 부족하다며, 갑판 일을 도우면 태워 주겠다고 한다.",
     "accept": "화물선에 오른다", "ride_km": (1200, 2500), "speed": 35, "dest": "도시",
     "stats": {"energy": -25, "satiety": 30, "hydration": 30},
     "risk": "먼바다의 날씨와 선상 노동은 만만치 않다",
     "bad": {"chance": 0.30, "ride_frac": 0.4, "dest": "도시", "stats": {"health": -25, "energy": -40},
             "text": "항해 중 폭풍을 만났다. 뱃멀미와 중노동에 몸이 망가졌고, 배는 예정에 한참 못 미친 항구로 피항했다."}},
]


def roll_major_event(place_type, extreme, indoor=False, rng=random):
    """현재 장소·장면에서 일어날 수 있는 대형 이벤트를 하나 뽑아 '제안'으로 만든다. 없으면 None."""
    pool = [e for e in MAJOR_EVENTS
            if place_type in e["where"]
            and (extreme or not e.get("extreme_only"))
            and not (indoor and e.get("outdoor_only"))]
    if not pool:
        return None
    if extreme:   # 극한 지형에서는 구조·보급이 더 잘 나온다
        pool += [e for e in pool if e["id"] in ("rescue", "supply")]
    event = rng.choice(pool)
    offer = {"id": event["id"], "text": event["text"], "accept": event["accept"],
             "hours": event.get("hours", 0), "stats": dict(event.get("stats", {})),
             "items": list(event.get("items", [])), "ride_km": 0, "money": 0,
             "risk": event["risk"], "bad": dict(event["bad"])}
    details = []
    if "ride_km" in event:
        offer["ride_km"] = int(rng.randint(*event["ride_km"]) // 10 * 10)
        offer["speed"], offer["dest"] = event["speed"], event["dest"]
        details.append(f"한국 방향으로 약 {offer['ride_km']:,}km 무료 이동")
    if "money" in event:
        offer["money"] = int(rng.randint(*event["money"]) // 10 * 10)
        details.append(f"${offer['money']} 획득")
    if offer["stats"]:
        details.append("몸 상태 회복" if sum(offer["stats"].values()) > 0 else "기력 소모")
    if offer["items"]:
        details.append("물품: " + ", ".join(offer["items"]))
    offer["detail"] = " · ".join(details)
    return offer
