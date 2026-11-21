"""시간·생체 수치·툴 체계·턴 진행·알림 테스트."""
import json
from types import SimpleNamespace

from survival import gamemaster
from survival.state import GameState
from survival.tools import execute_tool, TOOLS
from survival.ui import render_notices
from tests.helpers import call, fake_weather


def test_time_drains_stats_and_sleep_restores_energy(game):
    game.energy = 30
    game.pass_time(4, "explore")
    assert game.satiety < 70 and game.hydration < 70 and game.energy < 30
    game.pass_time(6, "sleep")
    assert game.energy > 60
    assert game.elapsed_hours == 10


def test_deltas_recorded_for_ui(game):
    game.begin_turn()
    game.apply_delta(hydration=20, health=-15)
    game.end_turn(2, "explore")
    assert game.delta["health"] == -15 and game.delta["hours"] == 2
    assert game.delta["energy"] < 0 and game.delta["satiety"] < 0 and game.delta["hydration"] > 0


def test_extreme_biomes_are_harsher(game):
    def after_six_hours(biome, weather, **kw):
        s = GameState(lat=0, lon=0, place_name="x", weather=weather, biome=biome)
        s.pass_time(6, "explore", **kw)
        return s
    mild = after_six_hours("forest", fake_weather(18))
    desert = after_six_hours("desert", fake_weather(41))
    snow = after_six_hours("snow", fake_weather(-20))
    fire = after_six_hours("snow", fake_weather(-20), sheltered=True)
    assert mild.health == 100
    assert desert.hydration < mild.hydration - 20 and desert.health < 100
    assert snow.health < 85 and snow.satiety < mild.satiety
    assert fire.health > snow.health          # 불·쉘터가 있으면 덜 깎인다
    town = GameState(lat=0, lon=0, place_name="x", weather=fake_weather(-20), biome="snow", place_type="마을")
    town.pass_time(6, "explore")
    assert town.health == 100                 # 마을 안에서는 환경 피해 없음


def test_estimate_time_from_player_text():
    assert gamemaster.estimate_time("텐트에서 잠을 잔다") == (7.0, "sleep")
    assert gamemaster.estimate_time("3시간만 잔다") == (3.0, "sleep")
    assert gamemaster.estimate_time("30분 쉰다") == (0.5, "rest")
    assert gamemaster.estimate_time("여행자에게 말을 건다") == (0.5, "other")


def test_sleep_passes_time_even_if_llm_forgets(game, monkeypatch):
    reply = SimpleNamespace(id="r", output=[], output_text="당신은 **깊은 잠**에 빠진다.")
    fake = SimpleNamespace(responses=SimpleNamespace(create=lambda **k: reply))
    monkeypatch.setattr(gamemaster, "get_client", lambda: fake)
    gamemaster.run_turn(game, "취침한다")
    assert game.elapsed_hours == 7 and game.day == 1 and game.hour == 19
    assert game.delta["hours"] == 7 and game.delta["energy"] > 0


def test_dehydration_kills(game):
    game.hydration = 0
    game.satiety = 0
    for _ in range(5):
        game.pass_time(12, "other")
    assert game.status == "dead"


def test_llm_cannot_cheat_with_big_deltas(game):
    game.apply_delta(health=999, money=99999)
    assert game.health == 100
    assert game.money == 50 + 600                       # 한 번에 최대 +600


def test_tools_schema_is_strict():
    for tool in TOOLS:
        params = tool["parameters"]
        assert set(params["required"]) == set(params["properties"])
        assert params["additionalProperties"] is False


def test_execute_tool_returns_state(game):
    out = json.loads(execute_tool(game, "update_status", json.dumps(
        {"health": -10, "satiety": 0, "hydration": 30, "energy": 0, "money": 0, "reason": "물을 마셨다"})))
    assert out["ok"] and out["현재상태"]["체력"] == 90 and game.hydration == 100
    assert "error" in json.loads(execute_tool(game, "nope", "{}"))


def test_full_turn_with_fake_llm(game, monkeypatch):
    """가짜 OpenAI 클라이언트로 '툴 호출 → 결과 전달 → 최종 서술' 흐름을 검증한다."""
    calls = []

    def fake_create(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:   # 1차 응답: 툴 호출 요청
            return SimpleNamespace(id="resp1", output_text="", output=[
                SimpleNamespace(type="function_call", name="advance_time", call_id="c1",
                                arguments='{"hours": 2, "activity": "forage"}'),
                SimpleNamespace(type="function_call", name="update_status", call_id="c2",
                                arguments='{"health": 0, "satiety": 0, "hydration": 25, "energy": 0, '
                                          '"money": 0, "reason": "개울물"}'),
            ])
        return SimpleNamespace(id="resp2", output=[SimpleNamespace(type="message")],
                               output_text="당신은 개울을 찾아 목을 축인다.\n▶ 불을 피운다\n▶ 잠을 잔다\n▶ 계속 걷는다")

    fake_client = SimpleNamespace(responses=SimpleNamespace(create=fake_create))
    monkeypatch.setattr(gamemaster, "get_client", lambda: fake_client)

    body = gamemaster.run_turn(game, "물을 찾는다")
    assert body == "당신은 개울을 찾아 목을 축인다."
    assert game.suggestions == ["불을 피운다", "잠을 잔다", "계속 걷는다"]
    assert game.elapsed_hours == 2 and game.prev_response_id == "resp2"
    assert calls[1]["previous_response_id"] == "resp1"
    assert [o["call_id"] for o in calls[1]["input"]] == ["c1", "c2"]


def test_player_text_is_framed_as_attempt(game):
    game.begin_turn()
    text = gamemaster.build_input(game, "텔레포트기를 줍는다")
    assert "시도" in text and text.index("텔레포트기를 줍는다") > text.index("[현재 상태]")


def test_notices_for_important_events(game):
    game.turn = 4
    game.begin_turn()
    game.turn_flags.pop("new_lead", None)                            # 무작위로 생긴 단서는 이 테스트와 무관
    game.event = {"kind": "danger", "text": "눈보라가 몰아치기 시작했다."}
    game.offer = {"text": "트럭이 멈춘다.", "accept": "트럭에 올라탄다", "detail": "약 300km 무료 이동",
                  "risk": "낯선 사람의 차다", "turn": game.turn}
    call(game, "travel", method="walk", distance_km=12)
    kinds = [n["kind"] for n in gamemaster.collect_notices(game)]
    assert kinds == ["info", "danger", "offer"]
    markdown = render_notices(gamemaster.collect_notices(game))
    assert "> ### 🟢 기회가 찾아왔다" in markdown and "> #### ⚠️ 위험" in markdown and "📍 이동" in markdown

    game.event = {"kind": "neutral", "text": "발자국"}
    game.offer = None
    game.turn_flags = {}
    assert gamemaster.collect_notices(game) == [] and render_notices([]) == ""

    game.turn_flags = {"offer_result": {"bad": True, "title": "트럭에 올라탄다", "text": "강도였다."}}
    game.status = "dead"
    game.death_reason = "과다 출혈"
    assert [n["kind"] for n in gamemaster.collect_notices(game)] == ["bad", "bad"]


def test_placeholder_or_broken_api_key_is_rejected():
    from survival.config import read_api_key
    assert read_api_key("sk-여기에-키를-입력") is None      # 한글 안내 문구 → ascii 인코딩 오류의 원인
    assert read_api_key("sk-your-key-here") is None and read_api_key("") is None and read_api_key(None) is None
    assert read_api_key('  "sk-proj-abc123_DEF"  ') == "sk-proj-abc123_DEF"


def test_no_walk_to_korea_suggestion():
    cleaned = gamemaster.clean_suggestions(["한국 방향으로 걷는다", "물을 찾는다", "불을 피운다"])
    assert not any("한국" in s for s in cleaned) and len(cleaned) == 3 and len(set(cleaned)) == 3
    assert gamemaster.clean_suggestions(["한국행 비행기를 탄다", "a", "b"])[0] == "한국행 비행기를 탄다"
    assert not any("한국" in s for s in gamemaster.DEFAULT_SUGGESTIONS)


def test_long_suggestions_are_not_cut():
    long = "강을 따라 하류로 내려가며 사람이 사는 흔적을 찾는다"
    _, suggestions = gamemaster.split_suggestions(f"서술\n▶ {long}\n▶ 불을 피운다\n▶ 잔다")
    assert suggestions[0] == long
