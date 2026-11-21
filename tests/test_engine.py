"""게임 엔진 테스트. 네트워크와 OpenAI 없이 실행된다:  python -m pytest"""
import json
import math
import random
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from survival import climate, gamemaster, geo, knowledge, state as state_module  # noqa: E402
from survival.events import classify_biome, roll_event  # noqa: E402
from survival.risk_model import predict_risk, train  # noqa: E402
from survival.state import GameState  # noqa: E402
from survival import tools as tools_module  # noqa: E402
from tests.helpers import patch_everywhere  # noqa: E402
from survival.tools import TOOLS, execute_tool  # noqa: E402


def fake_weather(temperature=20.0, **overrides):
    weather = {"ok": True, "temperature": temperature, "feels_like": temperature, "humidity": 50.0,
               "precipitation": 0.0, "wind_speed": 5.0, "is_day": True, "code": 0,
               "description": "맑음", "emoji": "☀️", "description_en": "clear sky",
               "elevation": 300.0, "local_hour": 12}
    weather.update(overrides)
    return weather


@pytest.fixture
def game(monkeypatch):
    """네트워크 호출을 모두 가짜로 바꾼 게임 상태 (몽골 초원에서 시작)."""
    patch_everywhere(monkeypatch, "get_weather", lambda lat, lon: fake_weather())   # state, travel, ...
    monkeypatch.setattr(geo, "reverse_geocode", lambda lat, lon: {"name": "테스트 지역"})
    monkeypatch.setattr(geo, "is_land", lambda lat, lon: True)
    monkeypatch.setattr(state_module, "EARLY_GAME_HOURS", 0)   # 대부분의 테스트는 초반 제한 없이 (따로 테스트함)
    monkeypatch.setattr(state_module.climate_api, "get_climate",
                        lambda lat, lon, weather, today=None: climate.make_climate("temperate", lat, 7))
    lat, lon = 46.9, 103.8
    distance = geo.distance_to_korea(lat, lon)
    return GameState(lat=lat, lon=lon, place_name="몽골", weather=fake_weather(), biome="forest",
                     start_distance=distance, distance=distance)


def test_distance_and_movement():
    assert geo.distance_to_korea(*geo.SEOUL) == pytest.approx(0, abs=1e-6)
    assert geo.haversine_km(37.5665, 126.978, 35.6762, 139.6503) == pytest.approx(1150, rel=0.03)  # 서울-도쿄
    before = geo.distance_to_korea(46.9, 103.8)
    lat, lon = geo.move_toward_korea(46.9, 103.8, 500)
    assert geo.distance_to_korea(lat, lon) == pytest.approx(before - 500, abs=2)
    assert geo.move_toward_korea(37.0, 127.0, 9999) == geo.SEOUL


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


def test_weather_follows_game_clock(game):
    game.set_weather(fake_weather(25, hourly=[{"temperature": 25.0, "feels_like": 25.0},
                                              {"temperature": 20.0, "feels_like": 19.0},
                                              {"temperature": 4.0, "feels_like": 1.0}]))
    game.pass_time(2, "rest")
    assert game.weather["temperature"] == 4.0 and "hourly" not in game.weather
    game.pass_time(5, "rest")
    assert game.weather["temperature"] == 4.0   # 예보 끝을 넘어가면 마지막 값 유지


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


def test_travel_rules(game):
    assert game.travel("flight", 5000)["success"] is False   # 야생에서는 비행기를 탈 수 없다
    assert game.travel("bus", 100)["success"] is False

    before = game.distance
    result = game.travel("walk", 20)
    assert result["success"] is True
    assert game.distance == pytest.approx(before - 20, abs=2)

    game.place_type, game.money = "도시", 10
    assert game.travel("train", 1000)["success"] is False    # 돈 부족
    game.money = 5000
    assert game.travel("flight", 99999)["success"] is False  # 초반에는 공항으로 갈 방법이 없다
    game.flags["at_airport"] = True
    result = game.travel("flight", 99999)
    assert result["arrived_in_korea"] is True
    assert game.status == "won" and game.distance == 0


def test_sea_blocks_land_travel(game, monkeypatch):
    monkeypatch.setattr(geo, "is_land", lambda lat, lon: False)
    before = game.distance
    assert game.travel("walk", 20)["success"] is False
    assert game.distance == before


def test_inventory(game):
    game.update_items(add=["마른 장작"], remove=["물"])
    assert "마른 장작" in game.items
    assert not any("물 1L" == item for item in game.items)


def test_risk_model_learns_and_orders_situations():
    _, accuracy = train(save=False)
    assert accuracy > 0.75
    safe = predict_risk(fake_weather(20), 100, 90, 90, 90, is_night=False, in_wild=False)
    deadly = predict_risk(fake_weather(-25, wind_speed=50, precipitation=5), 30, 10, 10, 10,
                          is_night=True, in_wild=True)
    assert safe["level"] == 0 and deadly["level"] == 2
    assert sum(deadly["probs"]) == pytest.approx(1.0)


def test_biome_and_events():
    assert classify_biome(70, fake_weather(-20)) == "snow"
    assert classify_biome(23, fake_weather(38, humidity=12)) == "desert"
    assert classify_biome(-3, fake_weather(27, humidity=88)) == "jungle"
    rng = random.Random(0)
    kinds = [e["kind"] for e in (roll_event("desert", "야생", 2, rng) for _ in range(300)) if e]
    assert kinds.count("danger") > len(kinds) / 2      # 위험 등급이 높으면 위험 이벤트가 많다


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


def test_keyword_search_finds_relevant_chunk():
    docs = knowledge.search(None, "뱀에 물렸을 때 어떻게 해야 해?")
    assert any("뱀" in d for d in docs)


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


def test_numpy_vector_search_without_chromadb(monkeypatch, tmp_path):
    """가짜 임베딩(글자 포함 여부)으로 numpy 벡터 검색 경로를 검증한다."""
    keys = ["뱀", "여권", "물", "불", "눈"]

    def fake_embed(client, texts):
        return [[float(k in t) + 0.01 for k in keys] for t in texts]

    monkeypatch.setattr(knowledge, "embed", fake_embed)
    monkeypatch.setattr(knowledge, "embed_cache_path", lambda: tmp_path / "e.json")
    monkeypatch.setattr(knowledge, "_matrix", None)
    docs = knowledge.numpy_search(object(), "여권", n_results=2)
    assert "여권" in docs[0] and (tmp_path / "e.json").exists()


# ---------- 3차 수정: 소지품 규칙 / 기회 / 저장 / 턴 제한 ----------
from survival import imagegen, savegame  # noqa: E402
from survival.events import roll_major_event  # noqa: E402


def call(game, tool_name, **args):
    return json.loads(execute_tool(game, tool_name, json.dumps(args)))


def test_inventory_rejects_places_and_impossible_items(game):
    game.begin_turn()
    out = call(game, "update_inventory", remove=[], add=[
        {"name": "빈 오두막", "carryable": True},        # 키워드로 거부
        {"name": "텔레포트기", "carryable": True},       # 존재할 수 없는 물건
        {"name": "버려진 낙타", "carryable": False},     # LLM이 스스로 들 수 없다고 판단
        {"name": "마른 장작", "carryable": True}])
    assert len(out["거부된_물건"]) == 3
    assert "마른 장작" in game.items
    assert not any(w in " ".join(game.items) for w in ("오두막", "텔레포트", "낙타"))


def test_consumables_disappear_when_used(game):
    game.begin_turn()
    game.update_items(add=["빗물(1회분)"])
    out = call(game, "update_status", health=0, satiety=0, hydration=30, energy=0, money=0,
               consumed_items=["빗물"], reason="받아 둔 빗물을 마셨다")
    assert out["사라진_소지품"] == ["빗물"]
    assert not any("빗물" in i for i in game.items) and "물 1L" in game.items   # 생수병은 그대로
    assert game.consume_item("에너지바") and "에너지바 1개" in game.items       # 수량은 하나씩 줄어든다
    assert game.consume_item("에너지바") and not any("에너지바" in i for i in game.items)


def test_auto_consume_when_llm_forgets(game):
    game.begin_turn()
    game.update_items(add=["야생 열매"])
    game.turn_flags.update(intake=True, consumed=False)
    gamemaster.auto_consume(game, "야생 열매를 먹는다")
    assert "야생 열매" not in game.items


def test_only_one_travel_per_turn(game):
    game.begin_turn()
    first = call(game, "travel", method="walk", distance_km=10)
    after_first = game.distance
    second = call(game, "travel", method="walk", distance_km=10)
    assert first["success"] and "error" in second and game.distance == after_first
    assert "error" in call(game, "advance_time", hours=5, activity="rest", sheltered=False)
    game.begin_turn()                      # 다음 턴에는 다시 가능
    assert call(game, "travel", method="walk", distance_km=10)["success"]


def test_major_event_offer_ride_and_expiry(game):
    rng = random.Random(1)
    offer = roll_major_event("야생", True, rng=rng)
    assert offer["id"] in ("trucker", "convoy", "rescue", "supply")

    game.turn = 5
    game.begin_turn()
    template = next(e for e in __import__("survival.events", fromlist=["x"]).MAJOR_EVENTS if e["id"] == "trucker")
    game.offer = game.plan_offer({"id": "trucker", "text": template["text"], "accept": "트럭에 올라탄다",
                                  "hours": 0, "stats": {}, "items": [], "money": 0, "risk": "",
                                  "bad": dict(template["bad"]), "move": dict(template["move"])})
    game.offer["turn"] = game.turn
    assert "울란바토르" in game.offer["text"] and "{dest}" not in game.offer["text"]   # 실제 가까운 도시가 목적지
    game.end_turn(0.5)
    assert game.offer is not None          # 나온 턴에는 유지
    game.begin_turn()
    game.offer["bad"]["chance"] = 0                       # 좋은 결과로 고정
    out = call(game, "accept_offer")
    assert out["success"] and game.offer is None
    assert (game.lat, game.lon) == (47.89, 106.91) and game.place_type == "도시" and "울란바토르" in game.place_name
    assert call(game, "accept_offer")["success"] is False

    game.offer = {"id": "news", "text": "기자", "accept": "", "detail": "", "turn": game.turn - 1,
                  "hours": 0, "stats": {}, "items": [], "money": 100}
    game.end_turn(0.5)
    assert game.offer is None              # 받아들이지 않으면 다음 턴 끝에 사라진다


def test_major_event_is_guaranteed_eventually(game):
    seen = False
    for _ in range(12):
        game.begin_turn()
        seen = seen or game.offer is not None
        game.end_turn(0.25)
        game.health = game.satiety = game.hydration = game.energy = 100
    assert seen


def test_save_and_resume(game, monkeypatch, tmp_path):
    monkeypatch.setattr(savegame, "SAVE_DIR", tmp_path)
    monkeypatch.setattr(savegame, "SAVE_PATH", tmp_path / "autosave.json")
    assert savegame.load() is None and not savegame.exists()
    game.begin_turn()
    game.pass_time(3, "explore")
    game.update_items(add=["마른 장작"])
    game.chat = [{"role": "assistant", "content": "시작"}, {"role": "user", "content": "걷는다"}]
    game.prev_response_id = "resp_x"
    game.end_turn()
    savegame.save(game)

    loaded = savegame.load()
    assert loaded is not None and loaded is not game
    for key in ("lat", "lon", "health", "hydration", "elapsed_hours", "items", "chat",
                "prev_response_id", "distance", "turn", "delta"):
        assert getattr(loaded, key) == getattr(game, key), key
    loaded.pass_time(1, "rest")            # 불러온 상태로 계속 진행할 수 있다

    game.status = "dead"
    savegame.save(game)                    # 게임이 끝나면 저장 파일이 지워진다
    assert not savegame.exists()


def test_resume_with_expired_conversation(game, monkeypatch):
    """저장된 대화 ID가 만료됐으면 최근 줄거리를 넣어 새 대화로 이어간다."""
    calls = []

    def fake_create(**kwargs):
        calls.append(kwargs)
        if kwargs.get("previous_response_id") == "expired":
            raise RuntimeError("Previous response not found")
        return SimpleNamespace(id="new", output=[], output_text="당신은 다시 눈을 뜬다.")

    monkeypatch.setattr(gamemaster, "get_client",
                        lambda: SimpleNamespace(responses=SimpleNamespace(create=fake_create)))
    game.prev_response_id = "expired"
    game.chat = [{"role": "assistant", "content": "당신은 동굴에서 불을 피웠다."}]
    gamemaster.run_turn(game, "주변을 살펴본다")
    assert len(calls) == 2 and calls[1]["previous_response_id"] is None
    assert "이전 줄거리" in calls[1]["input"] and "동굴" in calls[1]["input"]
    assert game.prev_response_id == "new"


def test_image_prompt_shows_weather_and_no_weapons(game):
    game.weather.update(code=65, description_en="heavy rain", wind_speed=50)
    prompt = imagegen.build_prompt(game)
    assert "raining" in prompt and "Strong wind" in prompt and "no guns" in prompt
    assert "first-person" not in prompt
    game.weather.update(code=75, wind_speed=5)
    assert "snowing" in imagegen.build_prompt(game)
    game.weather.update(code=0)
    assert "IMPORTANT" not in imagegen.build_prompt(game)


def test_player_text_is_framed_as_attempt(game):
    game.begin_turn()
    text = gamemaster.build_input(game, "텔레포트기를 줍는다")
    assert "시도" in text and text.index("텔레포트기를 줍는다") > text.index("[현재 상태]")


# ---------- 4차 수정: 장면 / 위험이 따르는 기회 / 상황에 맞는 이벤트 ----------
def test_scene_change_triggers_redraw_and_shelter(game):
    game.scene_dirty = False
    assert call(game, "set_scene", setting="indoor", place="빈 오두막 안",
                description_en="Inside a small abandoned log cabin with a rusty stove.")["장면이_바뀜"]
    assert game.indoor and game.scene_dirty
    prompt = imagegen.build_prompt(game)
    assert "interior" in prompt.lower() and "log cabin" in prompt and "no guns" in prompt

    game.scene_dirty = False               # 같은 곳이면 다시 그리지 않는다
    assert not call(game, "set_scene", setting="indoor", place="빈 오두막 안", description_en="same")["장면이_바뀜"]
    assert not game.scene_dirty

    game.weather.update(feels_like=-25.0, temperature=-20.0)   # 실내에서는 혹한 피해가 줄어든다
    inside = game.health
    game.pass_time(4, "rest")
    inside_loss = inside - game.health
    game.set_scene("outdoor", "오두막 앞 눈밭", "Snowy clearing in front of a cabin.")
    outside = game.health
    game.pass_time(4, "rest")
    assert outside - game.health > inside_loss * 2

    game.begin_turn()
    call(game, "travel", method="walk", distance_km=10)        # 이동하면 장면은 새 장소의 야외로 초기화
    assert not game.indoor and game.scene_place == "" and game.scene_dirty


def test_events_fit_the_scene(game):
    rng = random.Random(3)
    for _ in range(50):                     # 실내에서는 지나가는 차량·헬기·보급 상자가 나오지 않는다
        offer = roll_major_event("도시", False, indoor=True, rng=rng)
        assert offer["id"] in ("korean", "news", "embassy")
    assert roll_major_event("야생", True, indoor=True, rng=rng) is None

    game.set_scene("indoor", "동굴 안", "Inside a dark cave.")
    game.turn = 20                          # 기회가 나올 차례여도, 맞는 것이 없으면 나오지 않는다
    game.begin_turn()
    assert game.offer is None
    from survival.events import EVENTS
    indoor_texts = {e["text"] for e in EVENTS if e.get("indoor")}
    assert game.event is None or game.event["text"] in indoor_texts   # 실내에서는 실내 이벤트만

    game.set_scene("outdoor", "", "")
    game.begin_turn()
    assert game.offer is not None           # 밖으로 나오면 밀린 기회가 찾아온다
    call(game, "reject_event", reason="상황에 맞지 않음")
    assert game.offer is None and game.event is None


def test_flight_is_always_direct_to_korea(game):
    game.begin_turn()
    game.place_type, game.money = "도시", 100
    assert call(game, "travel", method="flight", distance_km=300)["success"] is False   # 직항 요금이 모자람
    game.money = 5000
    game.flags["at_airport"] = True
    out = call(game, "travel", method="flight", distance_km=300)
    assert out["arrived_in_korea"] and game.status == "won"


def test_offer_can_end_badly(game, monkeypatch):
    from survival.events import MAJOR_EVENTS

    def fresh(offer_id, money=200.0):
        s = GameState(lat=46.9, lon=103.8, place_name="몽골", weather=fake_weather(), biome="forest",
                      start_distance=2160, distance=geo.distance_to_korea(46.9, 103.8), money=money)
        s.begin_turn()
        e = next(x for x in MAJOR_EVENTS if x["id"] == offer_id)
        s.offer = s.plan_offer({"id": offer_id, "text": e["text"], "accept": e["accept"], "hours": e.get("hours", 0),
                                "stats": dict(e.get("stats", {})), "items": list(e.get("items", [])),
                                "money": 100 if "money" in e else 0, "risk": e["risk"], "bad": dict(e["bad"]),
                                "move": dict(e.get("move", {}))})
        s.offer["turn"] = s.turn
        return s

    monkeypatch.setattr(state_module.random, "random", lambda: 0.0)     # 항상 나쁜 결과
    s = fresh("trucker")
    route = geo.haversine_km(s.lat, s.lon, s.offer["dest"]["lat"], s.offer["dest"]["lon"])
    start = (s.lat, s.lon)
    out = s.accept_offer()
    assert out["outcome"] == "나쁜 결과" and s.money == pytest.approx(60)   # 70%를 빼앗김
    assert geo.haversine_km(*start, s.lat, s.lon) == pytest.approx(route * 0.2, abs=3) and s.place_type == "야생"
    assert s.health < 100

    s = fresh("korean")
    items_before = len(s.items)
    s.accept_offer()
    assert s.money == pytest.approx(40) and len(s.items) == items_before - 1 and "여권" in s.items

    s = fresh("supply")
    s.accept_offer()
    assert s.health < 100 and not any("비상식량" in i for i in s.items)

    monkeypatch.setattr(state_module.random, "random", lambda: 0.99)    # 항상 좋은 결과
    s = fresh("trucker")
    out = s.accept_offer()
    assert out["outcome"] == "좋은 결과" and s.money == 200 and s.place_type == "도시"
    s = fresh("supply")
    s.accept_offer()
    assert any("비상식량" in i for i in s.items)


def test_every_major_event_has_a_downside():
    from survival.events import MAJOR_EVENTS
    for event in MAJOR_EVENTS:
        assert 0.1 <= event["bad"]["chance"] <= 0.4 and event["bad"]["text"] and event["risk"]


# ---------- 5차 수정: 기후 / 그림과 서술의 일치 / 대화창 알림 ----------
import datetime  # noqa: E402

from survival.ui import render_notices  # noqa: E402


def test_climate_zones_from_yearly_records():
    zone = climate.classify_zone
    assert zone([14, 16, 20, 25, 30, 34, 36, 35, 31, 26, 20, 15], [2] * 12) == "desert"              # 사하라
    assert zone([26, 26, 27, 27, 27, 26, 26, 27, 27, 27, 27, 26], [250] * 12) == "rainforest"       # 아마존
    assert zone([25, 27, 29, 30, 29, 27, 26, 26, 26, 27, 26, 25], [0, 0, 5, 30, 120, 180, 250, 260, 200, 90, 10, 0]) == "savanna"
    assert zone([-2, 0, 5, 12, 18, 22, 25, 26, 21, 14, 7, 0], [20, 25, 45, 80, 100, 130, 390, 350, 140, 50, 50, 25]) == "temperate"  # 서울
    assert zone([-40, -35, -22, -7, 6, 15, 19, 15, 6, -8, -28, -38], [10, 8, 7, 10, 20, 35, 40, 38, 30, 20, 15, 12]) == "continental"  # 야쿠츠크
    assert zone([-28, -28, -26, -18, -7, 1, 5, 4, -1, -9, -18, -24], [5] * 12) == "polar"
    assert zone([5] * 12, [50] * 12, elevation=3800) == "alpine"
    assert climate.current_season(37, 1, "temperate") == "겨울"
    assert climate.current_season(-34, 1, "temperate") == "여름"          # 남반구는 반대
    assert climate.current_season(5, 8, "savanna", [0, 0, 5, 30, 120, 180, 250, 260, 200, 90, 10, 0]) == "우기"


def test_climate_api_parsing_and_fallback(monkeypatch):
    days = [datetime.date(2025, 11, 7) + datetime.timedelta(days=i) for i in range(365)]

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"daily": {"time": [d.isoformat() for d in days],
                              "temperature_2m_mean": [30.0 if 5 <= d.month <= 9 else 16.0 for d in days],
                              "precipitation_sum": [0.05] * 365}}

    monkeypatch.setattr(climate.requests, "get", lambda *a, **k: FakeResponse())
    result = climate.get_climate(23.4, 11.2, fake_weather(20), today=datetime.date(2026, 11, 17))
    assert result["zone"] == "desert" and result["biome"] == "desert" and result["source"] == "기록"
    assert result["season"] == "가을" and result["t_warm"] == 30 and result["p_ann"] == 18
    assert "사막 기후" in climate.describe(result)

    def broken(*a, **k):
        raise OSError("network down")
    monkeypatch.setattr(climate.requests, "get", broken)
    guess = climate.get_climate(23.4, 11.2, fake_weather(38, humidity=10))
    assert guess["zone"] == "desert" and guess["source"] == "추정"


def test_biome_follows_climate_not_todays_weather():
    desert = climate.make_climate("desert", 23, 1)
    assert classify_biome(23, fake_weather(6, humidity=70), desert) == "desert"      # 사막의 추운 밤도 사막
    taiga = climate.make_climate("continental", 62, 1)
    assert classify_biome(62, fake_weather(-25), taiga) == "snow"                    # 냉대의 한겨울은 설원
    assert classify_biome(62, fake_weather(18), taiga) == "forest"


def test_image_matches_declared_scene(game):
    game.climate = climate.make_climate("continental", 60, 1)
    game.set_scene("outdoor", "숲 가장자리", "A snowy forest edge with an abandoned log cabin by a frozen stream.",
                   ["버려진 오두막", "얼어붙은 개울"])
    prompt = imagegen.build_prompt(game)
    assert "abandoned log cabin" in prompt and "boreal conifer forest" in prompt and "winter" in prompt
    assert not imagegen.HANGUL.search(prompt)                # 그림 지시문에는 한글이 없다
    assert "untouched nature with no trace of people" in prompt   # 야생에서는 밝히지 않은 건물을 그리지 않는다

    game.scene_seen = ["버려진 오두막", "낡은 헛간"]        # Vision이 그림에서 추가로 발견한 것
    game.begin_turn()
    text = gamemaster.build_input(game, "헛간에 들어간다")
    assert "[화면에 보이는 것" in text and "낡은 헛간" in text and "얼어붙은 개울" in text
    assert "기후" in text and "냉대 기후" in text

    game.set_scene("indoor", "오두막 안", "Inside the cabin.", ["녹슨 난로"])
    assert game.scene_seen == [] and game.visible_things() == ["녹슨 난로"]


def test_describe_image_reads_back_what_was_drawn(tmp_path):
    path = tmp_path / "scene.png"
    path.write_bytes(b"\x89PNG fake")
    seen = {}

    def fake_create(**kwargs):
        seen.update(kwargs)
        return SimpleNamespace(output_text="통나무 오두막, 얼어붙은 호수,\n침엽수림.")

    client = SimpleNamespace(responses=SimpleNamespace(create=fake_create))
    assert imagegen.describe_image(client, str(path)) == ["통나무 오두막", "얼어붙은 호수", "침엽수림"]
    image_part = seen["input"][0]["content"][1]
    assert image_part["type"] == "input_image" and image_part["image_url"].startswith("data:image/png;base64,")
    assert imagegen.describe_image(client, "/없는/파일.png") == []


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


# ---------- 6차 수정: 교통편 예약 / 추천 행동 ----------
def test_ticket_is_remembered_and_used_on_boarding(game):
    game.begin_turn()
    game.place_type, game.money = "도시", 2000
    price = game.fare("flight", game.distance)
    out = call(game, "buy_ticket", method="flight", distance_km=1)
    assert out["success"] and game.money == pytest.approx(2000 - price)
    assert "한국행 항공권" in game.items and game.find_ticket("flight")
    assert "error" not in out and "한국행 항공권" in str(out["현재상태"]["예약한_교통편"])
    assert call(game, "buy_ticket", method="flight", distance_km=1)["success"] is False   # 중복 구매 불가
    assert any(n["title"].startswith("🎫") for n in gamemaster.collect_notices(game))

    for _ in range(3):                      # 여러 턴이 지나고, 돈을 다 써도 표는 남아 있다
        game.begin_turn()
        game.end_turn(0.5)
    game.money = 0
    game.flags["embassy_visited"] = True                     # 공관의 도움을 받았으면 도시에서 공항으로 갈 수 있다
    game.begin_turn()
    assert "한국행 항공권" in gamemaster.build_input(game, "한국행 비행기를 탄다")
    out = call(game, "travel", method="flight", distance_km=1)
    assert out["success"] and out["arrived_in_korea"] and game.status == "won"
    assert game.tickets == [] and "한국행 항공권" not in game.items and game.money == 0


def test_bus_ticket_consumed_and_survives_save(game, monkeypatch, tmp_path):
    monkeypatch.setattr(savegame, "SAVE_DIR", tmp_path)
    monkeypatch.setattr(savegame, "SAVE_PATH", tmp_path / "autosave.json")
    game.begin_turn()
    game.place_type, game.money = "마을", 100
    assert call(game, "buy_ticket", method="bus", distance_km=300)["success"]
    money_after_buying = game.money
    assert "버스 티켓(300km)" in game.items
    savegame.save(game)
    loaded = savegame.load()                # 저장했다 불러와도 예약이 남아 있다
    assert loaded.find_ticket("bus")["km"] == 300

    before = game.distance
    out = call(game, "travel", method="bus", distance_km=50)    # 표의 구간(300km)만큼 간다
    assert out["success"] and before - game.distance == pytest.approx(300, abs=3)
    assert game.money == money_after_buying and not any("티켓" in i for i in game.items)
    assert "사용" in gamemaster.collect_notices(game)[0]["title"]


def test_tickets_cannot_be_conjured_as_items(game):
    game.begin_turn()
    out = call(game, "update_inventory", remove=[], add=[{"name": "한국행 비행기 티켓", "carryable": True}])
    assert out["거부된_물건"] and not any("티켓" in i for i in game.items)
    assert call(game, "buy_ticket", method="flight", distance_km=1)["success"] is False   # 야생에서는 못 산다
    assert call(game, "buy_ticket", method="walk", distance_km=1)["success"] is False


def test_no_walk_to_korea_suggestion():
    cleaned = gamemaster.clean_suggestions(["한국 방향으로 걷는다", "물을 찾는다", "불을 피운다"])
    assert not any("한국" in s for s in cleaned) and len(cleaned) == 3 and len(set(cleaned)) == 3
    assert gamemaster.clean_suggestions(["한국행 비행기를 탄다", "a", "b"])[0] == "한국행 비행기를 탄다"
    assert not any("한국" in s for s in gamemaster.DEFAULT_SUGGESTIONS)


def test_saving_can_be_disabled_for_share_mode(game, monkeypatch, tmp_path):
    monkeypatch.setattr(savegame, "SAVE_DIR", tmp_path)
    monkeypatch.setattr(savegame, "SAVE_PATH", tmp_path / "autosave.json")
    savegame.save(game)
    assert savegame.exists()
    monkeypatch.setattr(savegame, "ENABLED", False)      # python app.py --share
    assert not savegame.exists() and savegame.load() is None
    game.health = 1
    savegame.save(game)                                  # 저장하지도, 기존 파일을 건드리지도 않는다
    monkeypatch.setattr(savegame, "ENABLED", True)
    assert savegame.load().health == 100



# ---------- 7차 수정: 자유 행동 (시도 판정, 탈것, 수배도) ----------
def fix_roll(monkeypatch, value):
    monkeypatch.setattr(state_module.random, "random", lambda: value)


def test_hijack_truck_then_drive(game, monkeypatch):
    game.begin_turn()
    game.offer = {"id": "trucker", "text": "트럭", "accept": "", "detail": "", "turn": game.turn}
    assert call(game, "acquire_vehicle", kind="truck", name="화물 트럭")["success"] is False   # 시도 없이 못 얻는다

    fix_roll(monkeypatch, 0.0)                                       # 주사위: 성공
    out = call(game, "attempt_action", action="트럭 기사를 기절시킨다", difficulty="hard",
               crime="차량 절도", witnessed="victim", violent=True, item="다용도 칼", stealth=False)
    assert out["success"] and out["chance"] == "50%" and game.wanted == 16   # hard 35% + 칼 15%, 20×1.3×0.6
    assert "error" in call(game, "attempt_action", action="또", difficulty="easy", crime="none",
                           witnessed="none", violent=False, item="", stealth=False)    # 한 턴에 한 번
    got = call(game, "acquire_vehicle", kind="truck", name="화물 트럭")
    assert got["success"] and game.vehicle["stolen"] and game.offer is None
    titles = [n["title"] for n in gamemaster.collect_notices(game)]
    assert any(t.startswith("🎲") and "성공" in t for t in titles) and any(t.startswith("🚙") for t in titles)

    game.begin_turn()                                                # 야생에서도 운전해서 갈 수 있다
    fuel, before = game.vehicle["range_km"], game.distance
    out = call(game, "travel", method="drive", distance_km=200)
    assert out["success"] and before - game.distance == pytest.approx(200, abs=3)
    assert game.vehicle["range_km"] == fuel - 200 and game.money == 50


def test_failed_attack_hurts_and_raises_wanted(game, monkeypatch):
    game.begin_turn()
    fix_roll(monkeypatch, 0.99)                                      # 주사위: 실패
    out = call(game, "attempt_action", action="기사를 제압한다", difficulty="very_hard",
               crime="폭행", witnessed="bystanders", violent=True, item="", stealth=False)
    assert out["success"] is False and game.health == 70 and game.wanted == 35
    assert call(game, "acquire_vehicle", kind="truck", name="")["success"] is False


def test_chance_modifiers():
    weak = GameState(lat=0, lon=0, place_name="x", weather=fake_weather(), biome="forest",
                     health=30, energy=10, start_hour=23)
    weak.begin_turn = lambda: None
    weak.turn_flags = {}
    random.seed(0)
    out = weak.attempt("창고에 몰래 들어간다", "normal", crime="주거·건물 침입", witnessed="none",
                       violent=False, item="", stealth=True)
    assert out["chance"] == "40%"                                     # 60 - 15 - 15 + 10(밤)


def test_drive_runs_out_of_fuel_and_blocks_at_sea(game, monkeypatch):
    game.begin_turn()
    game.vehicle = {"kind": "car", "name": "낡은 승용차", "speed": 70, "range_km": 100, "sea": False, "stolen": False}
    out = call(game, "travel", method="drive", distance_km=500)
    assert out["success"] and game.vehicle is None and "연료" in out["message"]

    game.begin_turn()
    game.vehicle = {"kind": "car", "name": "차", "speed": 70, "range_km": 300, "sea": False, "stolen": False}
    monkeypatch.setattr(geo, "is_land", lambda lat, lon: False)
    assert call(game, "travel", method="drive", distance_km=100)["success"] is False
    game.vehicle["kind"], game.vehicle["sea"] = "boat", True           # 보트는 바다를 건넌다
    assert call(game, "travel", method="drive", distance_km=100)["success"]


def test_wanted_consequences(game, monkeypatch):
    game.begin_turn()
    game.place_type, game.money, game.wanted = "도시", 3000, 80
    game.vehicle = {"kind": "car", "name": "훔친 차", "speed": 70, "range_km": 300, "sea": False, "stolen": True}
    assert call(game, "buy_ticket", method="flight", distance_km=1)["success"]
    game.flags["at_airport"] = True
    fix_roll(monkeypatch, 0.1)                                       # 0.1 < 0.8 → 공항에서 붙잡힘
    hours = game.elapsed_hours
    out = call(game, "travel", method="flight", distance_km=1)
    assert out["arrested"] and game.status == "playing"
    assert game.vehicle is None and game.tickets == [] and not any("항공권" in i for i in game.items)
    assert game.elapsed_hours - hours == 24 and game.wanted < 40 and game.money < 2000

    game.wanted = 60                                                 # 수배 중이면 도시에서 경찰 이벤트
    game.offer, game.last_major_turn = None, game.turn + 100
    fix_roll(monkeypatch, 0.0)
    game.begin_turn()
    assert game.event and "경찰" in game.event["text"]

    game.wanted = 30
    game.pass_time(5, "rest")
    assert game.wanted == pytest.approx(28.5)                        # 시간이 지나면 내려간다
    game.wanted = 0
    assert call(game, "arrest", reason="검문")["success"] is False    # 수배가 없으면 체포도 없다



# ---------- 8차 수정: 상황에 맞는 이벤트 / 범죄·목격자 / 돈 / 낮밤 기온 ----------
from survival import events as events_module  # noqa: E402


def ctx(**kw):
    base = {"night": False, "indoor": False, "weather": "clear", "temp": 15, "season": "여름"}
    base.update(kw)
    return base


def test_events_follow_place_time_weather():
    texts = lambda *a, **k: {e["text"] for e in events_module.candidates(*a, **k)}  # noqa: E731
    wild_night = texts("야생", "savanna", ctx(night=True))
    assert any("사자" in s for s in wild_night) and not any("코끼리" in s for s in wild_night)
    assert not any("경찰" in s or "소매치기" in s for s in wild_night)          # 야생에는 사람 이벤트 없음
    city = texts("도시", "desert", ctx())
    assert any("소매치기" in s for s in city) and not any("전갈" in s or "사자" in s for s in city)
    assert not texts("도시", "desert", ctx(night=True)) & {s for s in city if "소매치기" in s}
    assert any("와디" in s for s in texts("야생", "desert", ctx(weather="rain")))
    assert not any("와디" in s for s in texts("야생", "desert", ctx(weather="clear")))
    assert any("밤과 도토리" in s for s in texts("야생", "forest", ctx(season="가을")))
    assert not any("밤과 도토리" in s for s in texts("야생", "forest", ctx(season="봄")))
    assert any("열사병" in s for s in texts("야생", "desert", ctx(temp=40)))
    assert not any("열사병" in s for s in texts("야생", "desert", ctx(temp=20)))
    cave = texts("야생", "snow", ctx(indoor=True, weather="snow"))
    assert any("지붕" in s for s in cave) and not any("늑대" in s for s in cave)
    for place in ("야생", "마을", "도시"):
        for biome in ("snow", "alpine", "desert", "jungle", "savanna", "forest"):
            for night in (False, True):
                for indoor in (False, True):
                    assert len(events_module.candidates(place, biome, ctx(night=night, indoor=indoor))) >= 3


def test_roll_event_uses_context():
    rng = random.Random(2)
    seen = [events_module.roll_event("jungle", "야생", 2, rng, ctx(night=True, weather="rain"))
            for _ in range(200)]
    texts = {e["text"] for e in seen if e}
    assert texts and all(events_module.matches(next(x for x in events_module.EVENTS if x["text"] == s),
                                                "야생", "jungle", ctx(night=True, weather="rain")) for s in texts)


def test_wanted_only_for_witnessed_crimes(game, monkeypatch):
    fix_roll(monkeypatch, 0.0)                                       # 성공
    game.begin_turn()
    game.attempt("늑대를 칼로 쫓아낸다", "hard", crime="none", witnessed="bystanders", violent=True)
    assert game.wanted == 0                                          # 범죄가 아니면 수배 없음
    game.begin_turn()
    out = game.attempt("잠든 사이 지갑을 훔친다", "normal", crime="절도", witnessed="none")
    assert game.wanted == 0 and "목격자 없음" in out["엔진이_적용한_결과"][0]
    game.begin_turn()
    game.attempt("시장에서 빵을 훔친다", "normal", crime="절도", witnessed="bystanders")
    assert game.wanted == 16                                         # 20 × 0.8 × 1.0
    game.begin_turn()
    game.attempt("버스 무임승차", "easy", crime="무임승차", witnessed="victim")
    assert game.wanted == 16 + 5                                     # 20 × 0.4 × 0.6 = 4.8 → 5
    fix_roll(monkeypatch, 0.99)                                      # 실패하면 아무도 없었어도 들킨다
    game.begin_turn()
    game.attempt("창고 자물쇠를 딴다", "hard", crime="주거·건물 침입", witnessed="none")
    assert game.wanted == 21 + 13                                    # 35 × 0.6 × 0.6 = 12.6 → 13


def test_pay_and_auto_charge(game, monkeypatch):
    game.begin_turn()
    assert call(game, "pay", amount=8, purpose="생수 2병")["success"] and game.money == 42
    assert call(game, "pay", amount=100, purpose="숙박")["success"] is False and game.money == 42
    assert gamemaster.auto_charge(game, "당신은 $5를 내고 빵을 산다.") == 0      # 이미 냈으면 중복 차감 없음

    game.begin_turn()                                               # GM이 pay 를 빠뜨린 경우
    assert gamemaster.auto_charge(game, "주인에게 $12를 건네고 방 열쇠를 받는다.") == 12 and game.money == 30
    game.begin_turn()
    assert gamemaster.auto_charge(game, "노인이 당신에게 $20를 주었다.") == 0     # 받은 돈은 차감하지 않음
    assert gamemaster.auto_charge(game, "15달러를 지불했다") == 15 and game.money == 15
    game.end_turn(0.5)
    assert game.delta["money"] == -15                               # 상태창에도 -15 로 표시된다

    reply = SimpleNamespace(id="r", output=[], output_text="당신은 $7를 내고 물 한 병을 산다.")
    monkeypatch.setattr(gamemaster, "get_client",
                        lambda: SimpleNamespace(responses=SimpleNamespace(create=lambda **k: reply)))
    gamemaster.run_turn(game, "물을 산다")
    assert game.money == 8


def test_temperature_follows_time_of_day(game):
    game.start_hour, game.start_offset, game.utc_offset, game.elapsed_hours = 12, 0, 0, 0
    profile = [{"hour": (12 + i) % 24, "temperature": 20 + 10 * math.cos(2 * math.pi * ((12 + i) % 24 - 15) / 24),
                "feels_like": 20.0} for i in range(30)]
    game.set_weather(fake_weather(22, hourly=profile, utc_offset=0))
    noon = game.weather["temperature"]
    game.pass_time(12, "rest")                                       # 자정
    midnight = game.weather["temperature"]
    assert game.hour == 0 and midnight < noon - 10
    for _ in range(2):                                               # 예보(30시간)를 넘어가도 낮밤이 반복된다
        game.satiety = game.hydration = game.health = 100
        game.pass_time(12, "rest")
    assert game.hour == 0 and game.weather["temperature"] == pytest.approx(midnight)


def test_diurnal_curve_without_forecast(game):
    game.biome = "desert"
    game.start_hour, game.elapsed_hours = 15, 0
    game.set_weather(fake_weather(40, humidity=10, hourly=[]))
    assert game.weather["temperature"] == pytest.approx(40)          # 오후 3시 최고
    game.pass_time(12, "rest")                                       # 새벽 3시
    assert game.hour == 3 and game.weather["temperature"] == pytest.approx(40 - 2 * 11)


def test_clock_switches_to_local_time_zone(game):
    game.start_hour, game.start_offset, game.utc_offset, game.elapsed_hours = 10, 1, 1, 0
    profile = [{"hour": (17 + i) % 24, "temperature": 5.0, "feels_like": 5.0} for i in range(48)]
    game.set_weather(fake_weather(5, hourly=profile, utc_offset=8))   # 시차 +7시간 지역으로 이동
    assert game.hour == 17 and game.is_night is False
    game.pass_time(3, "rest")
    assert game.hour == 20 and game.is_night



def test_positive_events_everywhere():
    """어떤 상황에서도 그 상황에 맞는 긍정 이벤트가 3개 이상 있어야 한다."""
    for place in ("야생", "마을", "도시"):
        for biome in ("snow", "alpine", "desert", "jungle", "savanna", "forest"):
            for night in (False, True):
                for indoor in (False, True):
                    for weather in ("clear", "rain", "snow", "storm", "fog"):
                        for temp in (-10, 15, 35):
                            c = ctx(night=night, indoor=indoor, weather=weather, temp=temp)
                            lucky = [e for e in events_module.candidates(place, biome, c) if e["kind"] == "lucky"]
                            assert len(lucky) >= 3, (place, biome, c)
    texts = [e["text"] for e in events_module.EVENTS]
    assert len(texts) == len(set(texts))                             # 중복 이벤트 없음



# ---------- 9차 수정: 한국어 서술 ----------
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


# ---------- 10차 수정: 이야기의 개연성 / 목적지가 있는 이동 ----------
from survival import leads as leads_module, places  # noqa: E402


def test_clue_event_creates_lead_and_following_finds_it(game, monkeypatch):
    game.turn = 1
    monkeypatch.setattr(state_module, "roll_event",
                        lambda *a, **k: {"kind": "lucky", "text": "멀리서 엔진 소리가 들린다.", "lead": "engine"})
    game.begin_turn()
    lead = game.leads[0]
    assert game.event["lead_id"] == lead["id"] and game.event["direction"] == lead["direction"]
    assert game.event["text"] == "멀리서 엔진 소리가 들린다."                  # 이벤트 문구는 그대로
    titles = [n["title"] for n in gamemaster.collect_notices(game)]
    assert len([x for x in titles if "엔진 소리" in x]) == 1 and titles[0].startswith("🧭")   # 알림은 하나로
    assert any("엔진 소리" in f["text"] for f in game.facts)               # 이벤트는 사실로 남는다
    text = gamemaster.build_input(game, "엔진 소리 쪽으로 간다")
    assert "[단서" in text and lead["id"] in text and "[확정된 사실" in text
    assert lead["target"] not in text                                     # 정체는 미리 알려 주지 않는다

    game.turn_flags["travel"] = 0
    start, hours = (game.lat, game.lon), game.elapsed_hours
    out = call(game, "follow_lead", lead_id=lead["id"].lower())
    assert out["success"] and not game.leads
    assert geo.haversine_km(*start, game.lat, game.lon) == pytest.approx(lead["km"], abs=0.2)   # 정해 둔 거리
    assert game.elapsed_hours > hours                                      # 걸어간 시간이 흐른다
    expected = {"road": "도로", "village": "마을 입구", "logging": "벌목장"}[lead["target"]]
    assert expected in game.scene_place and game.scene_dirty               # 정해 둔 정체가 나타나고 그림도 바뀐다
    assert any("정체를 확인함" in f["text"] for f in game.facts)
    assert any(n["title"].startswith("🔎") for n in gamemaster.collect_notices(game))


def test_lead_target_is_fixed_and_fits_biome():
    rng = random.Random(5)
    for _ in range(200):
        assert leads_module.make_lead("engine", "x", "desert", rng)["target"] != "logging"   # 사막에 벌목장은 없다
        assert leads_module.make_lead("smoke", "x", "snow", rng)["target"] != "wildfire"
    lead = leads_module.make_lead("light", "불빛", "forest", random.Random(1))
    day = leads_module.reveal(dict(lead, target="village"), "forest", night=False, rng=random.Random(1))
    night = leads_module.reveal(dict(lead, target="village"), "forest", night=True, rng=random.Random(1))
    assert "오가고" in day["text"] and "잠들었" in night["text"]                 # 도착 시각에 따라 모습이 다르다
    assert day["text"].startswith("불빛을 따라가자")
    assert leads_module.eul("엔진 소리") == "엔진 소리를"                 # 도착 시각에 따라 모습이 다르다
    road = leads_module.reveal(dict(lead, target="road"), "forest", night=True, rng=random.Random(1))
    assert "거의 다니지 않는다" in road["text"] and "on_road" in road["effects"]
    camp = leads_module.reveal(dict(lead, target="camp"), "desert", night=False)
    assert camp["scene"] == "유목민 천막"                                       # 지형에 맞는 캠프


def test_gm_added_lead_and_facts_persist_until_leaving(game):
    game.begin_turn()
    game.leads, game.facts = [], []                                # 턴 시작 때 무작위로 생긴 단서·사실은 빼고
    out = call(game, "add_lead", kind="herd", clue="언덕 너머에서 양 떼 방울 소리")
    lead_id = out["단서"].split()[0]
    assert game.find_lead(lead_id) and call(game, "add_lead", kind="herd", clue="언덕 너머에서 양 떼 방울 소리")
    assert len(game.leads) == 1                                            # 같은 단서는 한 번만
    call(game, "remember", fact="여관 주인은 내일 아침 6시에 트럭이 떠난다고 했다", scope="here")
    call(game, "remember", fact="한국인 김씨에게 연락처를 받았다", scope="always")
    assert len(game.facts) == 2
    game.begin_turn()
    call(game, "travel", method="hitchhike", distance_km=200) if False else game._relocate(*geo.move_toward_korea(game.lat, game.lon, 200), 200, "bus")
    assert game.leads == [] and [f["text"] for f in game.facts] == ["한국인 김씨에게 연락처를 받았다"]


def test_road_makes_hitchhiking_easier(game, monkeypatch):
    game.flags["on_road"] = True
    fix_roll(monkeypatch, 0.80)                         # 숲 야생 기본 60% → 도로 위 85%
    game.begin_turn()
    assert game.travel("hitchhike", 100)["success"]


def test_ride_offers_go_to_real_places_not_just_toward_korea(game):
    from survival.events import MAJOR_EVENTS

    def plan(offer_id, state):
        e = next(x for x in MAJOR_EVENTS if x["id"] == offer_id)
        return state.plan_offer({"id": offer_id, "text": e["text"], "accept": e["accept"], "hours": 0, "stats": {},
                                 "items": [], "money": 0, "risk": "", "bad": dict(e["bad"]), "move": dict(e["move"])})

    # 알래스카 야생 → 구조 헬기는 가까운 도시(페어뱅크스)로. 한국 쪽이 아니다
    alaska = GameState(lat=64.5, lon=-147.0, place_name="알래스카", weather=fake_weather(), biome="snow",
                       distance=geo.distance_to_korea(64.5, -147.0))
    offer = plan("rescue", alaska)
    assert offer["dest"]["name"] == "페어뱅크스" and "페어뱅크스" in offer["text"] and "km" in offer["detail"]
    # 도시가 멀면 근처 마을로
    remote = GameState(lat=20.0, lon=0.0, place_name="사하라", weather=fake_weather(), biome="desert",
                       distance=geo.distance_to_korea(20.0, 0.0))
    offer = plan("rescue", remote)
    assert offer["dest"]["place"] == "마을" and 30 <= offer["dest"]["km"] <= 120


def test_embassy_then_airport_flow(game, monkeypatch):
    """마을에서 공관으로 → 귀국 지원 → 공항 → 귀국. 플레이어가 원하면 턴마다 바로 진행된다."""
    monkeypatch.setattr(state_module.random, "random", lambda: 0.99)   # 기회의 나쁜 결과가 나오지 않게
    game.place_type, game.country_code, game.money = "마을", "mn", 30
    game.begin_turn()
    out = call(game, "go_to", target="embassy")                              # 1턴: 공관이 교통편 마련, 바로 이동
    assert out["success"] and game.flags["embassy_visited"] and game.flags["at_embassy"]
    assert "울란바토르" in game.place_name and game.indoor and "공관" in game.scene_place
    assert "여행증명서" in game.items and game.place_type == "도시"
    assert any(f["scope"] == "always" and "영사 지원" in f["text"] for f in game.facts)

    game.begin_turn()                                                        # 2턴: 귀국 지원
    money = game.money
    out = call(game, "seek_help", kind="repatriation")
    assert out["success"] and game.find_ticket("flight") and game.money == money    # 소지금은 그대로
    assert any(n["title"].startswith("🎫 귀국 항공권") for n in gamemaster.collect_notices(game))

    game.begin_turn()                                                        # 3턴: 공항으로
    out = call(game, "go_to", target="airport")
    assert out["success"] and game.flags["at_airport"] and "공항" in game.scene_place

    game.begin_turn()                                                        # 4턴: 탑승
    out = call(game, "travel", method="flight", distance_km=1)
    assert out["arrived_in_korea"] and game.status == "won" and game.money == money


def test_no_teleport_from_the_wild(game, monkeypatch):
    """오지에서 공관을 찾아도 공관에 순간이동하지 않는다. 전화가 되면 통화만 하고, 먼저 마을로 간다."""
    game.biome, game.place_type, game.country_code = "snow", "야생", "mn"
    game.begin_turn()
    start = (game.lat, game.lon)
    out = call(game, "go_to", target="embassy")
    assert out["success"] and "연락할 방법이 없다" in out["message"]
    assert not game.flags.get("embassy_visited") and game.place_type in ("야생", "마을")
    assert game.journey is None or game.journey["type"] == "village"
    moved = geo.haversine_km(*start, game.lat, game.lon)
    assert 0 < moved <= 2.5 * 10 + 0.5                                       # 설원 도보 2.5km/h × 최대 10시간

    game2 = GameState(lat=46.9, lon=103.8, place_name="몽골", weather=fake_weather(), biome="forest",
                      distance=geo.distance_to_korea(46.9, 103.8), country_code="mn")
    game2.flags["can_call"] = True                                           # 신호가 잡히는 언덕
    game2.begin_turn()
    out = game2.go_to("embassy")
    assert "통화" in out["message"] and game2.flags["embassy_contacted"] and not game2.flags.get("embassy_visited")
    assert any("교통편을 마련" in f["text"] for f in game2.facts)


def test_long_walk_takes_several_turns(game, monkeypatch):
    game.biome, game.place_type = "snow", "야생"
    monkeypatch.setattr(state_module.random, "uniform", lambda a, b: b if b > 50 else 0)   # 마을까지 70km, 정면 방향
    game.begin_turn()
    out = call(game, "go_to", target="village")
    assert out["도착"] is False and game.journey and game.place_type == "야생"
    assert "[현재 상태]" in gamemaster.build_input(game, "계속 간다") and "진행_중인_여정" in gamemaster.build_input(game, "x")
    assert "error" in call(game, "go_to", target="continue")               # 한 턴에 한 번
    for _ in range(4):
        game.health = game.satiety = game.hydration = game.energy = 100
        game.begin_turn()
        out = call(game, "go_to", target="continue")
        if out.get("도착"):
            break
    assert out["도착"] and game.place_type == "마을" and game.journey is None and "마을" in game.scene_place


def test_village_uses_known_lead(game, monkeypatch):
    game.begin_turn()
    game.leads = []                                                # 턴 시작 때 무작위로 생긴 단서는 빼고
    lead = game.add_lead("settlement", "계곡 아래 마을 지붕")
    assert lead["target"] == "village"
    game.turn_flags["travel"] = 0
    out = call(game, "go_to", target="village")
    assert out["success"] and game.place_type == "마을" and not game.leads    # 알고 있는 마을로 간다


def test_city_trip_by_bus_and_airport_needs_a_city(game, monkeypatch):
    game.place_type, game.money = "마을", 100
    game.begin_turn()
    out = call(game, "go_to", target="airport")                              # 마을에서 공항 → 먼저 도시로
    assert "먼저 도시로" in out["message"] and out["수단"] == "버스" and game.money < 100
    assert out["도착"] and game.place_type == "도시" and "울란바토르" in game.place_name

    broke = GameState(lat=46.9, lon=103.8, place_name="몽골", weather=fake_weather(), biome="forest",
                      place_type="마을", money=0, distance=geo.distance_to_korea(46.9, 103.8))
    monkeypatch.setattr(state_module.random, "random", lambda: 0.99)          # 차비가 없으면 히치하이킹, 실패
    broke.begin_turn()
    assert "태워 주는 차가 없었다" in broke.go_to("city")["message"]


def test_drive_to_city_with_vehicle(game):
    game.vehicle = {"kind": "truck", "name": "트럭", "speed": 60, "range_km": 700, "sea": False, "stolen": False}
    game.begin_turn()
    out = call(game, "go_to", target="city")
    assert out["수단"] == "트럭" and out["도착"] and game.place_type == "도시" and game.vehicle["range_km"] < 700


def test_airport_blocked_early_without_embassy(game):
    game.place_type, game.money = "도시", 3000
    game.begin_turn()
    assert call(game, "go_to", target="airport")["success"] is False         # 1일차·공관 전에는 공항 불가
    assert game.travel("flight", 1)["success"] is False                      # 비행기도 탈 수 없다
    assert call(game, "seek_help", kind="repatriation")["success"] is False  # 공관 밖에서는 귀국 지원 불가


def test_airport_opens_after_enough_days(game):
    game.place_type = "도시"
    assert "airport" not in game.offer_needs()
    game.elapsed_hours = 24 * 5
    assert "airport" in game.offer_needs()
    game.place_type = "마을"
    assert "airport" not in game.offer_needs()


def test_city_data_is_sane():
    assert len(places.CITY_LIST) > 200
    for c in places.CITY_LIST:
        assert -60 < c["lat"] < 75 and -180 <= c["lon"] <= 180 and c["mission"] in ("", "대", "영")
    near = places.nearest_city(-23.9, 133.5)
    assert near["name"] == "앨리스스프링스" and near["km"] < 50
    assert places.nearest_city(20.0, 0.0, max_km=100) is None



# ---------- 11차 수정: 같은 장소·같은 사람 / 귀국을 끌지 않기 ----------
def test_same_place_keeps_description_and_people(game):
    game.set_scene("indoor", "한국 공관 영사과", "Inside a consular office with a counter and a Korean flag.",
                   ["민원 창구", "태극기"])
    game.scene_dirty = False
    first_desc = game.scene_desc
    assert game.add_character("김민수 영사", "영사과 담당 영사", "40대, 회색 양복, 안경")["look"] == "40대, 회색 양복, 안경"
    # 같은 곳을 다른 말로 다시 설정해도 묘사·그림·인물은 그대로
    assert call(game, "set_scene", setting="indoor", place="영사과 창구",
                description_en="A totally different modern lobby.", visible_features=["대기 번호표"])["장면이_바뀜"] is False
    assert game.scene_desc == first_desc and not game.scene_dirty and game.scene_place == "한국 공관 영사과"
    assert "대기 번호표" in game.scene_features                              # 새로 보이는 것은 덧붙인다
    person = game.add_character("박 영사", "영사과 담당 영사", "20대, 청바지")  # 같은 역할 → 같은 사람
    assert person["name"] == "김민수 영사" and len(game.characters) == 1
    text = gamemaster.build_input(game, "영사에게 묻는다")
    assert "[등장인물" in text and "김민수 영사" in text and "[지금 장면" in text

    assert call(game, "set_scene", setting="outdoor", place="공관 앞 거리",
                description_en="A city street.", visible_features=[])["장면이_바뀜"]    # 밖으로 나가면 바뀐다
    assert game.scene_dirty and game.characters == [] and not game.flags.get("at_embassy")


def test_night_does_not_change_the_scene(game):
    game.set_scene("outdoor", "강가", "A riverbank.", ["강"])
    game.scene_dirty = False
    game.begin_turn()
    game.pass_time(10, "rest")
    game.end_turn(0)
    assert not game.scene_dirty                                              # 낮밤이 바뀌어도 장면은 그대로


def load_app(monkeypatch):
    import importlib
    from unittest.mock import MagicMock
    fake = MagicMock()
    fake.update = lambda **k: k
    monkeypatch.setitem(sys.modules, "gradio", fake)
    sys.modules.pop("app", None)
    return importlib.import_module("app")


def test_image_update_modes(game, monkeypatch):
    app = load_app(monkeypatch)
    game.set_scene("outdoor", "강가", "A riverbank.", ["강"])
    assert app.image_update(game) == "new"                                   # 처음
    game.image_path, game.scene_dirty = "/tmp/a.png", False
    game.image_scene, game.image_night = app.scene_key(game), game.is_night
    game.image_weather = imagegen.weather_category(game.weather.get("code", 0))
    assert app.image_update(game) is None                                    # 그대로
    game.image_night = not game.is_night
    assert app.image_update(game) == "edit"                                  # 야외의 낮밤 변화 → 편집
    game.set_scene("indoor", "어부 오두막 안", "Inside a hut.", ["난로"])
    assert app.image_update(game) == "new"                                   # 장면이 바뀌면 새로
    game.scene_dirty, game.image_scene = False, app.scene_key(game)
    game.image_night = not game.is_night
    assert app.image_update(game) is None                                    # 실내는 낮밤으로 다시 그리지 않는다


def test_edit_keeps_composition(game):
    game.weather.update(code=63)
    game.start_hour, game.elapsed_hours = 6, 0
    prompt = imagegen.build_edit_prompt(game)
    assert "Keep the exact same camera angle" in prompt and "nothing new" in prompt
    assert "dawn" in prompt and "raining" in prompt
    calls = {}

    def fake_edit(**kw):
        calls.update(kw)
        import base64
        return SimpleNamespace(data=[SimpleNamespace(b64_json=base64.b64encode(b"png").decode())])

    client = SimpleNamespace(images=SimpleNamespace(edit=fake_edit))
    import tempfile
    prev = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    prev.write(b"old")
    prev.close()
    path = imagegen.edit_scene(client, game, prev.name)
    assert path and calls["prompt"] == imagegen.build_edit_prompt(game)
    assert imagegen.edit_scene(client, game, "/없는/파일.png") is None         # 실패하면 이전 그림 유지



# ---------- 12차 수정: 그림 속 글자는 현지 언어로 ----------
def test_image_prompt_has_no_hangul_and_uses_local_language(game):
    game.place_name, game.place_name_en = "오스트레일리아, 노던 준주", "Australia, Northern Territory"
    game.country_code, game.country_en = "au", "Australia"
    game.set_scene("outdoor", "도로변 표지판 앞", "A red dirt road with a road sign, spinifex grass.",
                   ["도로 표지판", "붉은 흙길"])
    prompt = imagegen.build_prompt(game)
    assert not imagegen.HANGUL.search(prompt)
    assert "Australia, Northern Territory" in prompt and "written in English" in prompt and "Never use Korean" in prompt
    edit = imagegen.build_edit_prompt(game)
    assert not imagegen.HANGUL.search(edit) and "written in English" in edit

    game.country_code, game.country_en, game.place_name_en = "mn", "Mongolia", ""
    game.scene_desc = "A steppe with a 게르 and a sign."                   # GM이 실수로 한글을 섞어도
    prompt = imagegen.build_prompt(game)
    assert not imagegen.HANGUL.search(prompt) and "Mongolian (Cyrillic)" in prompt
    assert "latitude 46.9, longitude 103.8" in prompt                    # 영어 지명이 없으면 좌표로


def test_indoor_prompt_has_no_hangul(game):
    game.country_code, game.country_en = "th", "Thailand"
    game.set_scene("indoor", "한국 공관 영사과", "Inside a consular office: a counter and a Korean flag.", ["태극기"])
    prompt = imagegen.build_prompt(game)
    assert not imagegen.HANGUL.search(prompt) and "written in Thai" in prompt


def test_reverse_geocode_returns_korean_and_english(monkeypatch):
    answers = {"ko": {"address": {"country": "오스트레일리아", "state": "노던 준주", "country_code": "AU"}},
               "en": {"address": {"country": "Australia", "state": "Northern Territory", "country_code": "AU"}}}

    def fake_get(url, params=None, **kw):
        return SimpleNamespace(json=lambda: answers[params["accept-language"]])

    monkeypatch.setattr(geo.requests, "get", fake_get)
    monkeypatch.setattr(geo.time, "sleep", lambda s: None)
    place = geo.reverse_geocode(-23.7, 133.9)
    assert place["name"] == "오스트레일리아, 노던 준주" and place["country_code"] == "au"
    assert place["name_en"] == "Australia, Northern Territory" and place["country_en"] == "Australia"


def test_every_city_country_has_a_sign_language():
    from survival.languages import SIGN_LANGUAGE
    assert {c["country"] for c in places.CITY_LIST} <= set(SIGN_LANGUAGE)


def test_season_wording_fits_barren_climates():
    assert climate.make_climate("desert", -23.9, 11)["season_en"] == "spring"
    assert "green" in climate.make_climate("temperate", 37, 4)["season_en"]


# ---------- 13차 수정: 행동의 결과 반영 / 초반 제한 ----------
def test_theft_reward_is_applied_by_engine(game, monkeypatch):
    fix_roll(monkeypatch, 0.0)                                       # 성공
    game.begin_turn()
    out = call(game, "attempt_action", action="옆 사람의 지갑을 훔친다", difficulty="normal", crime="절도",
               witnessed="none", violent=False, item="", stealth=True, success_money=320,
               success_items=["가죽 지갑", "픽업트럭"])
    assert out["success"] and game.money == 50 + 320 and "가죽 지갑" in game.items
    assert not any("트럭" in i for i in game.items) and out["거부된_물건"]       # 탈것은 소지품이 아니다
    assert any("+$320" in n["text"] for n in gamemaster.collect_notices(game))
    game.end_turn(0.5)
    assert game.delta["money"] == 320                                # 상태창에도 +320

    fix_roll(monkeypatch, 0.99)                                      # 실패하면 아무것도 얻지 못한다
    game.begin_turn()
    game.attempt("금고를 턴다", "hard", crime="절도", witnessed="none", success_money=500)
    assert game.money == 370


def test_vehicles_never_enter_inventory(game):
    game.begin_turn()
    out = call(game, "update_inventory", remove=[], add=[
        {"name": "트럭 기사의 화물 트럭", "carryable": True}, {"name": "오토바이", "carryable": True},
        {"name": "낙타", "carryable": True}, {"name": "트럭 열쇠", "carryable": True}])
    assert len(out["거부된_물건"]) == 3 and "acquire_vehicle" in out["거부된_물건"][0]
    assert game.items[-1] == "트럭 열쇠"                              # 열쇠는 들고 다닐 수 있다


def test_money_from_narration_is_applied(game):
    game.begin_turn()
    assert gamemaster.auto_money(game, "지갑 안에는 $280가 들어 있었고, 당신은 그 돈을 챙겼다.") == 280
    assert game.money == 330
    game.begin_turn()
    assert gamemaster.auto_money(game, "소매치기에게 $40를 빼앗겼다.") == -40 and game.money == 290
    game.begin_turn()
    call(game, "update_status", health=0, satiety=0, hydration=0, energy=0, money=50,
         consumed_items=[], reason="일당")
    assert gamemaster.auto_money(game, "일당으로 $50를 받았다.") == 0 and game.money == 340   # 이미 반영됨
    game.begin_turn()
    assert gamemaster.auto_money(game, "$5000를 주웠다") == 600                               # 상한


def test_early_game_keeps_you_near_the_drop(game, monkeypatch):
    monkeypatch.setattr(state_module, "EARLY_GAME_HOURS", 36)
    game.place_type, game.money, game.country_code = "마을", 3000, "mn"
    game.begin_turn()
    assert game.early and "초반_제한" in gamemaster.build_input(game, "x") and "36시간" in game.summary()["초반_제한"]
    for target in ("city", "embassy", "airport"):
        out = call(game, "go_to", target=target)
        assert out["success"] is False and "벗어날 방법" in out["message"]
    assert game.travel("train", 500)["success"] is False
    before = game.distance
    assert game.travel("bus", 500)["success"] and before - game.distance <= 61    # 초반에는 짧게
    assert game.place_type != "도시"                                            # 도시에는 닿지 않는다
    assert game.offer_needs() == ()

    from survival.events import MAJOR_EVENTS
    e = next(x for x in MAJOR_EVENTS if x["id"] == "trucker")
    offer = game.plan_offer({"id": "trucker", "text": e["text"], "accept": e["accept"], "hours": 0, "stats": {},
                             "items": [], "money": 0, "risk": "", "bad": dict(e["bad"]), "move": dict(e["move"])})
    assert offer["dest"]["place"] == "마을" and offer["dest"]["km"] <= 60       # 트럭도 근처 마을까지만

    wild = GameState(lat=46.9, lon=103.8, place_name="몽골", weather=fake_weather(), biome="forest",
                     distance=geo.distance_to_korea(46.9, 103.8))
    wild.begin_turn()
    out = wild.go_to("city")                                                    # 야생에서는 마을까지는 간다
    assert out["success"] and "가장 가까운 마을로" in out["message"]

    game.elapsed_hours = 40                                                     # 하루 반이 지나면 풀린다
    assert not game.early and "contact" in game.offer_needs()


# ---------- 14차 수정: 서술·그림·위치의 일치 ----------
def test_looking_for_shelter_does_not_move_to_a_village(game, monkeypatch):
    """'쉴 곳을 찾아 이동한다'를 GM이 마을 이동으로 처리하려 해도 엔진이 막는다 (브라질 초원 사례)."""
    game.biome, game.place_type = "savanna", "야생"
    game.set_scene("outdoor", "초원 한가운데", "Open savanna grassland.", ["키 큰 풀"])
    game.add_lead("smoke", "멀리 피어오르는 연기")
    calls = []

    def fake_create(**kw):
        calls.append(kw)
        if len(calls) == 1:
            return SimpleNamespace(id="r1", output_text="", output=[
                SimpleNamespace(type="function_call", name="go_to", call_id="a", arguments='{"target": "village"}'),
                SimpleNamespace(type="function_call", name="follow_lead", call_id="b",
                                arguments=json.dumps({"lead_id": game.leads[0]["id"]}))])
        return SimpleNamespace(id="r2", output=[], output_text="당신은 초원의 **나무 그늘**에서 몸을 누인다.")

    monkeypatch.setattr(gamemaster, "get_client",
                        lambda: SimpleNamespace(responses=SimpleNamespace(create=fake_create)))
    start = (game.lat, game.lon)
    game.scene_dirty = False
    gamemaster.run_turn(game, "쉴 곳을 찾아 이동한다")
    results = [json.loads(o["output"]) for o in calls[1]["input"]]
    assert all("error" in r for r in results)                                    # 두 이동 모두 거절
    assert (game.lat, game.lon) == start and game.place_type == "야생" and game.leads   # 그대로
    assert game.scene_place == "초원 한가운데" and not game.scene_dirty            # 그림도 그대로


def test_movement_allowed_when_player_says_so(game):
    game.place_type = "야생"
    game.begin_turn()
    game.turn_flags["player_text"] = "가장 가까운 마을로 간다"
    assert tools_module.player_asked_for(game, "go_to", {"target": "village"})
    assert not tools_module.player_asked_for(game, "go_to", {"target": "city"})
    lead = game.add_lead("engine", "멀리서 엔진 소리가 들린다.")
    game.turn_flags["player_text"] = "엔진 소리 쪽으로 간다"
    assert tools_module.player_asked_for(game, "follow_lead", {"lead_id": lead["id"]})
    game.turn_flags["player_text"] = f"{lead['direction']}으로 걸어간다"
    assert tools_module.player_asked_for(game, "follow_lead", {"lead_id": lead["id"]})
    game.turn_flags["player_text"] = "물을 찾는다"
    assert not tools_module.player_asked_for(game, "follow_lead", {"lead_id": lead["id"]})
    game.turn_flags["player_text"] = "계속 간다"
    assert tools_module.player_asked_for(game, "go_to", {"target": "continue"})


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


def test_location_bar_separates_terrain_and_place(game):
    from survival.ui import render_location
    game.place_type = "마을"
    html = render_location(game)
    assert "지형: " in html and "장소: 마을" in html


# ---------- 15차 수정: 요청하지 않은 장소 변화를 원천 차단 ----------
LOCAL_ACTIONS = [
    "다시 돌아가 덜 젖은 곳을 찾는다", "쉴 곳을 찾아 이동한다", "주변을 둘러본다", "나무 아래로 옮긴다",
    "물을 찾아 돌아다닌다", "근처 바위 쪽으로 이동한다", "비를 피할 곳을 찾는다", "자리를 옮긴다",
    "불을 피운다", "그늘로 이동한다", "언덕 위로 올라가 본다", "조금 걸어 본다", "근처를 탐색한다",
    "사람의 흔적을 찾는다", "나뭇가지로 쉼터 집을 짓는다", "잠깐 앉아서 쉰다", "네, 좀 더 걸어 볼게",
    "좋아, 주변을 살펴보자", "돌아가서 다시 찾아본다", "물가 쪽으로 가 본다", "출발 전에 물을 챙긴다",
    "떠나기 전에 불을 끈다", "계속 주변을 살핀다", "이어서 장작을 모은다", "마저 먹는다",
]
MOVE_CALLS = [
    ("travel", {"method": "walk", "distance_km": 4}), ("travel", {"method": "walk", "distance_km": 30}),
    ("travel", {"method": "hitchhike", "distance_km": 100}), ("travel", {"method": "bus", "distance_km": 100}),
    ("go_to", {"target": "village"}), ("go_to", {"target": "city"}), ("go_to", {"target": "continue"}),
    ("accept_offer", {}),
]


def test_no_place_change_without_a_requested_move(game, monkeypatch):
    """그 자리 근처에서 움직이는 어떤 입력에도, GM이 어떤 이동 툴을 부르든, 위치·장소는 바뀌지 않는다."""
    fix_roll(monkeypatch, 0.0)                                          # 확률이 걸린 것은 모두 '성공' 쪽으로
    for text in LOCAL_ACTIONS:
        for tool_name, args in MOVE_CALLS + [("follow_lead", None)]:
            game.lat, game.lon, game.place_type, game.money = 46.9, 103.8, "야생", 500
            game.journey = {"type": "village", "name": "마을", "label": "마을", "lat": 47.0, "lon": 104.0, "place": "마을"}
            game.begin_turn()
            game.leads = []
            lead = game.add_lead("smoke", "멀리서 연기가 가늘게 피어오른다.")
            game.offer = {"id": "trucker", "text": "트럭", "accept": "트럭에 올라탄다", "turn": game.turn, "hours": 0,
                          "stats": {}, "items": [], "money": 0, "risk": "", "bad": {"chance": 0},
                          "move": {"to": "city_or_village", "max_km": 500, "speed": 60},
                          "dest": {"type": "city_or_village", "name": "근처 마을", "label": "마을", "lat": 47.2,
                                   "lon": 104.2, "km": 40, "place": "마을"}}
            game.turn_flags["player_text"] = text
            call_args = {"lead_id": lead["id"]} if tool_name == "follow_lead" else args
            out = call(game, tool_name, **call_args)
            assert (game.lat, game.lon, game.place_type) == (46.9, 103.8, "야생"), (text, tool_name, out)


def test_the_reported_case_rain_and_tree(game, monkeypatch):
    """보고된 상황: 비를 피해 나무 아래로 갔을 뿐인데 마을이 됨 → 이제는 장면만 '나무 아래'로 바뀐다."""
    game.biome, game.place_type = "savanna", "야생"
    calls = []

    def fake_create(**kw):
        calls.append(kw)
        if len(calls) == 1:
            return SimpleNamespace(id="r1", output_text="", output=[
                SimpleNamespace(type="function_call", name="travel", call_id="a",
                                arguments='{"method": "walk", "distance_km": 4}')])
        if len(calls) == 2:                                             # 거절당한 GM이 장면만 바꾼다
            return SimpleNamespace(id="r2", output_text="", output=[
                SimpleNamespace(type="function_call", name="advance_time", call_id="b",
                                arguments='{"hours": 1, "activity": "explore", "sheltered": false}'),
                SimpleNamespace(type="function_call", name="set_scene", call_id="c",
                                arguments=json.dumps({"setting": "outdoor", "place": "큰 나무 아래",
                                                      "description_en": "A large tree in the savanna, rain falling.",
                                                      "visible_features": ["큰 나무"]}))])
        return SimpleNamespace(id="r3", output=[], output_text="당신은 **큰 나무** 아래로 몸을 피한다.")

    monkeypatch.setattr(gamemaster, "get_client",
                        lambda: SimpleNamespace(responses=SimpleNamespace(create=fake_create)))
    start = (game.lat, game.lon)
    gamemaster.run_turn(game, "다시 돌아가 덜 젖은 곳을 찾는다")
    assert "error" in json.loads(calls[1]["input"][0]["output"])
    assert (game.lat, game.lon) == start and game.place_type == "야생" and game.scene_place == "큰 나무 아래"


def test_arrival_place_is_rule_based_not_random():
    from survival.travel import arrival_place
    far, near = {"km": 500}, {"km": 10}
    assert arrival_place("walk", far) == "야생" and arrival_place("drive", far) == "야생"
    assert arrival_place("walk", near) == "도시"
    assert arrival_place("hitchhike", far) == "마을" and arrival_place("bus", far) == "마을"
    assert arrival_place("bus", {"km": 25}) == "도시" and arrival_place("train", far) == "도시"
    assert arrival_place("walk", None) == "야생"


def test_long_walk_never_lands_in_a_village(game, monkeypatch):
    places_seen = set()
    for i in range(60):
        game.lat, game.lon, game.place_type = 46.9, 103.8, "야생"
        game.begin_turn()
        game.turn_flags["player_text"] = "남쪽으로 30km 걷는다"
        call(game, "travel", method="walk", distance_km=30)
        places_seen.add(game.place_type)
    assert places_seen == {"야생"}                                        # 걸어서는 우연히 마을에 닿지 않는다


def test_requested_moves_still_work(game, monkeypatch):
    fix_roll(monkeypatch, 0.0)
    game.begin_turn()
    game.turn_flags["player_text"] = "지나가는 차를 세워 히치하이킹한다"
    out = call(game, "travel", method="hitchhike", distance_km=100)
    assert out["success"] and game.place_type == "마을"
    game.begin_turn()
    game.offer = {"id": "news", "text": "기자", "accept": "인터뷰에 응한다", "turn": game.turn, "hours": 1,
                  "stats": {}, "items": [], "money": 100, "risk": "", "bad": {"chance": 0}, "move": {}}
    game.turn_flags["player_text"] = "주변을 살핀다"
    assert "error" in call(game, "accept_offer")                          # 받아들인다고 하지 않았다
    game.turn_flags["player_text"] = "인터뷰에 응한다"
    assert call(game, "accept_offer")["success"]


def test_safety_net_reverts_unrequested_change(game):
    game.begin_turn()
    game.place_type, game.lat = "마을", 50.0                              # 어떤 경로로든 몰래 바뀌었다면
    assert game.guard_unrequested_move() is True
    assert game.place_type == "야생" and game.lat == 46.9
    game.turn_flags["travel"] = 1                                       # 정상적으로 이동한 턴이면 그대로
    game.place_type = "마을"
    assert game.guard_unrequested_move() is False and game.place_type == "마을"


def test_narration_checked_when_place_type_changes(game):
    game.begin_turn()
    game.place_type, game.scene_place = "마을", ""
    out = gamemaster.ensure_scene(None, "당신은 초원을 걷는다.", game)
    assert out.startswith("*📍 지금 위치:") and "마을" in out.splitlines()[0]
    assert gamemaster.ensure_scene(None, "당신은 마을에 들어선다.", game) == "당신은 마을에 들어선다."


def test_long_suggestions_are_not_cut():
    long = "강을 따라 하류로 내려가며 사람이 사는 흔적을 찾는다"
    _, suggestions = gamemaster.split_suggestions(f"서술\n▶ {long}\n▶ 불을 피운다\n▶ 잔다")
    assert suggestions[0] == long


REQUESTED_MOVES = [
    ("go_to", {"target": "village"}, ["가장 가까운 마을로 간다", "마을을 찾아 떠난다", "사람 사는 곳으로 가자", "근처 농가로 간다"]),
    ("go_to", {"target": "city"}, ["도시로 간다", "가까운 시내로 가자"]),
    ("go_to", {"target": "embassy"}, ["한국 대사관에 간다", "영사관을 찾아간다"]),
    ("go_to", {"target": "airport"}, ["공항으로 간다"]),
    ("go_to", {"target": "continue"}, ["계속 간다", "가던 길을 간다", "이어서 간다", "다시 출발한다"]),
    ("travel", {"method": "walk", "distance_km": 30}, ["한국 쪽으로 30km 걷는다", "남쪽으로 걷는다", "길을 따라 걷는다"]),
    ("travel", {"method": "hitchhike", "distance_km": 100}, ["히치하이킹을 한다", "지나가는 차를 세운다", "트럭을 얻어 탄다"]),
    ("travel", {"method": "bus", "distance_km": 100}, ["버스를 탄다"]),
    ("travel", {"method": "drive", "distance_km": 100}, ["트럭을 몰고 간다", "차로 달린다"]),
    ("accept_offer", {}, ["트럭에 탄다", "제안을 받아들인다", "태워 달라고 한다"]),
]


def test_requested_move_phrasings_are_allowed(game):
    """막는 것만큼 중요: 플레이어가 실제로 이동을 말하면 그 이동은 허용된다."""
    game.begin_turn()
    game.offer = {"accept": "트럭에 올라탄다"}
    for tool_name, args, texts in REQUESTED_MOVES:
        for text in texts:
            game.turn_flags["player_text"] = text
            assert tools_module.player_asked_for(game, tool_name, args), (tool_name, text)
    game.leads = []
    lead = game.add_lead("smoke", "멀리서 연기가 가늘게 피어오른다.")
    for text in ["연기 쪽으로 간다", "연기를 향해 걷는다", f"{lead['direction']}으로 걸어간다", "그쪽으로 가 보자"]:
        game.turn_flags["player_text"] = text
        assert tools_module.player_asked_for(game, "follow_lead", {"lead_id": lead["id"]}), text


# ---------- 16차 수정: 밤으로 바뀔 때 그림에 없던 건물이 생기는 문제 ----------
def test_added_structures_detects_new_buildings():
    known = ["넓은 초원", "큰 나무", "큰 나무 아래"]
    assert imagegen.added_structures(known, ["큰 나무", "불 켜진 오두막", "초원"]) == ["불 켜진 오두막"]
    assert imagegen.added_structures(known, ["큰 나무", "별이 뜬 하늘", "풀밭"]) == []      # 구조물이 아니면 괜찮다
    assert imagegen.added_structures(["버려진 오두막"], ["오두막", "통나무 오두막"]) == []      # 원래 있던 것


def fake_image_client(descriptions, edits):
    import base64
    replies = iter(descriptions)

    def edit(**kw):
        edits.append(kw["prompt"])
        return SimpleNamespace(data=[SimpleNamespace(b64_json=base64.b64encode(b"png").decode())])

    return SimpleNamespace(images=SimpleNamespace(edit=edit),
                           responses=SimpleNamespace(create=lambda **k: SimpleNamespace(output_text=next(replies))))


def test_checked_edit_retries_then_discards(game, tmp_path):
    prev = tmp_path / "day.png"
    prev.write_bytes(b"day")
    game.set_scene("outdoor", "큰 나무 아래", "A large tree in the savanna.", ["큰 나무"])
    game.scene_seen = ["큰 나무", "초원"]

    edits = []                                      # 1차: 오두막이 생김 → 2차(엄격): 깨끗함 → 받아들임
    client = fake_image_client(["큰 나무, 불 켜진 오두막", "큰 나무, 밤하늘"], edits)
    path, seen = imagegen.checked_edit(client, game, str(prev))
    assert path and seen == ["큰 나무", "밤하늘"] and len(edits) == 2 and "STRICT" in edits[1]
    assert "The picture contains: A large tree in the savanna." in edits[0] and "house" not in edits[0]

    edits = []                                      # 두 번 다 생기면 편집본을 버린다
    client = fake_image_client(["큰 나무, 오두막", "큰 나무, 오두막"], edits)
    assert imagegen.checked_edit(client, game, str(prev)) == (None, None)


def test_draw_scene_keeps_old_image_or_shares_what_is_visible(game, monkeypatch):
    app = load_app(monkeypatch)
    game.set_scene("outdoor", "큰 나무 아래", "A large tree.", ["큰 나무"])
    game.image_path, game.scene_dirty = "/tmp/day.png", False
    game.image_scene, game.image_night = app.scene_key(game), not game.is_night       # 낮밤이 바뀐 상황
    game.image_weather = imagegen.weather_category(game.weather.get("code", 0))
    monkeypatch.setattr(app.savegame, "save", lambda s: None)

    monkeypatch.setattr(app.imagegen, "checked_edit", lambda c, s, p: (None, None))   # 건물이 생겨 버림
    app.draw_scene(game)
    assert game.image_path == "/tmp/day.png"                                         # 이전 그림 유지

    game.image_night = not game.is_night
    monkeypatch.setattr(app.imagegen, "checked_edit", lambda c, s, p: ("/tmp/night.png", ["큰 나무", "달"]))
    app.draw_scene(game)
    assert game.image_path == "/tmp/night.png" and "달" in game.scene_seen          # 보이는 것은 GM에게 전달
    assert "달" in gamemaster.build_input(game, "주변을 본다")


def test_night_wild_prompt_forbids_new_lights(game):
    game.place_type, game.start_hour, game.elapsed_hours = "야생", 21, 0
    game.set_scene("outdoor", "초원", "Open grassland.", ["풀"])
    prompt = imagegen.build_prompt(game)
    assert "moonlight and starlight" in prompt and "artificial" not in prompt


# ---------- 17차 수정: 범죄 의도와 범죄의 결과 ----------
from survival.intent import crime_intent  # noqa: E402


def test_crime_intent_classification():
    assert crime_intent("트럭을 타려고 시도한다")[0] == "none"
    assert crime_intent("트럭을 타려고 시도한다", ["트럭을 훔칠까?", "물을 찾는다"])[0] == "context"
    assert crime_intent("트럭을 타려고 시도한다", ["지갑을 훔친다"])[0] == "none"          # 다른 대상
    assert crime_intent("트럭에 올라탄다", [], ["트럭을 훔칠 방법을 생각한다"])[0] == "context"
    for text in ["차량을 빼앗는다", "트럭 기사를 기절시킨다", "몰래 짐칸에 숨어 탄다", "무임승차를 한다",
                 "기사를 속여서 태워 달라고 한다", "가게 물건을 슬쩍한다"]:
        assert crime_intent(text)[0] == "explicit", text
    for text in ["구멍으로 안을 훔쳐본다", "멧돼지의 공격을 피한다", "속이 안 좋아 쉰다", "기사에게 태워 달라고 부탁한다"]:
        assert crime_intent(text)[0] == "none", text


TRUCK_OFFER = {"id": "trucker", "text": "장거리 화물 트럭이 멈춰 선다. 기사는 마을까지 간다며 태워 주겠다고 한다.",
               "accept": "트럭에 올라탄다", "hours": 0, "stats": {}, "items": [], "money": 0, "risk": "",
               "detail": "근처 마을(약 25km)까지 이동",
               "bad": {"chance": 0}, "move": {"to": "city_or_village", "max_km": 500, "speed": 60},
               "dest": {"type": "city_or_village", "name": "근처 마을", "label": "근처 마을", "lat": 47.1,
                        "lon": 104.1, "km": 25, "place": "마을"}}


def gm_tries_to_steal(monkeypatch, game, player_text):
    """GM이 '트럭 절도 → 트럭 획득'을 시도하고, 거절되면 '제안 수락'으로 바꾸는 상황을 흉내 낸다."""
    calls = []
    steal = {"action": "트럭을 빼앗는다", "difficulty": "hard", "crime": "차량 절도", "witnessed": "victim",
             "violent": True, "item": "", "stealth": False, "success_money": 0, "success_items": [],
             "victim": "트럭 기사"}

    def fake_create(**kw):
        calls.append(kw)
        if len(calls) == 1:
            return SimpleNamespace(id="r1", output_text="", output=[
                SimpleNamespace(type="function_call", name="attempt_action", call_id="a", arguments=json.dumps(steal)),
                SimpleNamespace(type="function_call", name="acquire_vehicle", call_id="b",
                                arguments='{"kind": "truck", "name": "화물 트럭"}')])
        if len(calls) == 2 and any("error" in json.loads(o["output"]) for o in kw["input"]):
            return SimpleNamespace(id="r2", output_text="", output=[
                SimpleNamespace(type="function_call", name="accept_offer", call_id="c", arguments="{}")])
        return SimpleNamespace(id="r3", output=[], output_text="당신은 트럭에 오른다.")

    monkeypatch.setattr(gamemaster, "get_client",
                        lambda: SimpleNamespace(responses=SimpleNamespace(create=fake_create)))
    fix_roll(monkeypatch, 0.0)
    game.offer = dict(TRUCK_OFFER, turn=game.turn + 1)       # 이번 턴에 유효한 제안
    gamemaster.run_turn(game, player_text)
    return calls


def test_reported_case_riding_is_not_stealing(game, monkeypatch):
    """보고된 상황: '트럭을 타려고 시도한다' → 절도가 되면 안 되고, 기사의 제안을 받아들인 것이 된다."""
    game.suggestions = ["트럭 기사에게 말을 건다", "트럭을 타려고 시도한다", "물을 찾는다"]
    calls = gm_tries_to_steal(monkeypatch, game, "트럭을 타려고 시도한다")
    first = [json.loads(o["output"]) for o in calls[1]["input"]]
    assert "범죄를 의도하지 않았다" in first[0]["error"] and first[1]["success"] is False
    assert game.vehicle is None and game.wanted == 0 and not any(c.get("status") for c in game.characters)
    assert game.place_type == "마을"                                          # 대신 트럭을 얻어 타고 마을로
    assert "범죄 의도가 없다" in calls[0]["input"]


def test_crime_allowed_with_context_or_explicit_order(game, monkeypatch):
    game.suggestions = ["트럭을 훔칠까?", "기사에게 부탁한다", "물을 찾는다"]       # 앞서 범죄를 고려했다
    calls = gm_tries_to_steal(monkeypatch, game, "트럭을 타려고 시도한다")
    assert "앞서 같은 대상에 대한 범죄를 고려했다" in calls[0]["input"]
    assert game.vehicle and game.vehicle["stolen"] and game.wanted > 0

    other = GameState(lat=46.9, lon=103.8, place_name="몽골", weather=fake_weather(), biome="forest",
                      distance=geo.distance_to_korea(46.9, 103.8))
    other.suggestions = ["물을 찾는다"]
    gm_tries_to_steal(monkeypatch, other, "트럭을 빼앗는다")                      # 직접 지시
    assert other.vehicle and other.vehicle["stolen"]


def test_world_remembers_the_crime(game, monkeypatch):
    fix_roll(monkeypatch, 0.0)
    game.begin_turn()
    game.add_character("아메드", "트럭 기사", "50대, 콧수염")
    game.offer = dict(TRUCK_OFFER, turn=game.turn)
    out = game.attempt("트럭 기사를 기절시킨다", "hard", crime="차량 절도", witnessed="victim", violent=True,
                       victim="트럭 기사")
    assert out["success"]
    game.acquire_vehicle("truck", "화물 트럭")
    driver = game.find_character("트럭 기사")
    assert driver["name"] == "아메드" and "쓰러져" in driver["status"] and "빼앗겼다" in driver["status"]
    assert game.offer is None                                                 # 태워 주겠다던 제안은 끝났다
    assert any(f["scope"] == "always" and "차량 절도" in f["text"] for f in game.facts)
    text = gamemaster.build_input(game, "트럭 기사에게 말을 건다")
    assert "아메드 (트럭 기사)" in text and "상태: 당신에게" in text and "돕지 않" in text

    game.end_turn(0.5)
    game.begin_turn()                                                         # 현장에 머물면 반응이 온다
    assert game.event and "아메드" not in game.event["text"] and "트럭 기사" in game.event["text"]

    game.begin_turn()
    game.turn_flags["player_text"] = "트럭을 몰고 떠난다"
    call(game, "travel", method="drive", distance_km=50)                     # 현장을 떠나면 끝
    assert game.crime_scene is None


def test_failed_crime_makes_victim_hostile(game, monkeypatch):
    fix_roll(monkeypatch, 0.99)
    game.begin_turn()
    game.attempt("상인의 지갑을 훔친다", "normal", crime="절도", witnessed="none", victim="시장 상인")
    merchant = game.find_character("시장 상인")
    assert "알아챘다" in merchant["status"] and "적대" in merchant["status"]

    fix_roll(monkeypatch, 0.0)
    game.begin_turn()
    game.attempt("잠든 여행자의 지갑을 훔친다", "normal", crime="절도", witnessed="none", victim="잠든 여행자")
    assert "모른다" in game.find_character("잠든 여행자")["status"]
    assert game.crime_scene["witnessed"] == "none"
    monkeypatch.setattr(state_module, "roll_event", lambda *a, **k: None)
    game.end_turn(0.5)
    game.begin_turn()
    assert game.event is None                                                  # 아무도 못 봤으면 현장 반응도 없다



def test_no_vehicle_ownership_from_a_ride_request(game, monkeypatch):
    fix_roll(monkeypatch, 0.0)
    game.begin_turn()
    game.turn_flags["player_text"] = "트럭을 타려고 시도한다"
    game.turn_flags["crime_intent"] = crime_intent("트럭을 타려고 시도한다")
    game.attempt("기사를 설득한다", "normal")                               # 합법적인 시도는 성공해도
    out = call(game, "acquire_vehicle", kind="truck", name="화물 트럭")
    assert out["success"] is False and game.vehicle is None               # 트럭이 내 것이 되지는 않는다
    game.begin_turn()
    game.turn_flags["player_text"] = "주인에게 돈을 주고 오토바이를 산다"
    game.turn_flags["crime_intent"] = crime_intent(game.turn_flags["player_text"])
    game.attempt("오토바이 값을 흥정한다", "normal")
    assert call(game, "acquire_vehicle", kind="motorbike", name="낡은 오토바이")["success"]
    assert game.vehicle and not game.vehicle["stolen"]


def test_stolen_money_not_auto_added_without_intent(game):
    game.begin_turn()
    game.turn_flags["crime_intent"] = ("none", "")
    assert gamemaster.auto_money(game, "당신은 그의 지갑에서 $200를 훔쳤다.") == 0 and game.money == 50
    assert gamemaster.auto_money(game, "일을 도와 $30를 받았다.") == 30



# ---------- 18차 수정: 범죄 판정 보강, 판정 없는 범죄 차단, 범죄의 여파 ----------
def test_more_crimes_are_recognized():
    for text in ["노점에 불을 지른다", "경찰에게 뇌물을 준다", "여권을 위조한다", "남의 밭에서 감자를 캐 간다",
                 "주차된 오토바이 시동을 걸어 몰고 간다", "주인 몰래 빵을 챙긴다", "돈을 내지 않고 물을 들고 간다",
                 "밀수품을 나른다", "창고에 불을 질렀다"]:
        assert crime_intent(text)[0] == "explicit", text
    for text in ["모닥불에 불을 피운다", "마른 풀로 불을 지핀다", "배낭에서 물을 꺼내 마신다", "남의 도움을 받아 길을 찾는다",
                 "감자를 캐 간다", "내 짐을 챙겨 떠난다", "가도 되는지 물어본다", "소리를 지른다", "몰래 다가가 살펴본다",
                 "강가로 간다", "사기가 떨어진다"]:
        assert crime_intent(text)[0] == "none", text
    from survival.config import CRIMES
    assert {"방화", "뇌물", "위조", "밀수"} <= set(CRIMES)


def test_gains_need_an_honest_source(game, monkeypatch):
    game.place_type = "마을"
    game.begin_turn()
    out = call(game, "update_inventory", remove=[], add=[{"name": "빵", "carryable": True}], source="stolen", giver="")
    assert "error" in out and "빵" not in game.items                          # 판정 없이 훔친 것은 안 된다
    out = call(game, "update_inventory", remove=[], add=[{"name": "빵", "carryable": True}], source="bought", giver="")
    assert "error" in out                                                     # 값을 안 냈다
    call(game, "pay", amount=2, purpose="빵")
    assert "error" not in call(game, "update_inventory", remove=[], add=[{"name": "빵", "carryable": True}],
                               source="bought", giver="")
    out = call(game, "update_status", health=0, satiety=0, hydration=0, energy=0, money=100, money_source="stolen",
               consumed_items=[], reason="지갑")
    assert "error" in out and game.money == 48                                # 훔친 돈도 판정 없이는 안 된다

    fix_roll(monkeypatch, 0.0)
    game.begin_turn()
    game.attempt("시장 상인의 빵을 훔친다", "normal", crime="절도", witnessed="bystanders", victim="시장 상인",
                 success_items=["바게트"])
    assert "바게트" in game.items and "바게트" in game.stolen_items          # 판정에 성공한 장물
    out = call(game, "update_inventory", remove=[], add=[{"name": "사과", "carryable": True}], source="gift",
               giver="시장 상인")
    assert "원한" in out["error"]                                             # 피해자는 아무것도 주지 않는다


def test_crime_aftermath_carries_forward(game, monkeypatch):
    fix_roll(monkeypatch, 0.0)
    game.place_type, game.place_name = "마을", "몽골, 어느 마을"
    game.begin_turn()
    game.add_character("아메드", "트럭 기사", "50대")
    game.attempt("트럭 기사를 기절시킨다", "hard", crime="차량 절도", witnessed="bystanders", violent=True,
                 victim="트럭 기사")
    game.acquire_vehicle("truck", "화물 트럭")
    assert game.notorious and game.enemies[0]["name"] == "아메드"
    notes = game.crime_aftermath()
    assert any("수배도" in n for n in notes) and any("현장" in n for n in notes) and any("훔친 것" in n for n in notes)
    assert any("범죄자로 알려져" in n for n in notes)

    game.end_turn(0.5)
    game.begin_turn()                                                         # 다음 턴: 반드시 반응
    assert game.event and "트럭 기사" in game.event["text"]
    game.set_scene("indoor", "트럭 운전석", "Inside the truck cab.", ["운전대"])   # 장면이 바뀌어도
    text = gamemaster.build_input(game, "숨을 고른다")
    assert "[당신에게 원한이 있는 사람" in text and "아메드" in text and "[범죄의 여파" in text

    game.pass_time(3, "rest")                                                 # 기절한 기사는 두어 시간 뒤 깨어난다
    game.end_turn(0)
    game.begin_turn()
    assert "정신을 차리고" in game.event["text"]

    game.begin_turn()
    game.turn_flags["player_text"] = "트럭을 몰고 떠난다"
    call(game, "travel", method="drive", distance_km=100)                    # 멀리 떠나면 현장·원한은 멀어진다
    assert game.crime_scene is None and not game.enemies_nearby() and not game.notorious_here()
    assert any("훔친 것" in n for n in game.crime_aftermath())               # 훔친 트럭은 여전히 여파로 남는다


def test_notorious_town_reacts_and_does_not_help(game, monkeypatch):
    game.place_type = "마을"
    game.notorious = [{"place": "몽골", "lat": game.lat, "lon": game.lon, "crime": "강도", "turn": 1}]
    fix_roll(monkeypatch, 0.0)
    monkeypatch.setattr(state_module, "roll_major_event",
                        lambda *a, **k: {"id": "korean", "text": "한국인이 초대한다", "accept": "초대를 받아들인다",
                                         "move": {}, "stats": {}, "items": [], "money": 50, "hours": 1, "risk": "",
                                         "bad": {"chance": 0}})
    game.turn, game.last_major_turn = 20, 0
    game.begin_turn()
    assert game.offer is None and "알아보고" in game.event["text"]


def test_arrest_confiscates_stolen_goods(game):
    game.wanted = 40
    game.items.append("훔친 시계")
    game.stolen_items = ["훔친 시계"]
    game.begin_turn()
    game.arrest("검문")
    assert "훔친 시계" not in game.items and game.stolen_items == []


# ---------- 19차 수정: 지나간 기회는 정말 사라진다 ----------
def offer_turn(game, offer_id="trucker"):
    from survival.events import MAJOR_EVENTS
    e = next(x for x in MAJOR_EVENTS if x["id"] == offer_id)
    game.offer = game.plan_offer({"id": offer_id, "text": e["text"], "accept": e["accept"], "hours": e.get("hours", 0),
                                  "stats": dict(e.get("stats", {})), "items": list(e.get("items", [])), "money": 0,
                                  "risk": e["risk"], "bad": dict(e["bad"]), "move": dict(e.get("move", {}))})
    game.offer["turn"] = game.turn
    return game.offer


def test_mentioning_the_truck_is_not_accepting(game):
    game.begin_turn()
    offer_turn(game)
    for text in ["트럭 기사에게 말을 건다", "트럭을 살펴본다", "트럭 타이어를 살핀다", "트럭 기사에게 어디 가는지 묻는다"]:
        game.turn_flags["player_text"] = text
        assert not tools_module.player_asked_for(game, "accept_offer", {}), text
    for text in ["트럭에 탄다", "트럭에 올라탄다", "트럭 기사를 따라간다", "제안을 받아들인다", "트럭을 타고 가겠다"]:
        game.turn_flags["player_text"] = text
        assert tools_module.player_asked_for(game, "accept_offer", {}), text


def test_ignored_offer_leaves_the_world(game, monkeypatch):
    monkeypatch.setattr(state_module, "roll_event", lambda *a, **k: None)
    game.begin_turn()                                                    # N턴: 트럭 기사가 제안
    offer_turn(game)
    game.set_scene("outdoor", "흙길 옆", "A dirt road. A truck is parked by the road. Grass all around.",
                   ["흙길", "멈춰 선 트럭"])
    game.add_character("아메드", "트럭 기사", "50대")
    game.end_turn(0.5)
    assert game.offer                                                    # 나온 턴에는 유지

    game.begin_turn()                                                    # N+1턴: 다른 행동
    text = gamemaster.build_input(game, "물을 마신다")
    assert "[기회 - 이번 턴이 마지막]" in text and "트럭 기사는 더 기다리지 않고" in text
    game.scene_dirty = False
    game.end_turn(0.5)
    assert game.offer is None
    assert "멈춰 선 트럭" not in game.scene_features and not game.find_character("트럭 기사")
    assert "truck" not in game.scene_desc.lower() and "dirt road" in game.scene_desc.lower()
    assert game.scene_dirty                                              # 그림에서도 트럭을 지운다
    assert any("⌛" in n["title"] for n in gamemaster.collect_notices(game))
    assert any("트럭 기사는" in f["text"] for f in game.facts)

    game.begin_turn()                                                    # N+2턴: 이제 와서 탄다고 해도
    game.turn_flags["player_text"] = "트럭에 탄다"
    out = call(game, "accept_offer")
    assert out["success"] is False and "이미 지나갔다" in out["message"] and game.place_type == "야생"
    assert "[지나간 기회" in gamemaster.build_input(game, "트럭에 탄다")


def test_same_offer_does_not_come_right_back(game, monkeypatch):
    monkeypatch.setattr(state_module, "roll_event", lambda *a, **k: None)
    game.begin_turn()
    offer_turn(game)
    game.end_turn(0.5)
    game.begin_turn()
    game.end_turn(0.5)                                                   # 놓침
    monkeypatch.setattr(state_module, "roll_major_event",
                        lambda *a, **k: {"id": "trucker", "text": "트럭이 또 멈춘다", "accept": "트럭에 올라탄다",
                                         "move": {}, "stats": {}, "items": [], "money": 0, "hours": 0, "risk": "",
                                         "bad": {"chance": 0}})
    fix_roll(monkeypatch, 0.0)
    for _ in range(3):
        game.begin_turn()
        assert game.offer is None or game.offer["id"] != "trucker"
        game.end_turn(0.25)
        game.health = game.satiety = game.hydration = 100


def test_supply_crate_stays_until_you_leave(game, monkeypatch):
    monkeypatch.setattr(state_module, "roll_event", lambda *a, **k: None)
    game.begin_turn()
    offer_turn(game, "supply")
    for _ in range(3):
        game.end_turn(0.5)
        game.begin_turn()
    assert game.offer and game.offer["id"] == "supply"                  # 상자는 떠나지 않는다
    game.turn_flags["player_text"] = "남쪽으로 30km 걷는다"
    call(game, "travel", method="walk", distance_km=30)
    assert game.offer is None                                            # 떠나면 두고 온 것


# ---------- 20차 수정: 물을 마시면 수분이 오른다 ----------
def desert_noon(game):
    game.biome, game.place_type, game.start_hour, game.elapsed_hours = "desert", "야생", 13, 0
    game.weather.update(temperature=38.0, feels_like=40.0, humidity=15.0, hourly=[])
    game.forecast, game.diurnal = [], {}


def reply_with(monkeypatch, *responses):
    replies = iter(responses)
    monkeypatch.setattr(gamemaster, "get_client",
                        lambda: SimpleNamespace(responses=SimpleNamespace(create=lambda **k: next(replies))))


def test_drinking_in_the_desert_raises_hydration(game, monkeypatch):
    desert_noon(game)
    game.hydration = 50
    # GM이 서술만 하고 아무 툴도 부르지 않은 경우 (보고된 증상)
    reply_with(monkeypatch, SimpleNamespace(id="r", output=[], output_text="당신은 물을 들이켠다."))
    gamemaster.run_turn(game, "가지고 있는 물을 마신다")
    assert "물 1L" not in game.items and game.hydration > 50 + 35          # +45, 15분 동안 -3.6
    assert game.delta["hours"] == 0.25
    from survival.ui import turn_summary
    assert "💧 수분 +45 (물)" in turn_summary(game) and "더위" in turn_summary(game)


def test_gm_gives_too_little_or_only_removes_item(game, monkeypatch):
    desert_noon(game)
    game.hydration = 50
    call_small = SimpleNamespace(id="r1", output_text="", output=[
        SimpleNamespace(type="function_call", name="update_status", call_id="a", arguments=json.dumps(
            {"health": 0, "satiety": 0, "hydration": 5, "energy": 0, "money": 0, "money_source": "none",
             "consumed_items": ["물 1L"], "reason": "물을 마심"}))])
    reply_with(monkeypatch, call_small, SimpleNamespace(id="r2", output=[], output_text="당신은 물을 마신다."))
    gamemaster.run_turn(game, "물을 마신다")
    assert game.hydration >= 50 + 45 - 4                                   # GM이 +5만 줘도 +45 보장

    other = GameState(lat=23, lon=11, place_name="사막", weather=fake_weather(), biome="desert")
    desert_noon(other)
    other.hydration = 40
    only_remove = SimpleNamespace(id="r1", output_text="", output=[
        SimpleNamespace(type="function_call", name="update_inventory", call_id="a", arguments=json.dumps(
            {"add": [], "remove": ["물 1L"], "source": "none", "giver": ""}))])
    reply_with(monkeypatch, only_remove, SimpleNamespace(id="r2", output=[], output_text="물을 다 마셨다."))
    gamemaster.run_turn(other, "물을 마신다")
    assert other.hydration >= 40 + 45 - 4 and "물 1L" not in other.items


def test_eating_food_and_not_double_counting(game, monkeypatch):
    game.satiety = 30
    reply_with(monkeypatch, SimpleNamespace(id="r", output=[], output_text="당신은 에너지바를 씹는다."))
    gamemaster.run_turn(game, "에너지바를 먹는다")
    assert "에너지바 1개" in game.items and game.satiety >= 30 + 25 - 1        # 하나만 먹는다
    game.satiety = 30
    big = SimpleNamespace(id="r1", output_text="", output=[
        SimpleNamespace(type="function_call", name="update_status", call_id="a", arguments=json.dumps(
            {"health": 0, "satiety": 40, "hydration": 0, "energy": 0, "money": 0, "money_source": "none",
             "consumed_items": ["에너지바"], "reason": "든든히 먹음"}))])
    reply_with(monkeypatch, big, SimpleNamespace(id="r2", output=[], output_text="배가 부르다."))
    gamemaster.run_turn(game, "에너지바를 먹는다")
    assert 30 + 40 - 1 <= game.satiety <= 30 + 40                           # GM이 더 주면 그대로, 겹쳐 더하지 않는다


def test_river_water_is_not_taken_from_inventory(game, monkeypatch):
    game.hydration = 40
    river = SimpleNamespace(id="r1", output_text="", output=[
        SimpleNamespace(type="function_call", name="update_status", call_id="a", arguments=json.dumps(
            {"health": 0, "satiety": 0, "hydration": 30, "energy": 0, "money": 0, "money_source": "none",
             "consumed_items": [], "reason": "개울물을 끓여 마심"}))])
    reply_with(monkeypatch, river, SimpleNamespace(id="r2", output=[], output_text="개울물을 마신다."))
    gamemaster.run_turn(game, "개울물을 끓여 마신다")
    assert "물 1L" in game.items                                           # 가진 물은 그대로
    assert gamemaster.estimate_time("에너지바를 먹고 잔다") == (7.0, "sleep")   # 먹고 자면 잠이 우선


# ---------- 21차 수정: 서술의 몸 상태 = 오른쪽 수치 ----------
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


# ---------- 22차 수정: 그림 지시문을 한 번에 맞게 ----------
def test_wild_prompts_do_not_name_what_must_not_appear(game):
    game.place_type, game.start_hour, game.elapsed_hours = "야생", 22, 0
    game.set_scene("outdoor", "초원", "Open grassland with a lone acacia tree.", ["아카시아 나무"])
    for prompt in (imagegen.build_prompt(game), imagegen.build_edit_prompt(game)):
        low = prompt.lower()
        # 금지할 물건 이름(집·등불·창문·표지판)을 말하지 않는다: 말하면 이미지 모델이 그것을 그린다
        assert not any(w in low for w in ("house", "lantern", "lamp", "window", "cabin", "sign", "architecture",
                                          "artificial"))
        assert "moonlight and starlight" in prompt
    assert "Relight this exact picture" in imagegen.build_edit_prompt(game)


def test_edit_prompt_pins_down_what_is_in_the_picture(game, tmp_path):
    path = tmp_path / "scene.png"
    path.write_bytes(b"png")
    client = SimpleNamespace(responses=SimpleNamespace(create=lambda **k: SimpleNamespace(
        output_text="큰 바오밥나무 | large baobab tree, 붉은 흙 평원 | red dirt plain, 해 | sun")))
    assert imagegen.read_image(client, str(path)) == (["큰 바오밥나무", "붉은 흙 평원", "해"],
                                                      ["large baobab tree", "red dirt plain", "sun"])
    assert imagegen.describe_image(client, str(path)) == ["큰 바오밥나무", "붉은 흙 평원", "해"]
    game.place_type = "야생"
    game.set_scene("outdoor", "바오밥 아래", "A baobab tree on a plain.", ["바오밥나무"])
    game.scene_seen_en = ["large baobab tree", "red dirt plain"]
    assert "The picture contains: large baobab tree, red dirt plain." in imagegen.build_edit_prompt(game)
    game.place_type = "마을"                                             # 마을의 밤은 있던 불빛만 켜진다
    game.start_hour = 22
    edit = imagegen.build_edit_prompt(game)
    assert "Only lights that already exist" in edit and "written in" in edit


# ---------- 23차 수정: 기회는 한 번만 ----------
def supply_offer(game):
    from survival.events import MAJOR_EVENTS
    event = next(e for e in MAJOR_EVENTS if e["id"] == "supply")
    offer = {"id": "supply", "text": event["text"], "accept": event["accept"], "hours": 0.5,
             "stats": dict(event["stats"]), "items": list(event["items"]), "money": 0, "risk": event["risk"],
             "bad": dict(event["bad"], chance=0), "move": {}}
    game.place_type = "야생"
    game.offer = game.plan_offer(offer)
    game.offer["turn"] = game.turn
    game.scene_features = ["낙하산 달린 보급 상자"]
    return game.offer


def test_opened_supply_crate_cannot_be_opened_again(game, monkeypatch):
    supply_offer(game)
    game.turn += 1
    game.begin_turn = lambda: None
    game.turn_flags = {"player_text": "보급 상자를 연다"}
    assert game.accept_offer()["success"]
    assert "생수 2병" in game.items and "열린 빈 보급 상자" in game.scene_features
    satiety = game.satiety
    # 다음 턴: 다시 연다 → 엔진이 막는다
    game.turn += 1
    game.turn_flags = {"player_text": "보급 상자를 다시 연다"}
    again = game.accept_offer()
    assert not again["success"] and "텅 비어" in again["message"]
    bad_gain = call(game, "update_inventory", add=[{"name": "비상식량 2개", "carryable": True}], remove=[],
                    source="found", giver="")
    assert "error" in bad_gain and game.items.count("비상식량 2개") == 1
    bad_stat = call(game, "update_status", health=0, satiety=40, hydration=40, energy=0, money=0,
                    money_source="none", consumed_items=[], reason="상자 속 식량")
    assert "error" in bad_stat and game.satiety == satiety
    text = gamemaster.build_input(game, "보급 상자를 연다")
    assert "[끝난 기회" in text and "텅 비어" in text
    # 같은 곳에서는 보급 상자 기회가 다시 나오지 않는다
    assert game.offer_closed("supply")


def test_declined_offer_cannot_be_accepted_later(game, monkeypatch):
    supply_offer(game)
    game.turn += 1
    reply_with(monkeypatch, SimpleNamespace(id="r", output=[], output_text="당신은 상자를 그대로 둔다."))
    gamemaster.run_turn(game, "수상해 보이니 상자는 열지 않는다")
    assert game.offer is None and game.done_offers[-1]["how"] == "declined"
    assert any("거절" in n["title"] for n in game.notices)
    reply_with(monkeypatch, SimpleNamespace(id="r1", output_text="", output=[
        SimpleNamespace(type="function_call", name="accept_offer", call_id="a", arguments="{}")]),
        SimpleNamespace(id="r2", output=[], output_text="이미 열지 않기로 했다."))
    before = list(game.items)
    gamemaster.run_turn(game, "역시 보급 상자를 연다")
    assert game.items == before and game.done_offers[-1]["how"] == "declined"


def test_gm_decline_tool_and_new_offer_not_declined(game, monkeypatch):
    supply_offer(game)
    # 이번 턴에 막 나온 기회는 플레이어가 아직 못 봤다: 거절로 치지 않는다
    assert not gamemaster.auto_decline(game, "무시하고 걷는다")
    game.turn += 1
    out = call(game, "decline_offer", reason="상자를 무시함")
    assert out["ok"] and game.offer is None
    from survival.events import DECLINE_WORDS                # 거절이 아닌 말에 걸리지 않는다
    assert not any(w.replace(" ", "") in "안타깝다가방안가득" for w in DECLINE_WORDS)


def test_engine_opens_crate_once_even_if_gm_skips_the_tool(game, monkeypatch):
    supply_offer(game)
    game.turn += 1                                        # 기회는 지난 턴에 나왔다
    game.offer["turn"] = game.turn
    monkeypatch.setattr(game, "begin_turn", lambda: (setattr(game, "turn", game.turn + 1),
                                                     setattr(game, "turn_flags", {}),
                                                     setattr(game, "time_passed_this_turn", False),
                                                     setattr(game, "_snapshot", game._tracked())))
    # 1) GM이 accept_offer 없이 서술만 해도 엔진이 받아들여 한 번 얻는다
    reply_with(monkeypatch, SimpleNamespace(id="r", output=[], output_text="당신은 상자를 연다."))
    gamemaster.run_turn(game, "보급 상자를 연다")
    assert game.items.count("생수 2병") == 1 and game.done_offers[-1]["how"] == "accepted"
    assert any("기회를 잡았다" in n["title"] for n in game.notices)
    items = list(game.items)
    # 2) 다시 연다: GM이 물건을 또 주려 해도, 서술로 꺼냈다고 해도 막힌다
    give = SimpleNamespace(id="r1", output_text="", output=[
        SimpleNamespace(type="function_call", name="update_inventory", call_id="a", arguments=json.dumps(
            {"add": [{"name": "비상식량 2개", "carryable": True}], "remove": [], "source": "found", "giver": ""})),
        SimpleNamespace(type="function_call", name="accept_offer", call_id="b", arguments="{}")])
    reply_with(monkeypatch, give,
               SimpleNamespace(id="r2", output=[], output_text="상자를 뒤지자 비상식량 2개가 나왔다. 당신은 그것을 챙긴다."))
    body = gamemaster.run_turn(game, "보급 상자를 다시 연다")
    assert game.items == items
    assert "텅 비어" in body and "나왔다" not in body
    assert any("이미 끝난 일" in n["title"] for n in game.notices)


def test_gm_accept_call_after_engine_accept_is_not_double(game, monkeypatch):
    supply_offer(game)
    game.turn += 1
    call_accept = SimpleNamespace(id="r1", output_text="", output=[
        SimpleNamespace(type="function_call", name="accept_offer", call_id="a", arguments="{}")])
    reply_with(monkeypatch, call_accept, SimpleNamespace(id="r2", output=[], output_text="상자를 연다."))
    gamemaster.run_turn(game, "보급 상자를 연다")
    assert game.items.count("생수 2병") == 1 and len(game.done_offers) == 1
    assert gamemaster.enforce_redo("상자 안에는 아무것도 들어 있지 않다.", {"kind": "redo", "message": "x",
                                                                       "items": []}) == "상자 안에는 아무것도 들어 있지 않다."


# ---------- 일부만 마시기: "조금 마신다"가 물 한 병을 통째로 없애지 않는다 ----------
from survival.inventory import consumable_effect, liquid_ml, partial_portion, with_volume  # noqa: E402


def test_volume_helpers():
    assert liquid_ml("물 1L") == 1000 and liquid_ml("생수 500ml") == 500 and liquid_ml("물 1.5L") == 1500
    assert liquid_ml("에너지바 2개") is None and liquid_ml("스마트폰(배터리 30%)") is None
    assert with_volume("물 1L", 750) == "물 750ml" and with_volume("물 2L", 1500) == "물 1.5L"
    assert consumable_effect("물 1L") == ("hydration", 45)                  # 기존 값 그대로
    assert consumable_effect("물 500ml") == ("hydration", 22)               # 용량에 비례
    assert consumable_effect("물 250ml") == ("hydration", 11)


def test_partial_portion_wording():
    assert partial_portion("가진 물을 조금 마신다", 1000) == 250
    assert partial_portion("물을 한 모금 마신다", 1000) == 250
    assert partial_portion("물을 아껴서 마신다", 1000) == 250
    assert partial_portion("물을 반만 마신다", 1000) == 500
    assert partial_portion("물을 절반 마신다", 600) == 300
    assert partial_portion("물을 마신다", 1000) is None
    assert partial_portion("물을 마시고 조금 쉰다", 1000) is None           # '조금'이 쉬는 것에 붙음
    assert partial_portion("반드시 물을 마신다", 1000) is None
    assert partial_portion("모금함 옆에서 물을 마신다", 1000) is None
    assert partial_portion("물을 조금 마신다", 250) is None                 # 남은 게 한 모금뿐이면 다 마신다


def test_sipping_keeps_the_rest_when_gm_does_nothing(game, monkeypatch):
    """보고된 증상: GM이 툴 없이 서술만 해도 '조금 마신다'면 남은 물이 남는다."""
    game.hydration = 50
    reply_with(monkeypatch, SimpleNamespace(id="r", output=[], output_text="당신은 물을 한 모금 마신다."))
    gamemaster.run_turn(game, "가진 물을 조금 마신다")
    assert "물 750ml" in game.items and "물 1L" not in game.items
    assert 50 + 11 - 2 <= game.hydration <= 50 + 11                        # 250ml 만큼만
    from survival.ui import turn_summary
    assert "💧 수분 +11 (물)" in turn_summary(game)


def test_sipping_caps_gm_gain_and_reports_remaining(game, monkeypatch):
    """GM이 물 한 병을 다 마신 만큼(+45) 줘도 반만 마셨으면 반만큼만 오르고, 남은 물을 툴 결과로 알려 준다."""
    game.hydration = 40
    big = SimpleNamespace(id="r1", output_text="", output=[
        SimpleNamespace(type="function_call", name="update_status", call_id="a", arguments=json.dumps(
            {"health": 0, "satiety": 0, "hydration": 45, "energy": 0, "money": 0, "money_source": "none",
             "consumed_items": ["물 1L"], "reason": "물을 마심"}))])
    reply_with(monkeypatch, big, SimpleNamespace(id="r2", output=[], output_text="물을 반쯤 마신다."))
    gamemaster.run_turn(game, "물을 반만 마신다")
    assert "물 500ml" in game.items
    assert 40 + 22 - 2 <= game.hydration <= 40 + 23
    game.turn_flags = {"player_text": "물을 한 모금 마신다"}
    result = call(game, "update_status", health=0, satiety=0, hydration=30, energy=0, money=0,
                  money_source="none", consumed_items=["물 500ml"], reason="한 모금")
    assert result["일부만_마심"] == ["물 500ml → 물 250ml (250ml 마심)"] and result["사라진_소지품"] == []
    assert "물 250ml" in game.items


def test_gm_removing_bottle_on_a_sip_leaves_the_rest(game, monkeypatch):
    """GM이 '물 1L'을 지우기만 해도, 조금 마셨으면 남은 물을 남긴다. GM이 직접 남은 양을 넣으면 그대로 따른다."""
    game.hydration = 40
    only_remove = SimpleNamespace(id="r1", output_text="", output=[
        SimpleNamespace(type="function_call", name="update_inventory", call_id="a", arguments=json.dumps(
            {"add": [], "remove": ["물 1L"], "source": "none", "giver": ""}))])
    reply_with(monkeypatch, only_remove, SimpleNamespace(id="r2", output=[], output_text="목을 축인다."))
    gamemaster.run_turn(game, "물을 조금 마신다")
    assert "물 750ml" in game.items and game.hydration >= 40 + 11 - 2

    game.items = ["물 1L"]
    game.turn_flags = {"player_text": "물을 조금 마신다"}
    game.update_items(add=["물 800ml"], remove=["물 1L"])
    assert game.items == ["물 800ml"]


def test_full_drink_still_empties_the_bottle(game, monkeypatch):
    game.hydration = 40
    reply_with(monkeypatch, SimpleNamespace(id="r", output=[], output_text="물을 다 마신다."))
    gamemaster.run_turn(game, "물을 전부 마신다")
    assert not any(liquid_ml(i) for i in game.items) and game.hydration >= 40 + 45 - 2


def test_full_drink_of_measured_water_caps_gm_gain(game, monkeypatch):
    """남은 물 375ml(기본 +17)를 다 마실 때 GM이 +35를 줘도 1.2배(+20)까지만. 강물처럼 용량을 모르는 것은 GM을 따른다."""
    game.items = ["물 375ml"]
    game.hydration = 40
    game.turn_flags = {"player_text": "남은 물을 전부 마신다"}
    call(game, "update_status", health=0, satiety=0, hydration=35, energy=0, money=0, money_source="none",
         consumed_items=["물 375ml"], reason="다 마심")
    assert game.hydration == 40 + 20 and game.items == []
    game.turn_flags = {"player_text": "개울물을 끓여 마신다"}
    call(game, "update_status", health=0, satiety=0, hydration=30, energy=0, money=0, money_source="none",
         consumed_items=[], reason="개울물")
    assert game.hydration == 60 + 30
