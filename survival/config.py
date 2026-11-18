"""프로젝트 전체에서 쓰는 설정값 모음."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
MODEL_DIR = BASE_DIR / "models"      # 학습된 ML 모델 저장 위치
OUTPUT_DIR = BASE_DIR / "outputs"    # 생성된 이미지 저장 위치
CHROMA_DIR = BASE_DIR / "chroma_db"  # RAG용 벡터 DB 저장 위치
SAVE_DIR = BASE_DIR / "saves"        # 자동 저장 파일 위치

# --- OpenAI 모델 (교재에서 사용한 저비용 모델) ---
def read_api_key(raw):
    """환경변수에서 읽은 키를 검사한다. 쓸 수 없는 값이면 None을 돌려준다.

    키에 한글 등 ASCII가 아닌 글자가 있으면(.env.example의 안내 문구를 그대로 둔 경우 등)
    HTTP 헤더로 보낼 수 없어 "'ascii' codec can't encode characters" 오류가 난다.
    """
    key = (raw or "").strip().strip('"').strip("'")
    if not key or not key.isascii() or " " in key or "your-key" in key:
        return None
    return key


OPENAI_API_KEY = read_api_key(os.getenv("OPENAI_API_KEY"))
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")
IMAGE_MODEL = os.getenv("IMAGE_MODEL", "gpt-image-1-mini")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")

# --- 게임 규칙 ---
SEOUL = (37.5665, 126.9780)   # 목적지
ARRIVAL_RADIUS_KM = 60        # 이 거리 안으로 들어오면 귀환 성공
MAX_TOOL_ROUNDS = 5           # 한 턴에 LLM이 툴을 연속 호출할 수 있는 횟수
REDRAW_DISTANCE_KM = 80       # 이만큼 이동하면 장면 이미지를 새로 그림

# 포만감·수분·기력이 줄어드는 속도 배율. 1.0이 원래 속도, 클수록 빨리 줄어든다. (회복 속도에는 영향 없음)
VITALS_DRAIN = 1.6

START_ITEMS = ["물 1L", "에너지바 2개", "라이터", "다용도 칼", "여권", "스마트폰(배터리 30%)"]
START_MONEY = 50  # USD

# 이동 수단별 규칙: 최대 거리(km), 속도(km/h), km당 요금($), 기본요금($), 이용 가능한 장소
TRAVEL_RULES = {
    "walk":      {"label": "도보",       "max_km": 30,    "speed": 4,   "per_km": 0.0,  "base": 0,   "places": ["야생", "마을", "도시"]},
    "hitchhike": {"label": "히치하이킹", "max_km": 250,   "speed": 60,  "per_km": 0.0,  "base": 0,   "places": ["야생", "마을", "도시"]},
    "bus":       {"label": "버스",       "max_km": 600,   "speed": 60,  "per_km": 0.05, "base": 2,   "places": ["마을", "도시"]},
    "train":     {"label": "기차",       "max_km": 1500,  "speed": 110, "per_km": 0.07, "base": 5,   "places": ["도시"]},
    "ship":      {"label": "배",         "max_km": 3000,  "speed": 35,  "per_km": 0.06, "base": 30,  "places": ["도시"]},
    "flight":    {"label": "비행기",     "max_km": 20000, "speed": 800, "per_km": 0.10, "base": 250, "places": ["도시"]},
}
LAND_METHODS = {"walk", "hitchhike", "bus", "train"}

# --- 자유 행동 (시도 판정) ---
# 난이도별 기본 성공 확률. 상태·소지품·상황에 따라 엔진이 보정한다.
ATTEMPT_CHANCE = {"easy": 0.85, "normal": 0.60, "hard": 0.35, "very_hard": 0.15}
# 실패했을 때 몸싸움 등으로 입는 피해(체력)
ATTEMPT_FAIL_DAMAGE = {"easy": 5, "normal": 12, "hard": 20, "very_hard": 30}

# 손에 넣은 탈것: 이름, 속도(km/h), 연료를 가득 채웠을 때 갈 수 있는 거리(km), 바다를 건널 수 있는지
VEHICLES = {
    "car":       {"label": "승용차",   "speed": 70, "range": 550, "sea": False},
    "truck":     {"label": "트럭",     "speed": 60, "range": 750, "sea": False},
    "motorbike": {"label": "오토바이", "speed": 55, "range": 300, "sea": False},
    "boat":      {"label": "보트",     "speed": 25, "range": 350, "sea": True},
}

# 수배도(0~100): 불법 행동을 하면 오르고, 시간이 지나거나 멀리 떠나면 내려간다
# 수배도는 '현실에서 범죄인 행동'을 '누군가 목격했을 때'만 오른다.
WANTED_ON_SUCCESS = 20       # 범죄에 성공했을 때의 기준값
WANTED_ON_FAIL = 35          # 범죄에 실패했을 때의 기준값 (붙잡히거나 얼굴이 알려짐)
# 범죄 종류별 무게 (기준값에 곱한다). 'none'은 범죄가 아님
CRIMES = {"none": 0.0, "무임승차": 0.4, "주거·건물 침입": 0.6, "절도": 0.8, "사기": 0.8, "협박": 0.8,
          "폭행": 1.0, "밀입국·밀항": 1.0, "강도": 1.3, "차량 절도": 1.3}
# 목격자별 무게: 아무도 못 봄 / 피해자만 봄 / 주변 사람들이 봄
WITNESS = {"none": 0.0, "victim": 0.6, "bystanders": 1.0}
WANTED_DECAY_PER_HOUR = 0.3

# 하루 기온 변화 폭(최저~최고의 절반, 도). 예보가 없을 때 이 값으로 낮밤 기온을 만든다
DIURNAL_AMPLITUDE = {"desert": 11, "alpine": 8, "savanna": 7, "snow": 5, "forest": 5, "jungle": 4}
WANTED_AIRPORT_LIMIT = 50    # 이 이상이면 공항·항구 검문에서 붙잡힐 수 있다

# --- 돈 ---
MONEY_GAIN_LIMIT = 600        # 한 번에 얻을 수 있는 돈의 상한(USD). 지갑을 훔치거나 일당을 받는 정도

# --- 초반 제한 ---
# 게임 시작 후 이 시간 동안은 도시·공항·공관으로 갈 수 없다. 낙하 지점 근처(마을까지)에서 버텨야 한다
EARLY_GAME_HOURS = 36
EARLY_MAX_TRAVEL_KM = 60      # 초반에 한 번에 이동할 수 있는 최대 거리

# --- 목적지로 가기 (go_to) ---
JOURNEY_MAX_HOURS = 10        # 한 턴에 이동하는 최대 시간. 더 걸리면 중간에서 멈추고 다음 턴에 이어 간다
# 야생에서 가장 가까운 마을까지의 거리(km) 범위. 극한 지형일수록 멀다
VILLAGE_DISTANCE = {"snow": (25, 70), "desert": (25, 80), "alpine": (15, 45),
                    "jungle": (10, 40), "savanna": (8, 30), "forest": (5, 25)}

# 대형 이벤트(기회): 매 턴 발생 확률과, 이 턴 수만큼 안 나오면 반드시 나오게 하는 보정
MAJOR_EVENT_CHANCE = 0.10
MAJOR_EVENT_PITY_TURNS = 8
