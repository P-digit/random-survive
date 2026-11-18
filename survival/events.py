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


# ---------- 돌발 이벤트 ----------
# 각 이벤트는 '언제, 어디서' 일어날 수 있는지 조건을 가진다. 조건에 맞는 것만 후보가 된다.
#   kind    : danger(위험) / lucky(행운) / neutral(단서·정보)
#   places  : 야생 / 마을 / 도시          biomes  : 지형 (없으면 어디서나)
#   time    : day / night                 weather : rain / snow / storm / fog / clear 중 하나 이상
#   temp    : hot(체감 30도 이상) / cold(체감 0도 이하) / mild
#   indoor  : True면 실내에서만, False(기본)면 야외에서만
#   season  : 봄 / 여름 / 가을 / 겨울 / 우기 / 건기 중 하나 이상
# 사람 생활권에서 먼 야생에서는 동물·자연이, 마을·도시에서는 사람이 이벤트의 중심이 된다.


def E(kind, text, **cond):
    return dict(kind=kind, text=text, **cond)


W = ("야생",)
TOWN = ("마을",)
CITY = ("도시",)
SETTLED = ("마을", "도시")

EVENTS = [
    # ===== 설원 · 툰드라 =====
    E("danger", "굶주린 늑대 무리의 울음소리가 점점 가까워진다.", places=W, biomes=("snow",), time="night"),
    E("danger", "늑대 두 마리가 멀찍이 거리를 두고 당신을 따라오고 있다.", places=W, biomes=("snow", "forest")),
    E("danger", "손끝과 발가락의 감각이 사라지고 있다. 동상 초기 증상이다.", places=W, biomes=("snow", "alpine"), temp="cold"),
    E("danger", "발밑의 얼음이 쩍 하고 갈라지는 소리가 난다.", places=W, biomes=("snow",)),
    E("danger", "눈에 덮인 구덩이에 허리까지 빠졌다. 옷 속으로 눈이 스며든다.", places=W, biomes=("snow",)),
    E("danger", "눈부신 설원의 반사광 때문에 눈이 따갑고 시야가 흐려진다. 설맹 증상이다.",
      places=W, biomes=("snow",), time="day", weather=("clear",)),
    E("danger", "눈보라가 몰아쳐 한 치 앞도 보이지 않는다.", places=W, biomes=("snow", "alpine", "forest"),
      weather=("snow", "storm")),
    E("lucky", "사냥꾼이 쓰던 빈 오두막을 발견했다. 굴뚝이 멀쩡하다.", places=W, biomes=("snow", "forest")),
    E("lucky", "바람을 막아 줄 커다란 바위 틈을 발견했다.", places=W, biomes=("snow", "alpine", "desert")),
    E("lucky", "순록 떼가 일정한 방향으로 이동하고 있다. 유목민의 목초지로 향하는 길일 수 있다.",
      places=W, biomes=("snow",)),
    E("lucky", "구름 한 점 없는 밤하늘에 북극성이 또렷하다. 방향을 잡기 좋다.", places=W, time="night",
      weather=("clear",)),
    E("neutral", "눈 위에 설상차가 지나간 궤도 자국이 길게 나 있다.", places=W, biomes=("snow",)),
    E("neutral", "눈 위에 사람 손바닥보다 큰 곰 발자국이 찍혀 있다. 아직 선명하다.", places=W, biomes=("snow", "forest")),

    # ===== 고산지대 =====
    E("danger", "머리가 깨질 듯 아프고 속이 메스껍다. 고산병 증세다.", places=W, biomes=("alpine",)),
    E("danger", "위쪽 비탈에서 돌이 굴러떨어지기 시작했다.", places=W, biomes=("alpine",)),
    E("danger", "짙은 구름이 산허리를 덮어 길이 보이지 않는다.", places=W, biomes=("alpine",), weather=("fog", "snow", "rain")),
    E("danger", "능선 바로 위로 번개가 내리친다. 높은 곳에 있으면 위험하다.", places=W, biomes=("alpine", "savanna"),
      weather=("storm",)),
    E("danger", "해가 지자 기온이 무섭게 떨어진다. 바람이 뼛속까지 파고든다.", places=W, biomes=("alpine",), time="night"),
    E("danger", "자갈 비탈에서 발이 미끄러졌다.", places=W, biomes=("alpine",)),
    E("lucky", "산악인들이 바위 밑에 숨겨 둔 비상식량 꾸러미를 발견했다.", places=W, biomes=("alpine",)),
    E("lucky", "돌을 쌓아 만든 목동의 움막이 보인다.", places=W, biomes=("alpine",)),
    E("lucky", "만년설이 녹아 흐르는 차가운 개울을 발견했다.", places=W, biomes=("alpine",), time="day"),
    E("neutral", "바위에 돌무더기 표지가 일정한 간격으로 쌓여 있다. 누군가 다니는 길이다.", places=W,
      biomes=("alpine", "desert")),
    E("neutral", "야크 몇 마리가 길을 막고 서서 콧김을 내뿜는다. 근처에 주인이 있을 것이다.", places=W, biomes=("alpine",)),

    # ===== 사막 =====
    E("danger", "지평선에서 누런 모래폭풍이 벽처럼 밀려온다.", places=W, biomes=("desert", "savanna"),
      weather=("clear",)),
    E("danger", "신발 옆으로 전갈이 꼬리를 치켜든 채 기어 다닌다.", places=W, biomes=("desert",), time="night"),
    E("danger", "모래 속에 몸을 숨긴 뿔살모사를 밟을 뻔했다.", places=W, biomes=("desert",)),
    E("danger", "극심한 더위에 어지럼증과 구역질이 몰려온다. 열사병 직전이다.", places=W,
      biomes=("desert", "savanna"), time="day", temp="hot"),
    E("danger", "멀리 반짝이는 호수를 향해 한참을 걸었지만 신기루였다.", places=W, biomes=("desert",), time="day"),
    E("danger", "해가 지자 사막의 열기가 순식간에 사라지고 한기가 몰려온다.", places=W, biomes=("desert",), time="night"),
    E("danger", "비가 내리자 마른 강바닥(와디)에 흙탕물이 무섭게 불어나기 시작했다.", places=W,
      biomes=("desert", "savanna"), weather=("rain", "storm")),
    E("lucky", "야자수가 몇 그루 서 있는 작은 오아시스가 보인다.", places=W, biomes=("desert",)),
    E("lucky", "바위의 움푹한 곳에 빗물이 고여 있다.", places=W, biomes=("desert", "savanna", "alpine"),
      weather=("rain", "storm")),
    E("lucky", "가시덤불 아래 그늘에서 잠시 숨을 돌릴 수 있는 곳을 찾았다.", places=W, biomes=("desert",), time="day"),
    E("neutral", "낙타를 끌고 가는 대상 행렬이 지평선에 보인다.", places=W, biomes=("desert",), time="day"),
    E("neutral", "모래 위에 낙타 발자국과 바퀴 자국이 한 방향으로 이어져 있다.", places=W, biomes=("desert",)),

    # ===== 열대우림 =====
    E("danger", "덤불 속에서 독사가 고개를 들고 혀를 날름거린다.", places=W, biomes=("jungle", "savanna")),
    E("danger", "갑자기 스콜이 쏟아져 온몸이 흠뻑 젖었다.", places=W, biomes=("jungle",), weather=("rain", "storm")),
    E("danger", "모기떼가 구름처럼 달려든다. 물린 자리가 부어오른다.", places=W, biomes=("jungle",)),
    E("danger", "다리에 거머리 여러 마리가 달라붙어 있다.", places=W, biomes=("jungle",), weather=("rain", "storm", "fog")),
    E("danger", "발을 디딘 곳이 불개미 집이었다. 다리가 불타는 듯 따갑다.", places=W, biomes=("jungle", "savanna")),
    E("danger", "어둠 속에서 큰 고양잇과 짐승의 낮은 울음소리가 들린다.", places=W, biomes=("jungle",), time="night"),
    E("danger", "비에 불어난 강물이 흙탕물이 되어 거세게 흐른다. 건너기 어렵다.", places=W,
      biomes=("jungle", "forest"), weather=("rain", "storm")),
    E("danger", "썩은 거목이 굉음을 내며 바로 옆으로 쓰러졌다.", places=W, biomes=("jungle", "forest"),
      weather=("storm", "rain")),
    E("lucky", "잘 익은 야생 바나나 군락을 발견했다.", places=W, biomes=("jungle",)),
    E("lucky", "굵은 덩굴을 자르면 마실 수 있는 물이 흘러나온다는 것을 기억해 냈다.", places=W, biomes=("jungle",)),
    E("lucky", "강가에 주인 없는 나룻배가 묶여 있다.", places=W, biomes=("jungle", "forest")),
    E("neutral", "원숭이 무리가 나무 위에서 시끄럽게 경고음을 낸다. 근처에 무언가 있다.", places=W, biomes=("jungle",)),
    E("neutral", "강물에 플라스틱 병이 떠내려온다. 상류에 사람이 산다.", places=W, biomes=("jungle", "forest", "savanna")),
    E("neutral", "멀리서 전기톱 소리가 들린다. 벌목꾼이 있는 것 같다.", places=W, biomes=("jungle", "forest"), time="day"),

    # ===== 사바나 · 초원 =====
    E("danger", "멀리서 사자의 포효가 들린다. 생각보다 가깝다.", places=W, biomes=("savanna",), time="night"),
    E("danger", "풀숲 사이로 하이에나 무리가 어슬렁거린다.", places=W, biomes=("savanna", "desert"), time="night"),
    E("danger", "마른 풀밭에 들불이 번지며 바람을 타고 다가온다.", places=W, biomes=("savanna",),
      weather=("clear",), temp="hot"),
    E("danger", "물소 한 마리가 고개를 숙이고 당신 쪽을 노려본다.", places=W, biomes=("savanna",)),
    E("danger", "코끼리 떼가 새끼를 데리고 길목을 지나간다. 가까이 가면 위험하다.", places=W, biomes=("savanna",), time="day"),
    E("danger", "흙탕물 웅덩이의 물을 마신 뒤 배가 뒤틀리듯 아프다.", places=W, biomes=("savanna", "jungle")),
    E("lucky", "유목민 가족이 멀리서 손짓하며 부른다.", places=W, biomes=("savanna", "desert", "alpine"), time="day"),
    E("lucky", "동물들이 모여드는 물웅덩이를 찾았다.", places=W, biomes=("savanna",)),
    E("lucky", "거대한 바오밥나무 아래 그늘이 넓다.", places=W, biomes=("savanna",), time="day"),
    E("neutral", "독수리 떼가 한곳을 맴돌고 있다. 그 아래 사체가 있고, 맹수도 있을지 모른다.", places=W,
      biomes=("savanna", "desert"), time="day"),
    E("neutral", "흙길에 타이어 자국이 선명하게 나 있다.", places=W, biomes=("savanna", "desert", "forest")),

    # ===== 온대림 · 냉대림 =====
    E("danger", "새끼를 데린 멧돼지와 정면으로 마주쳤다.", places=W, biomes=("forest",)),
    E("danger", "덤불 너머에서 곰이 일어서서 냄새를 맡고 있다.", places=W, biomes=("forest",), season=("봄", "여름", "가을")),
    E("danger", "먹음직스러운 버섯 군락을 발견했지만 독버섯일 수도 있다.", places=W, biomes=("forest", "jungle"),
      season=("여름", "가을", "우기")),
    E("danger", "비에 젖은 몸이 떨리기 시작한다. 저체온증이 걱정된다.", places=W, weather=("rain", "storm"), temp="cold"),
    E("danger", "비에 젖은 몸이 식으며 한기가 든다.", places=W, biomes=("forest", "alpine"), weather=("rain",), temp="mild"),
    E("danger", "다리에 진드기가 여러 마리 붙어 있다.", places=W, biomes=("forest", "savanna"), season=("봄", "여름")),
    E("danger", "날이 저물어 나무와 나무가 구별되지 않는다. 길을 잃기 쉽다.", places=W, biomes=("forest", "jungle"),
      time="night"),
    E("danger", "낙엽에 덮인 비탈에서 미끄러져 굴렀다.", places=W, biomes=("forest",)),
    E("lucky", "산딸기 덤불이 열매를 잔뜩 달고 있다.", places=W, biomes=("forest",), season=("여름",)),
    E("lucky", "땅에 떨어진 밤과 도토리가 수북하다.", places=W, biomes=("forest",), season=("가을",)),
    E("lucky", "등산객이 떨어뜨린 지갑에서 현금을 발견했다.", places=W, biomes=("forest", "alpine")),
    E("lucky", "맑은 물이 흐르는 계곡을 발견했다.", places=W, biomes=("forest", "jungle")),
    E("neutral", "숲 사이로 오래된 임도가 이어져 있다.", places=W, biomes=("forest",)),

    # ===== 야생 공통 =====
    E("lucky", "누군가 버리고 간 배낭을 발견했다.", places=W),
    E("lucky", "빗물을 받아 둘 수 있겠다.", places=W, weather=("rain",)),
    E("neutral", "멀리서 연기가 가늘게 피어오른다.", places=W, time="day"),
    E("neutral", "어둠 너머 멀리에서 희미한 불빛 하나가 깜빡인다.", places=W, time="night"),
    E("neutral", "스마트폰에 아주 약한 신호가 잠깐 잡혔다.", places=W),
    E("danger", "발을 헛디뎌 발목을 접질렸다.", places=W),
    E("danger", "어둠 속에서 돌부리에 걸려 넘어졌다.", places=W, time="night"),
    E("danger", "짙은 안개가 내려앉아 방향을 잃었다.", places=W, weather=("fog",)),
    E("danger", "가까운 곳에 벼락이 떨어졌다. 귀가 먹먹하다.", places=W, weather=("storm",)),

    # ===== 마을 =====
    E("danger", "사나운 개 떼가 이를 드러내며 짖어 댄다.", places=TOWN),
    E("danger", "마을 사람들이 낯선 당신을 경계하며 마을을 떠나라고 손짓한다.", places=TOWN),
    E("danger", "우물물이 탁하다. 마신 뒤 속이 좋지 않다.", places=TOWN),
    E("danger", "술에 취한 남자가 시비를 걸어온다.", places=SETTLED, time="night"),
    E("danger", "손전등을 든 마을 자경단이 당신을 불러 세운다.", places=TOWN, time="night"),
    E("lucky", "밭일을 도와주면 먹을 것과 잠자리를 주겠다는 농부를 만났다.", places=TOWN, time="day"),
    E("lucky", "노부부가 집 앞에서 따뜻한 음식을 나눠 주겠다고 한다.", places=TOWN),
    E("lucky", "오늘은 장날이다. 물건을 사고팔 수 있다.", places=TOWN, time="day"),
    E("lucky", "처마 밑에서 함께 비를 피하던 주민이 큰 도시로 가는 길을 알려 준다.", places=TOWN, weather=("rain", "storm")),
    E("neutral", "정류장 기둥에 낡은 버스 시간표가 붙어 있다.", places=TOWN, time="day"),
    E("neutral", "짐을 가득 실은 트럭이 장터에서 출발 준비를 하고 있다.", places=TOWN, time="day"),

    # ===== 도시 =====
    E("danger", "붐비는 시장에서 누군가 주머니를 더듬는다. 소매치기다.", places=CITY, time="day"),
    E("danger", "오토바이를 탄 날치기가 가방을 노리고 다가온다.", places=CITY, time="day"),
    E("danger", "어두운 뒷골목에서 두 남자가 길을 막아선다.", places=CITY, time="night"),
    E("danger", "현지 경찰이 신분증을 보여 달라고 한다.", places=SETTLED),
    E("danger", "길거리 음식을 먹고 속이 뒤틀린다.", places=CITY),
    E("danger", "택시 기사가 터무니없는 요금을 부르며 내리지 못하게 한다.", places=CITY),
    E("danger", "시위 행렬이 거리를 메우고 경찰과 대치하고 있다.", places=CITY, time="day"),
    E("danger", "노숙하려던 자리에서 경비원이 거칠게 쫓아낸다.", places=CITY, time="night"),
    E("lucky", "한국인 여행자가 한국어를 듣고 반갑게 말을 걸어왔다.", places=CITY),
    E("lucky", "골목 끝에 한글 간판의 한국 식당이 보인다.", places=CITY),
    E("lucky", "무료 와이파이가 되는 카페를 찾았다. 스마트폰을 충전할 수 있을지도 모른다.", places=CITY),
    E("lucky", "항구에서 짐 나르기 일당을 준다는 사람이 있다.", places=CITY, time="day"),
    E("lucky", "교회 앞에서 무료 급식을 나눠 주고 있다.", places=CITY),
    E("neutral", "환전소와 장거리 버스 매표소가 나란히 있다.", places=CITY, time="day"),
    E("neutral", "벽에 공항행 셔틀버스 광고가 붙어 있다.", places=CITY),

    # ===== 실내 (야생의 오두막·동굴) =====
    E("danger", "쌓인 눈 무게에 오두막 지붕이 삐걱거리며 내려앉기 시작한다.", places=W, indoor=True,
      weather=("snow", "storm")),
    E("danger", "동굴 안쪽 어둠에서 짐승의 냄새와 거친 숨소리가 난다.", places=W, indoor=True),
    E("danger", "피워 둔 불의 연기가 빠지지 않아 숨이 막힌다.", places=W, indoor=True),
    E("danger", "쥐가 배낭을 뚫고 먹을 것을 갉아 먹었다.", places=W + SETTLED, indoor=True, time="night"),
    E("lucky", "선반 구석에서 유통기한이 지나지 않은 통조림을 찾았다.", places=W, indoor=True),
    E("lucky", "벽에 이 일대의 낡은 지도가 걸려 있다.", places=W + TOWN, indoor=True),
    E("lucky", "구석에 두꺼운 모포가 개켜져 있다.", places=W, indoor=True, temp="cold"),
    # ===== 실내 (마을·도시의 건물) =====
    E("danger", "주인이 의심스러운 눈으로 보더니 당장 나가라고 소리친다.", places=SETTLED, indoor=True),
    E("lucky", "주인이 말없이 따뜻한 차 한 잔을 내준다.", places=SETTLED, indoor=True, temp="cold"),
    E("lucky", "벽 게시판에 '일손 구함' 쪽지가 붙어 있다.", places=SETTLED, indoor=True),
    E("neutral", "TV 뉴스에서 이 지역의 도로 통제 소식이 나온다.", places=SETTLED, indoor=True),
]

# ---------- 긍정 이벤트 보강 ----------
# 모두 물·식량·체온·휴식·길 찾기·돈·이동 중 하나에 실제로 도움이 되는 것들이다.
EVENTS += [
    # ===== 설원 =====
    E("lucky", "얼음 위에 낚시꾼이 뚫어 놓은 구멍과 버려진 낚싯줄이 있다. 물고기를 잡을 수 있겠다.",
      places=W, biomes=("snow",), time="day"),
    E("lucky", "바람에 눈이 단단히 다져진 언덕이 있다. 눈굴을 파기에 좋다.", places=W, biomes=("snow",)),
    E("lucky", "말라 죽은 관목이 눈 위로 삐죽 나와 있다. 불쏘시개로 쓸 수 있다.", places=W, biomes=("snow", "alpine")),
    E("lucky", "멀리서 개 썰매 방울 소리가 들린다.", places=W, biomes=("snow",), time="day"),
    E("lucky", "흐린 하늘이 걷히자 해가 낮게 떠 남쪽 방향이 분명해졌다.", places=W, biomes=("snow", "alpine", "forest"),
      time="day", weather=("clear",)),

    # ===== 고산 =====
    E("lucky", "바람이 닿지 않는 양지바른 바위 아래가 따뜻하다. 몸을 녹이며 쉴 수 있다.",
      places=W, biomes=("alpine",), time="day"),
    E("lucky", "능선 위에서 계곡 아래 마을의 지붕들이 내려다보인다.", places=W, biomes=("alpine",), time="day",
      weather=("clear",)),
    E("lucky", "누군가 바위에 붉은 페인트로 길 표시를 해 두었다. 하산로다.", places=W, biomes=("alpine",)),
    E("lucky", "어둠 속 아래쪽 계곡에 마을 불빛이 몇 개 반짝인다. 방향을 잡을 수 있다.",
      places=W, biomes=("alpine", "forest", "desert", "savanna"), time="night", weather=("clear",)),

    # ===== 사막 =====
    E("lucky", "새벽 냉기에 바위와 천 위에 이슬이 맺혔다. 천으로 훔쳐 짜면 마실 물이 된다.",
      places=W, biomes=("desert", "savanna"), time="night"),
    E("lucky", "모래에 반쯤 묻힌 플라스틱 물통을 찾았다. 안에 물이 조금 남아 있다.", places=W, biomes=("desert",)),
    E("lucky", "선인장처럼 물을 머금은 다육식물 군락이 있다.", places=W, biomes=("desert",)),
    E("lucky", "멀리 송전탑이 일렬로 서 있다.", places=W, biomes=("desert", "savanna", "snow")),
    E("lucky", "모래 위에 덤불 그림자가 길게 드리워 방향을 읽을 수 있다.", places=W, biomes=("desert",), time="day"),
    E("lucky", "해가 지자 열기가 가셔 걷기 좋은 시간이 되었다. 밤하늘 별이 길잡이가 된다.",
      places=W, biomes=("desert",), time="night", weather=("clear",)),

    # ===== 열대우림 =====
    E("lucky", "커다란 잎이 우산처럼 겹친 곳 아래로 빗물이 줄줄 흘러내린다. 받아 마시기 좋다.",
      places=W, biomes=("jungle",), weather=("rain", "storm")),
    E("lucky", "코코넛이 달린 야자나무가 있다. 과즙과 과육을 얻을 수 있다.", places=W, biomes=("jungle", "savanna")),
    E("lucky", "강가에 반쯤 물에 잠긴 통나무들이 있다. 엮으면 뗏목이 된다.", places=W, biomes=("jungle", "forest")),
    E("lucky", "칼로 낸 표시가 나무줄기마다 이어져 있다. 원주민이나 채집꾼의 길이다.", places=W, biomes=("jungle",)),
    E("lucky", "강물 소리가 들린다. 하류로 가면 사람 사는 곳이 나올 가능성이 크다.",
      places=W, biomes=("jungle", "forest", "alpine")),

    # ===== 사바나 =====
    E("lucky", "개코원숭이 무리가 땅을 파헤치는 곳을 보니 얕게 고인 지하수가 있다.", places=W, biomes=("savanna",), time="day"),
    E("lucky", "모닥불 흔적과 아직 따뜻한 재가 남아 있다. 사람이 막 떠난 자리다.", places=W, biomes=("savanna", "desert", "forest")),
    E("lucky", "가시나무로 둥글게 울타리를 친 빈 가축우리가 있다. 맹수를 피해 밤을 보내기 좋다.",
      places=W, biomes=("savanna",), time="night"),
    E("lucky", "멀리 목동이 모는 소 떼의 방울 소리가 들린다. 아침이면 마을로 돌아갈 것이다.",
      places=W, biomes=("savanna",), time="night"),
    E("lucky", "마른 소똥이 넓게 흩어져 있다. 잘 타는 연료가 된다.", places=W, biomes=("savanna", "alpine", "desert")),

    # ===== 숲 =====
    E("lucky", "덫에 걸린 토끼가 있다. 누군가 놓아둔 올무다.", places=W, biomes=("forest", "snow")),
    E("lucky", "자작나무 껍질이 잔뜩 벗겨져 있다. 젖어도 불이 잘 붙는 불쏘시개다.", places=W, biomes=("forest", "snow")),
    E("lucky", "벌목꾼들이 쓰던 임시 천막이 비어 있다. 비를 피할 수 있다.", places=W, biomes=("forest", "jungle"),
      weather=("rain", "storm")),
    E("lucky", "쓰러진 나무 밑동이 바람을 막아 주는 아늑한 자리를 만들었다.", places=W, biomes=("forest",), time="night"),
    E("lucky", "개울에 송어가 그림자처럼 머물러 있다. 손으로도 잡을 수 있을 것 같다.",
      places=W, biomes=("forest", "alpine"), season=("봄", "여름", "가을")),

    # ===== 야생 공통 =====
    E("lucky", "밤새 내린 비로 바위 웅덩이마다 깨끗한 물이 찰랑거린다.", places=W, weather=("rain",), time="day"),
    E("lucky", "멀리서 엔진 소리가 들린다. 바람을 타고 끊겼다 이어지기를 반복한다.", places=W, time="day"),
    E("lucky", "바람이 잦아들고 하늘이 맑게 갰다. 오늘은 멀리까지 걸을 수 있겠다.", places=W, weather=("clear",), temp="mild"),

    # ===== 마을 (낮) =====
    E("lucky", "마을 사람이 당신의 사정을 듣고 이웃 마을까지 가는 오토바이를 태워 주겠다고 한다.",
      places=TOWN, time="day"),
    E("lucky", "집집마다 돌아다니며 물을 나르는 아이들이 마을 공동 우물 위치를 알려 준다.", places=TOWN, time="day"),
    E("lucky", "가지고 있는 물건을 먹을 것과 바꾸자는 상인이 있다.", places=TOWN),
    E("lucky", "마을 진료소가 문을 열었다. 간단한 치료를 받을 수 있다.", places=TOWN, time="day"),
    # ===== 마을 (밤) =====
    E("lucky", "늦게까지 불이 켜진 집에서 노인이 손짓하며 들어와 몸을 녹이라고 한다.", places=TOWN, time="night"),
    E("lucky", "마을 사원(교회·모스크)의 문이 열려 있다. 나그네가 하룻밤 머무는 것을 허락하는 곳이다.",
      places=TOWN, time="night"),
    E("lucky", "밤늦게 들어온 화물차 기사가 내일 새벽 큰 도시로 떠난다며 자리가 있다고 한다.",
      places=TOWN, time="night"),
    E("lucky", "모닥불가에 모인 마을 사람들이 남은 음식을 나눠 준다.", places=TOWN, time="night"),

    # ===== 도시 =====
    E("lucky", "광장에 무료 공공 충전대가 있다. 스마트폰을 충전하면 가족에게 연락할 수 있을지 모른다.",
      places=CITY),
    E("lucky", "광장 한쪽에서 관광객 안내소가 무료 지도와 대사관 위치를 알려 준다.", places=CITY, time="day"),
    E("lucky", "식당 주인이 설거지를 도와주면 한 끼와 약간의 돈을 주겠다고 한다.", places=CITY),
    E("lucky", "24시간 여는 기차역 대합실은 밤새 따뜻하고 경비가 있어 비교적 안전하다.", places=CITY, time="night"),
    E("lucky", "야시장 상인이 문 닫기 전 남은 음식을 헐값에 판다.", places=CITY, time="night"),
    E("lucky", "중고 물건 가게에서 쓸 만한 물건을 사 주겠다고 한다.", places=CITY, time="day"),

    # ===== 야생의 실내 (오두막·동굴) =====
    E("lucky", "난로 옆에 마른 장작이 한 아름 쌓여 있다.", places=W, indoor=True),
    E("lucky", "구석에서 녹슬었지만 쓸 만한 냄비를 찾았다. 물을 끓일 수 있다.", places=W, indoor=True),
    E("lucky", "지붕 홈통 아래 빗물받이 통에 물이 가득하다.", places=W, indoor=True, weather=("rain", "storm")),
    E("lucky", "벽에 이전에 머문 사람이 남긴 메모가 있다. 가장 가까운 마을까지의 방향과 거리가 적혀 있다.",
      places=W, indoor=True),
    E("lucky", "바람과 눈을 완전히 막아 주는 깊고 마른 공간이다. 오랜만에 깊이 잘 수 있겠다.",
      places=W, indoor=True, time="night"),
    E("lucky", "선반 위 상자에 붕대와 소독약이 남아 있다.", places=W + TOWN, indoor=True),
    # ===== 마을·도시의 실내 =====
    E("lucky", "가게 주인이 휴대폰 충전을 해 주겠다고 한다.", places=SETTLED, indoor=True, time="day"),
    E("lucky", "숙소 주인이 일을 도우면 숙박비를 받지 않겠다고 한다.", places=SETTLED, indoor=True),
    E("lucky", "식당 TV에서 한국 대사관의 해외 조난자 지원 안내가 나온다. 연락처를 받아 적었다.",
      places=SETTLED, indoor=True),
    E("lucky", "옆자리 트럭 기사가 내일 아침 당신이 가려는 방향으로 간다고 말한다.", places=SETTLED, indoor=True),
    E("lucky", "주인이 남은 수프를 데워 내준다.", places=SETTLED, indoor=True, time="night"),
]

# ---------- 단서가 되는 이벤트 ----------
# 이 이벤트들은 '무언가가 저쪽에 있다'는 단서다. 이벤트가 일어나면 엔진이 그 정체·방향·거리를 정해 두고(leads.py),
# 플레이어가 따라가면 반드시 그것이 나타난다. (앞의 것이 먼저 맞으면 그것을 쓴다)
LEAD_HINTS = [
    ("마을 불빛", "settlement"), ("마을의 지붕", "settlement"), ("엔진 소리", "engine"),
    ("설상차", "tracks"), ("타이어 자국", "tracks"), ("바퀴 자국", "tracks"), ("연기가 가늘게", "smoke"),
    ("모닥불 흔적", "trail"), ("불빛", "light"), ("송전탑", "power"), ("강물 소리", "river"),
    ("플라스틱 병", "river"), ("돌무더기 표지", "trail"), ("붉은 페인트", "trail"), ("칼로 낸 표시", "trail"),
    ("임도", "trail"), ("메모가 있다", "trail"), ("낡은 지도", "trail"), ("개 썰매", "herd"),
    ("방울 소리", "herd"), ("순록 떼", "herd"), ("야크", "herd"), ("목동의 움막", "herd"),
    ("손짓하며 부른다", "herd"), ("전기톱", "chainsaw"), ("대상 행렬", "caravan"),
    ("아주 약한 신호", "signal"), ("개코원숭이", "water"),
]
for _event in EVENTS:
    for _hint, _kind in LEAD_HINTS:
        if _hint in _event["text"] and "야생" in _event.get("places", W):
            _event["lead"] = _kind
            break

# 위험 등급(0 안전, 1 주의, 2 위험)별 이벤트 발생 확률과 '위험 이벤트' 비중
EVENT_CHANCE = {0: 0.20, 1: 0.40, 2: 0.60}
DANGER_SHARE = {0: 0.25, 1: 0.50, 2: 0.75}


def matches(event, place_type, biome, context):
    """이벤트의 조건이 지금 상황과 맞는지."""
    c = context or {}
    if place_type not in event.get("places", W):
        return False
    if event.get("biomes") and biome not in event["biomes"]:
        return False
    if bool(event.get("indoor", False)) != bool(c.get("indoor", False)):
        return False
    if "time" in event and event["time"] != ("night" if c.get("night") else "day"):
        return False
    if "weather" in event and c.get("weather", "clear") not in event["weather"]:
        return False
    if "temp" in event:
        feels = c.get("temp", 15)
        band = "hot" if feels >= 30 else ("cold" if feels <= 0 else "mild")
        if event["temp"] != band:
            return False
    if "season" in event and c.get("season") and c["season"] not in event["season"]:
        return False
    return True


def candidates(place_type, biome, context=None):
    return [e for e in EVENTS if matches(e, place_type, biome, context)]


def roll_event(biome, place_type, risk_level, rng=random, context=None):
    """이번 턴에 일어날 이벤트를 지금 상황(장소·지형·시간·날씨·기온·실내외·계절)에 맞게 뽑는다.

    날씨·시간처럼 구체적인 조건이 붙은 이벤트일수록 지금 상황을 잘 드러내므로 더 잘 뽑힌다.
    아무 일도 없으면 None.
    """
    if rng.random() > EVENT_CHANCE.get(risk_level, 0.3):
        return None
    pool = candidates(place_type, biome, context)
    if not pool:
        return None
    want_danger = rng.random() < DANGER_SHARE.get(risk_level, 0.5)
    chosen = [e for e in pool if (e["kind"] == "danger") == want_danger] or pool
    weights = [1 + sum(k in e for k in ("time", "weather", "temp", "season")) * 1.5 for e in chosen]
    event = rng.choices(chosen, weights=weights, k=1)[0]
    result = {"kind": event["kind"], "text": event["text"]}
    if event.get("lead") and place_type == "야생":
        result["lead"] = event["lead"]
    return result


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
     "text": "장거리 화물 트럭이 속도를 줄이더니 멈춰 선다. 기사는 {dest}까지 간다며 태워 주겠다고 한다.",
     "accept": "트럭에 올라탄다", "move": {"to": "city_or_village", "max_km": 500, "speed": 60},
     "risk": "낯선 사람의 차다. 정말 그곳으로 데려갈지는 타 봐야 안다",
     "bad": {"chance": 0.30, "ride_frac": 0.2, "dest": "야생", "lose_money_frac": 0.7,
             "stats": {"health": -10},
             "text": "기사는 인적 없는 곳에 차를 세우더니 돈을 요구했다. 가진 돈 대부분을 빼앗기고 길가에 버려졌다."}},
    {"id": "convoy", "where": ["야생", "마을"], "outdoor_only": True,
     "text": "구호단체 차량 행렬이 당신을 발견하고 멈춘다. {dest}에 있는 본부까지 데려다주겠다고 한다.",
     "accept": "구호 차량에 탄다", "move": {"to": "city_or_village", "max_km": 700, "speed": 55},
     "stats": {"satiety": 30, "hydration": 40},
     "risk": "치안이 불안한 길을 지난다. 끝까지 간다는 보장은 없다",
     "bad": {"chance": 0.20, "ride_frac": 0.4, "dest": "야생", "hours": 5,
             "text": "행렬은 도중에 무장 검문소에 막혀 되돌아가야 했다. 당신은 허허벌판 중간 지점에 내려야 했다."}},
    {"id": "rescue", "where": ["야생"], "extreme_only": True, "outdoor_only": True,
     "text": "수색 중이던 구조 헬기가 당신을 발견하고 내려온다. {dest}까지 이송해 주겠다고 한다.",
     "accept": "구조 헬기에 탄다", "move": {"to": "rescue", "max_km": 300, "speed": 200},
     "stats": {"health": 30, "satiety": 30, "hydration": 40},
     "risk": "민간 구조대다. 이송 비용을 청구할 수 있다",
     "bad": {"chance": 0.20, "ride_frac": 1.0, "lose_money_frac": 0.6,
             "stats": {"health": 30, "satiety": 30, "hydration": 40},
             "text": "무사히 이송되었지만, 내리자마자 거액의 구조 비용이 청구되었다. 가진 돈의 절반 이상이 사라졌다."}},
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
    {"id": "embassy", "where": ["마을", "도시"], "needs": "contact",
     "text": "{dest} 영사과와 연락이 닿았다. 담당 영사가 그곳까지 오는 교통편을 마련해 주고, 도착하면 "
             "여행증명서와 긴급 지원금을 주겠다고 한다.",
     "accept": "공관으로 간다", "move": {"to": "embassy", "max_km": 3500, "speed": 250},
     "money": (150, 300), "items": ["여행증명서"],
     "risk": "서류 절차가 얼마나 걸릴지 모른다",
     "bad": {"chance": 0.20, "ride_frac": 1.0, "hours": 24, "money_frac": 0.3, "stats": {"energy": -10},
             "text": "공관에는 도착했지만 신원 확인과 서류 절차에 꼬박 하루가 걸렸고, 지원금은 약속된 금액의 일부만 나왔다."}},
    {"id": "airport", "where": ["도시"], "needs": "airport",
     "text": "{dest} 국제공항으로 가는 차편이 생겼다. 공항까지 데려다주겠다고 한다.",
     "accept": "공항으로 간다", "move": {"to": "airport", "max_km": 400, "speed": 70},
     "risk": "공항까지 가는 길에 무슨 일이 생길지 모른다",
     "bad": {"chance": 0.20, "ride_frac": 1.0, "lose_money_frac": 0.3,
             "text": "공항에는 도착했지만, 차에서 내리는 사이 지갑에서 돈 일부가 사라졌다."}},
    {"id": "cargo", "where": ["도시"], "outdoor_only": True,
     "text": "한국 쪽으로 가는 화물선의 선장이 일손이 부족하다며, 갑판 일을 도우면 {dest}까지 태워 주겠다고 한다.",
     "accept": "화물선에 오른다", "move": {"to": "port_toward_korea", "max_km": 2500, "speed": 35},
     "stats": {"energy": -25, "satiety": 30, "hydration": 30},
     "risk": "먼바다의 날씨와 선상 노동은 만만치 않다",
     "bad": {"chance": 0.30, "ride_frac": 0.4, "dest": "도시", "stats": {"health": -25, "energy": -40},
             "text": "항해 중 폭풍을 만났다. 뱃멀미와 중노동에 몸이 망가졌고, 배는 예정에 한참 못 미친 항구로 피항했다."}},
]


# 기회가 사라질 때: 무엇이 떠나는지, 장면에서 지울 것(한국어 '보이는 것'과 그림 묘사의 영어 낱말)
OFFER_EXIT = {
    "trucker": ("트럭 기사는 더 기다리지 않고 트럭을 몰고 떠났다.", ("트럭", "화물차", "기사"), ("truck", "lorry")),
    "convoy": ("구호 차량 행렬은 다시 출발해 멀어졌다.", ("구호", "차량", "행렬"), ("convoy", "vehicle", "jeep", "truck")),
    "rescue": ("구조 헬기는 다시 날아올라 멀어졌다.", ("헬기", "헬리콥터", "구조대"), ("helicopter",)),
    "korean": ("초대했던 사람은 아쉬워하며 돌아갔다.", ("한국인",), ()),
    "news": ("기자는 다른 취재를 하러 떠났다.", ("기자", "카메라"), ("reporter", "camera")),
    "cargo": ("화물선은 당신을 기다리지 않고 출항했다.", ("화물선", "선장"), ("ship", "freighter", "vessel")),
    "embassy": ("공관과의 연락이 끊겼다.", (), ()),
    "airport": ("공항으로 가는 차편은 떠났다.", (), ()),
}
# 사람이 아니라 놓여 있는 물건이라 떠나지 않는 기회 (그곳을 떠날 때까지 남는다)
PERSISTENT_OFFERS = ("supply",)


def roll_major_event(place_type, extreme, indoor=False, rng=random, allowed_needs=()):
    """현재 장소·장면에서 일어날 수 있는 대형 이벤트를 하나 뽑아 '제안'으로 만든다. 없으면 None.

    목적지({dest})는 아직 정하지 않는다. 게임 상태(위치, 가까운 도시)가 필요하므로 state 가 정한다.
    allowed_needs: 조건이 붙은 이벤트 중 지금 허용되는 것 ('contact': 공관과 연락 가능, 'airport': 공항 허용)
    """
    pool = [e for e in MAJOR_EVENTS
            if place_type in e["where"]
            and (extreme or not e.get("extreme_only"))
            and not (indoor and e.get("outdoor_only"))
            and (not e.get("needs") or e["needs"] in allowed_needs)]
    if not pool:
        return None
    if extreme:   # 극한 지형에서는 구조·보급이 더 잘 나온다
        pool += [e for e in pool if e["id"] in ("rescue", "supply")]
    if allowed_needs:   # 귀환에 결정적인 기회(공관·공항)는 조건이 되면 더 잘 나온다
        pool += [e for e in pool if e.get("needs")] * 2
    event = rng.choice(pool)
    offer = {"id": event["id"], "text": event["text"], "accept": event["accept"],
             "hours": event.get("hours", 0), "stats": dict(event.get("stats", {})),
             "items": list(event.get("items", [])), "money": 0,
             "risk": event["risk"], "bad": dict(event["bad"]), "move": dict(event.get("move", {}))}
    if "money" in event:
        offer["money"] = int(rng.randint(*event["money"]) // 10 * 10)
    return offer
