"""테스트 도우미."""
import importlib
import pkgutil
import sys

import survival


def load_all_survival_modules():
    """survival 패키지의 모든 모듈을 불러 둔다(아직 import되지 않은 모듈의 바꿔 끼우기가 빠지지 않게)."""
    for info in pkgutil.iter_modules(survival.__path__):
        importlib.import_module(f"survival.{info.name}")


def patch_everywhere(monkeypatch, name, value):
    """survival 패키지에서 `name`을 가져다 쓰는 모든 모듈의 그 이름을 바꿔 끼운다.

    `from .weather import get_weather`처럼 이름을 가져다 쓰면 모듈마다 따로 참조를 가진다. 코드를 다른 모듈로
    옮겨도 바꿔 끼우기가 빠지지 않게 한다. 바꾼 모듈이 하나도 없으면 오류(이름이 바뀌었거나 없어졌다).
    """
    load_all_survival_modules()
    patched = []
    for module_name, module in list(sys.modules.items()):
        if module_name.startswith("survival.") and module is not None and hasattr(module, name):
            monkeypatch.setattr(module, name, value)
            patched.append(module_name)
    assert patched, f"survival 모듈에서 '{name}'을(를) 찾지 못했다"
    return patched
