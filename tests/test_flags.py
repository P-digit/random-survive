"""turn_flags / flags 키 검사: 코드에서 쓰는 모든 키가 survival/flags.py에 적혀 있고, 적힌 키는 실제로 쓰인다.

키를 문자열로 주고받으므로 오탈자는 오류 없이 동작만 조용히 깨뜨린다. 소스 코드를 AST로 읽어 다음을 모은다.
- state.turn_flags["k"], self.turn_flags.get("k"), .setdefault("k"), .pop("k"), "k" in ..., 대입하는 dict 리터럴의 키
- 같은 것을 state.flags / self.flags 에 대해
- 함수 안의 별칭: flags = state.turn_flags (or {}) 뒤의 flags.get("k")
- 변수 키로 쓰는 곳(self.flags[effect])은 바로 위 `if effect in ("a", "b")`의 상수들
"""
import ast
from pathlib import Path

from survival.flags import PLACE_FLAG_KEYS, TURN_FLAG_KEYS


ROOT = Path(__file__).resolve().parent.parent
SOURCES = sorted((ROOT / "survival").glob("*.py")) + [ROOT / "app.py"]
DICTS = {"turn_flags": "turn", "flags": "place"}
ACCESS = ("get", "setdefault", "pop")


def _kind(node, aliases):
    """node가 turn_flags/flags 중 어느 쪽을 가리키는지. 아니면 None."""
    if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
        return _kind(node.values[0], aliases)
    if isinstance(node, ast.Attribute) and node.attr in DICTS and isinstance(node.value, ast.Name) \
            and node.value.id in ("self", "state"):
        return DICTS[node.attr]
    if isinstance(node, ast.Name):
        return aliases.get(node.id)
    return None


def _str(node):
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _collect(tree):
    found = {"turn": {}, "place": {}}       # 종류 → {키: 첫 위치}
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}

    def add(kind, key, node):
        if kind and key:
            found[kind].setdefault(key, node.lineno)

    scopes = [tree] + [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    for scope in scopes:
        aliases = {}
        for node in ast.walk(scope):
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                kind = _kind(node.value, {})
                if kind:
                    aliases[node.targets[0].id] = kind
        for node in ast.walk(scope):
            if isinstance(node, ast.Subscript):
                kind = _kind(node.value, aliases)
                key = _str(node.slice)
                if kind and key is None and isinstance(node.slice, ast.Name):
                    # self.flags[effect] = True  ←  if effect in ("on_road", "can_call"):
                    guard = parents.get(node)
                    while guard is not None and not isinstance(guard, ast.If):
                        guard = parents.get(guard)
                    test = guard.test if guard is not None else None
                    assert isinstance(test, ast.Compare) and isinstance(test.ops[0], ast.In) \
                        and isinstance(test.comparators[0], (ast.Tuple, ast.List, ast.Set)), \
                        f"{node.lineno}행: 변수 키로 flags를 쓰려면 바로 위에 `if 변수 in (상수들)` 검사가 있어야 함"
                    for element in test.comparators[0].elts:
                        add(kind, _str(element), node)
                add(kind, key, node)
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in ACCESS \
                    and node.args:
                add(_kind(node.func.value, aliases), _str(node.args[0]), node)
            elif isinstance(node, ast.Compare) and isinstance(node.ops[0], (ast.In, ast.NotIn)):
                add(_kind(node.comparators[0], aliases), _str(node.left), node)
            elif isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict):
                for target in node.targets:
                    kind = _kind(target, {})
                    for key in node.value.keys:
                        add(kind, _str(key), node)
    return found


def used_keys():
    keys = {"turn": {}, "place": {}}
    for path in SOURCES:
        found = _collect(ast.parse(path.read_text(encoding="utf-8")))
        for kind in keys:
            for key, line in found[kind].items():
                keys[kind].setdefault(key, f"{path.relative_to(ROOT)}:{line}")
    return keys


def test_every_turn_flag_in_code_is_declared():
    unknown = {k: where for k, where in used_keys()["turn"].items() if k not in TURN_FLAG_KEYS}
    assert not unknown, f"survival/flags.py TurnFlags에 없는 turn_flags 키(오탈자이거나 새 키): {unknown}"


def test_every_place_flag_in_code_is_declared():
    unknown = {k: where for k, where in used_keys()["place"].items() if k not in PLACE_FLAG_KEYS}
    assert not unknown, f"survival/flags.py PlaceFlags에 없는 flags 키(오탈자이거나 새 키): {unknown}"


def test_every_declared_flag_is_used():
    used = used_keys()
    assert not TURN_FLAG_KEYS - set(used["turn"]), f"쓰이지 않는 TurnFlags 키: {TURN_FLAG_KEYS - set(used['turn'])}"
    assert not PLACE_FLAG_KEYS - set(used["place"]), \
        f"쓰이지 않는 PlaceFlags 키: {PLACE_FLAG_KEYS - set(used['place'])}"


def test_checker_catches_a_typo():
    """검사기 자체 확인: 별칭을 거친 오탈자, 직접 쓴 오탈자, 변수 키의 상수를 모두 잡는다."""
    code = '''
def f(state):
    flags = state.turn_flags or {}
    if flags.get("arested"):
        pass
    state.turn_flags["moevd"] = 1
    for effect in ("x",):
        if effect in ("on_raod",):
            state.flags[effect] = True
'''
    found = _collect(ast.parse(code))
    assert set(found["turn"]) == {"arested", "moevd"} and set(found["place"]) == {"on_raod"}
