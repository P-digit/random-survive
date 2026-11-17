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

# 대형 이벤트(기회): 매 턴 발생 확률과, 이 턴 수만큼 안 나오면 반드시 나오게 하는 보정
MAJOR_EVENT_CHANCE = 0.10
MAJOR_EVENT_PITY_TURNS = 8
