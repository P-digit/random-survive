"""기회(대형 이벤트) (survival/offers.py) 테스트."""
import json
import random
from types import SimpleNamespace

import pytest

from survival import gamemaster, geo, state as state_module, tools as tools_module
from survival.events import roll_major_event
from survival.state import GameState
from tests.helpers import call, fake_weather, fix_roll, reply_with


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
    # 3턴째부터는 새 기회가 무작위로 나올 수 있다. 그러면 N+2턴의 '트럭에 탄다'가 새 기회를 받아들여 버린다(가끔 실패하던 원인)
    monkeypatch.setattr(state_module, "roll_major_event", lambda *a, **k: None)
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
