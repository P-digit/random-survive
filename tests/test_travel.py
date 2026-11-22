"""이동 수단·표·운전·초반 제한 (survival/travel.py) 테스트."""
import pytest

from survival import gamemaster, geo, savegame, state as state_module
from survival.state import GameState
from tests.helpers import call, fake_weather, fix_roll


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


def test_only_one_travel_per_turn(game):
    game.begin_turn()
    first = call(game, "travel", method="walk", distance_km=10)
    after_first = game.distance
    second = call(game, "travel", method="walk", distance_km=10)
    assert first["success"] and "error" in second and game.distance == after_first
    assert "error" in call(game, "advance_time", hours=5, activity="rest", sheltered=False)
    game.begin_turn()                      # 다음 턴에는 다시 가능
    assert call(game, "travel", method="walk", distance_km=10)["success"]


def test_flight_is_always_direct_to_korea(game):
    game.begin_turn()
    game.place_type, game.money = "도시", 100
    assert call(game, "travel", method="flight", distance_km=300)["success"] is False   # 직항 요금이 모자람
    game.money = 5000
    game.flags["at_airport"] = True
    out = call(game, "travel", method="flight", distance_km=300)
    assert out["arrived_in_korea"] and game.status == "won"


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


def test_road_makes_hitchhiking_easier(game, monkeypatch):
    game.flags["on_road"] = True
    fix_roll(monkeypatch, 0.80)                         # 숲 야생 기본 60% → 도로 위 85%
    game.begin_turn()
    assert game.travel("hitchhike", 100)["success"]


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


def test_arrival_place_is_rule_based_not_random():
    from survival.travel import arrival_place
    far, near = {"km": 500}, {"km": 10}
    assert arrival_place("walk", far) == "야생" and arrival_place("drive", far) == "야생"
    assert arrival_place("walk", near) == "도시"
    assert arrival_place("hitchhike", far) == "마을" and arrival_place("bus", far) == "마을"
    assert arrival_place("bus", {"km": 25}) == "도시" and arrival_place("train", far) == "도시"
    assert arrival_place("walk", None) == "야생"
