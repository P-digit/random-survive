"""자동 저장과 이어하기. 진행 중인 게임 하나를 saves/autosave.json 에 보관한다."""
import json
import os
from dataclasses import asdict, fields

from .config import SAVE_DIR
from .state import GameState

SAVE_PATH = SAVE_DIR / "autosave.json"

# 공유 링크로 여러 사람이 동시에 접속할 때는 저장 파일 하나를 함께 쓰게 되므로 꺼 둔다
ENABLED = True


def save(state):
    """턴이 끝날 때마다 호출한다. 게임이 끝났으면(사망/귀환) 저장 파일을 지운다."""
    if not ENABLED:
        return
    try:
        if state is None or state.status != "playing":
            delete()
            return
        SAVE_DIR.mkdir(exist_ok=True)
        temp = SAVE_PATH.with_suffix(".tmp")
        temp.write_text(json.dumps(asdict(state), ensure_ascii=False), encoding="utf-8")
        os.replace(temp, SAVE_PATH)     # 쓰다가 꺼져도 기존 저장이 깨지지 않게 한다
    except Exception as e:
        print(f"[저장] 자동 저장 실패: {e}")


def load():
    """저장된 게임을 불러온다. 없거나 읽을 수 없으면 None."""
    if not ENABLED:
        return None
    try:
        data = json.loads(SAVE_PATH.read_text(encoding="utf-8"))
        names = {f.name for f in fields(GameState)}
        state = GameState(**{k: v for k, v in data.items() if k in names})
    except Exception:
        return None
    if state.status != "playing":
        return None
    if state.image_path and not os.path.exists(state.image_path):
        state.image_path = None         # 이미지 파일이 지워졌으면 다시 그린다
    return state


def exists():
    return load() is not None


def delete():
    try:
        SAVE_PATH.unlink()
    except FileNotFoundError:
        pass
