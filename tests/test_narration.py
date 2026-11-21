"""GM 서술 보정: 한국어·바뀐 장소·몸 상태 (survival/gamemaster.py) 테스트."""
from types import SimpleNamespace

from survival import gamemaster
from tests.helpers import desert_noon


def test_foreign_script_is_detected_and_removed():
    assert gamemaster.has_foreign("당신은 सोच 깊이 생각한다.")
    assert gamemaster.has_foreign("상인이 «Привет» 하고 인사한다")
    assert not gamemaster.has_foreign("**버려진 오두막**에서 $5를 내고 12km를 걷는다. 기온 -3°C.")
    assert not gamemaster.has_foreign("Rajasthan의 사막", allowed=())                 # 영문은 허용
    assert not gamemaster.has_foreign("인도, राजस्थान 에 도착했다", allowed=("인도, राजस्थान",))   # 지명은 허용
    assert gamemaster.strip_foreign("당신은 सोच 깊이 생각한다.") == "당신은 깊이 생각한다."
    assert gamemaster.strip_foreign("노인이 (नमस्ते) 하고 웃는다") == "노인이 하고 웃는다"
    assert gamemaster.strip_foreign("인도, राजस्थान 에서 सोच", allowed=("인도, राजस्थान",)) == "인도, राजस्थान 에서"


def test_ensure_korean_rewrites_or_strips():
    calls = []

    def ok(**kw):
        calls.append(kw)
        return SimpleNamespace(output_text="당신은 잠시 생각에 잠긴다.\n▶ 물을 찾는다")

    client = SimpleNamespace(responses=SimpleNamespace(create=ok))
    clean = "당신은 잠시 생각에 잠긴다.\n▶ 물을 찾는다"
    assert gamemaster.ensure_korean(client, clean) == clean and calls == []          # 깨끗하면 호출하지 않음
    assert gamemaster.ensure_korean(client, "당신은 सोच 잠긴다.\n▶ 물을 찾는다") == clean and len(calls) == 1

    def bad(**kw):
        return SimpleNamespace(output_text="당신은 सोच 잠긴다.\n▶ 물을 찾는다")

    client = SimpleNamespace(responses=SimpleNamespace(create=bad))                  # 다시 써도 남으면 지운다
    assert gamemaster.ensure_korean(client, "당신은 सोच 잠긴다.\n▶ 물을 찾는다") == "당신은 잠긴다.\n▶ 물을 찾는다"


def test_turn_output_is_korean(game, monkeypatch):
    replies = iter([SimpleNamespace(id="r", output=[], output_text="당신은 सोच 길을 찾는다.\n▶ 걷는다\n▶ 쉰다\n▶ 먹는다"),
                    SimpleNamespace(output_text="당신은 곰곰이 길을 찾는다.\n▶ 걷는다\n▶ 쉰다\n▶ 먹는다")])
    monkeypatch.setattr(gamemaster, "get_client",
                        lambda: SimpleNamespace(responses=SimpleNamespace(create=lambda **k: next(replies))))
    assert gamemaster.run_turn(game, "길을 찾는다") == "당신은 곰곰이 길을 찾는다."


def test_narration_is_fixed_when_it_ignores_the_new_place(game):
    game.begin_turn()
    game.set_scene("outdoor", "마을 입구", "Village entrance.", ["작은 집들", "우물"])
    stale = "당신은 초원의 나무 그늘에서 쉰다.\n▶ 잔다\n▶ 물을 찾는다\n▶ 불을 피운다"
    good = "당신은 마을 입구에 들어선다. 우물이 보인다.\n▶ 잔다\n▶ 물을 찾는다\n▶ 불을 피운다"
    client = SimpleNamespace(responses=SimpleNamespace(create=lambda **k: SimpleNamespace(output_text=good)))
    assert gamemaster.ensure_scene(client, stale, game) == good
    assert gamemaster.ensure_scene(client, good, game) == good                    # 맞으면 그대로

    broken = SimpleNamespace(responses=SimpleNamespace(create=lambda **k: SimpleNamespace(output_text=stale)))
    assert gamemaster.ensure_scene(broken, stale, game).startswith("*📍 지금 위치: 마을 입구")   # 그래도 안 되면 표시

    game.begin_turn()                                                            # 장소가 안 바뀐 턴은 검사하지 않는다
    assert gamemaster.ensure_scene(broken, stale, game) == stale


def test_narration_checked_when_place_type_changes(game):
    game.begin_turn()
    game.place_type, game.scene_place = "마을", ""
    out = gamemaster.ensure_scene(None, "당신은 초원을 걷는다.", game)
    assert out.startswith("*📍 지금 위치:") and "마을" in out.splitlines()[0]
    assert gamemaster.ensure_scene(None, "당신은 마을에 들어선다.", game) == "당신은 마을에 들어선다."


def test_narration_numbers_follow_final_vitals(game, monkeypatch):
    desert_noon(game)
    game.hydration = 50
    calls = []
    def create(**k):
        calls.append(k)
        if len(calls) == 1:
            return SimpleNamespace(id="r", output=[], output_text="갈증이 심하다. 수분이 50까지 떨어졌다.")
        return SimpleNamespace(id="x", output=[], output_text="물이 목을 적시자 갈증이 가신다. 수분이 50까지 올랐다.")
    monkeypatch.setattr(gamemaster, "get_client", lambda: SimpleNamespace(responses=SimpleNamespace(create=create)))
    body = gamemaster.run_turn(game, "가지고 있는 물을 마신다")
    final = round(game.hydration)
    assert final > 80 and f"수분이 {final}" in body and "수분이 50" not in body
    assert "목마르지 않다" in calls[-1]["instructions"]          # 바뀐 몸 상태를 알려 주고 고치게 한다
    assert "갈증이 가신다" in body


def test_no_rewrite_when_band_unchanged(game, monkeypatch):
    calls = []
    def create(**k):
        calls.append(k)
        return SimpleNamespace(id="r", output=[], output_text="당신은 주변을 둘러본다. 체력 99")
    monkeypatch.setattr(gamemaster, "get_client", lambda: SimpleNamespace(responses=SimpleNamespace(create=create)))
    game.health = 90
    body = gamemaster.run_turn(game, "주변을 둘러본다")
    assert len(calls) == 1 and f"체력 {round(game.health)}" in body
