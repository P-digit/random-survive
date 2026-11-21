"""목적지로 가기·단서·요청하지 않은 이동 차단 (survival/journey.py, 단서는 state.py) 테스트."""
import json
import random
from types import SimpleNamespace

import pytest

from survival import gamemaster, geo, leads as leads_module, state as state_module, tools as tools_module
from survival.state import GameState
from tests.helpers import call, fake_weather, fix_roll


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
