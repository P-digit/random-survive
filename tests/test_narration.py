"""GM 서술 보정: 한국어·바뀐 장소·몸 상태 (survival/gamemaster.py) 테스트."""
import json
from types import SimpleNamespace

from survival import gamemaster
from tests.helpers import desert_noon, reply_with


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


# ---------- 서술 속의 돈: 플레이 테스트에서 실제로 나온 문장들 ----------
def test_money_sentences_are_classified_by_direction():
    m = gamemaster.money_mentions
    assert m("아침이 되자 아바카르는 수고했다며 수고비로 **10 달러를 건네줍니다**.") == [(10, "in")]
    assert m("그는 **$70의 여비까지 챙겨 주겠다**며 같이 가자고 합니다.") == [(70, "promise")]
    assert m("주인에게 $12를 건네고 방 열쇠를 받는다.") == [(12, "out")]
    assert m("작은 가게에 5달러를 내고 빵 2개를 샀습니다.") == [(5, "out")]
    assert m("노인이 당신에게 $20를 주었다.") == [(20, "in")]
    assert m("소매치기에게 $40를 빼앗겼다.") == [(40, "loss")]
    assert m("버스 요금은 $12 정도다.") == [(12, "unknown")]
    assert m("일을 도우면 $30를 받을 수 있다고 한다.") == [(30, "unknown")]
    # 2회차 플레이 테스트의 문장들
    assert m("일한 대가로 **카를로스는 현금 $15를 수고비로 건넸습니다**.") == [(15, "in")]
    assert m("빵과 생수를 내어주고, 4달러를 셈하여 받아 갑니다.") == [(4, "out")]
    assert m("카를로스에게 $5를 지불하고 행랑채에서 잠을 청합니다.") == [(5, "out")]


def test_reward_handed_to_player_is_not_charged(game, monkeypatch):
    """보고된 경우 A: GM이 툴로 +$10을 줬는데 '10 달러를 건네줍니다'를 지불로 읽어 -$10 하던 문제."""
    tool = SimpleNamespace(id="r1", output_text="", output=[SimpleNamespace(
        type="function_call", name="update_status", call_id="a", arguments=json.dumps(
            {"health": 0, "satiety": 0, "hydration": 0, "energy": -10, "money": 10, "money_source": "earned",
             "consumed_items": [], "reason": "밤새 일한 수고비"}))])
    reply_with(monkeypatch, tool, SimpleNamespace(id="r2", output=[], output_text=(
        "아침이 되자 아바카르는 수고했다며 수고비로 **10 달러를 건네줍니다**.")))
    gamemaster.run_turn(game, "일을 해서 돈을 번다")
    assert game.money == 60
    assert not any("💸" in n["title"] or "💵" in n["title"] for n in game.notices)   # 서술에 금액이 있다


def test_promised_money_is_not_paid_yet(game, monkeypatch):
    """보고된 경우 B: '$70의 여비까지 챙겨 주겠다'는 제안을 받은 돈으로 처리하던 문제."""
    reply_with(monkeypatch, SimpleNamespace(id="r", output=[], output_text=(
        "한 교민 남성이 자신의 집으로 초대하며 **$70의 여비까지 챙겨 주겠다**며 같이 가자고 합니다.")))
    gamemaster.run_turn(game, "가족에게 연락한다")
    assert game.money == 50


def test_unexplained_tool_payment_gets_a_notice(game, monkeypatch):
    """보고된 경우 C: GM이 pay로 $50을 썼는데 서술에 없어서 플레이어가 이유를 모르던 문제."""
    def turn(text):
        tool = SimpleNamespace(id="r1", output_text="", output=[SimpleNamespace(
            type="function_call", name="pay", call_id="a", arguments=json.dumps(
                {"amount": 20, "purpose": "운전기사 사례비"}))])
        reply_with(monkeypatch, tool, SimpleNamespace(id="r2", output=[], output_text=text))
        gamemaster.run_turn(game, "히치하이킹으로 도시로 간다")
        return [n["title"] for n in game.notices]
    titles = turn("길가에서 한참 차를 기다렸지만 차는 오지 않는다.")
    assert game.money == 30 and "💸 지출 -$20 — 운전기사 사례비" in titles
    titles = turn("기사에게 사례비로 $20를 건네고 트럭에 오른다.")
    assert game.money == 10 and not any("💸" in t for t in titles)          # 서술에 있으면 알림 없음
