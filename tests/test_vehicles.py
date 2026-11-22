"""탈것: 사기, 주유, 연료 없는 탈것, 경비행기, 국경 (survival/travel.py)."""
import pytest

from survival import gamemaster, geo
from survival.config import VEHICLES
from tests.helpers import call


def own(game, kind, place="도시", money=20000):
    game.place_type, game.money = place, money
    game.begin_turn()
    assert call(game, "buy_vehicle", kind=kind, name="")["success"], kind
    return game.vehicle


def test_buying_where_it_is_sold(game):
    game.begin_turn()
    assert call(game, "buy_vehicle", kind="bicycle", name="")["success"] is False          # 야생에서는 살 수 없다
    game.place_type, game.money = "마을", 400
    assert call(game, "buy_vehicle", kind="plane", name="")["success"] is False            # 경비행기는 도시에서
    assert call(game, "buy_vehicle", kind="car", name="")["success"] is False              # $1,200 > $400
    out = call(game, "buy_vehicle", kind="motorbike", name="중고 오토바이")
    assert out["success"] and game.money == 50 and game.vehicle["name"] == "중고 오토바이"
    assert game.vehicle["range_km"] == VEHICLES["motorbike"]["range"] and not game.vehicle["stolen"]
    game.money = 100
    out = call(game, "buy_vehicle", kind="bicycle", name="")                               # 갈아탈 수 있다
    assert out["success"] and game.vehicle["kind"] == "bicycle" and "두고 간다" in out["message"]
    assert any(n["title"].startswith("🚙 탈것 확보") for n in gamemaster.collect_notices(game))


def test_refuelling(game):
    v = own(game, "car", money=1300)
    v["range_km"] = 50
    game.place_type = "야생"
    assert call(game, "refuel")["success"] is False
    game.place_type = "마을"
    out = call(game, "refuel")                                     # 가진 $100으로 살 수 있는 만큼 (km당 $0.08)
    assert out["success"] and v["range_km"] == 550 and game.money == pytest.approx(100 - 500 * 0.08)
    assert call(game, "refuel")["success"] is False                # 이미 가득


def test_fuel_free_rides_never_run_dry(game):
    own(game, "bicycle", place="마을")
    game.place_type = "야생"
    energy = game.energy
    out = call(game, "travel", method="drive", distance_km=60)
    assert out["success"] and game.vehicle and game.vehicle["range_km"] == 120   # 연료가 줄지 않는다
    assert game.energy < energy                                                  # 자전거는 몸으로 간다
    assert call(game, "refuel")["success"] is False


def test_plane_crosses_the_sea_cars_do_not(game, monkeypatch):
    monkeypatch.setattr(geo, "is_land", lambda lat, lon: False)
    own(game, "car")
    game.place_type = "야생"
    assert call(game, "travel", method="drive", distance_km=100)["success"] is False
    game.vehicle = None
    own(game, "plane")
    out = call(game, "travel", method="drive", distance_km=600)
    assert out["success"] and game.vehicle["range_km"] == 900 - 600


def border_crossing(game, monkeypatch, stolen=False, wanted=0):
    own(game, "car")
    game.vehicle["stolen"] = stolen
    game.wanted, game.country_code = wanted, "mn"
    monkeypatch.setattr(geo, "reverse_geocode", lambda lat, lon: {"name": "중국 국경 마을", "country_code": "cn"})
    game.begin_turn()
    return call(game, "travel", method="drive", distance_km=200)


def test_clean_border_crossing(game, monkeypatch):
    out = border_crossing(game, monkeypatch)
    assert out["success"] and game.turn_flags["border"] == {"from": "mn", "to": "cn", "stopped": False}
    assert not game.pursuit and "국경을 넘었다" in out["message"]
    assert any(n["title"].startswith("🛂 국경을 넘었다 — MN → CN") for n in gamemaster.collect_notices(game))


def test_stolen_car_is_stopped_at_the_border(game, monkeypatch):
    out = border_crossing(game, monkeypatch, stolen=True)
    assert game.pursuit and game.pursuit["who"] == "국경 검문소의 무장 경비대" and game.pursuit["stolen_vehicle"]
    assert "멈춰 세우는 장면" in out["message"]
    assert any(n["title"].startswith("🚔 경찰 — 국경 검문소") for n in gamemaster.collect_notices(game))


def test_wanted_driver_is_stopped_at_the_border(game, monkeypatch):
    border_crossing(game, monkeypatch, wanted=45)
    assert game.pursuit and game.pursuit["stage"] == 3


def test_relaxed_limits():
    from survival import config
    assert config.EARLY_GAME_HOURS == 12 and config.AIRPORT_OPEN_DAY == 3


def test_riding_your_own_vehicle_counts_as_a_requested_move(game):
    """실제 플레이: '오토바이를 타고 한국 쪽으로 달린다'를 '타고 달'로 찾지 못해 이동이 막혔다(GM은 '갈 수 없다'고 서술)."""
    from survival.tools import player_asked_for
    own(game, "motorbike", place="마을")
    for text in ("오토바이를 타고 한국 쪽으로 달린다", "오토바이로 동쪽 도시까지 간다", "중고 오토바이를 몰고 출발한다"):
        game.turn_flags["player_text"] = text
        assert player_asked_for(game, "travel", {"method": "drive"}), text
    game.turn_flags["player_text"] = "마을 사람에게 길을 묻는다"
    assert not player_asked_for(game, "travel", {"method": "drive"})
    game.vehicle = None                                    # 탈것이 없으면 엔진이 거절한다
    game.turn_flags["player_text"] = "오토바이를 타고 달린다"
    assert "탈것이 없다" in call(game, "travel", method="drive", distance_km=50)["message"]


def test_jerrycan_refuels_in_the_wild(game):
    v = own(game, "motorbike", place="마을")
    v["range_km"] = 0
    game.place_type = "야생"
    assert call(game, "refuel")["success"] is False                         # 연료통이 없으면 못 넣는다
    game.items.append("휘발유 5L 연료통")
    out = call(game, "refuel")
    assert out["success"] and v["range_km"] == 100 and not any("연료통" in i for i in game.items)


def test_open_vehicles_are_exposed_to_weather(game, monkeypatch):
    seen = []
    original = type(game).pass_time

    def spy(self, hours, activity="other", sheltered=False):
        seen.append(sheltered)
        return original(self, hours, activity, sheltered)
    monkeypatch.setattr(type(game), "pass_time", spy)
    own(game, "motorbike", place="마을")
    game.place_type = "야생"
    call(game, "travel", method="drive", distance_km=50)
    game.vehicle = None
    own(game, "car", place="마을")
    game.place_type = "야생"
    call(game, "travel", method="drive", distance_km=50)
    assert seen[-2:] == [False, True]                               # 오토바이는 노출, 승용차는 지붕 아래


def test_jerrycan_when_broke_in_town(game):
    v = own(game, "car", place="마을", money=1200)
    v["range_km"] = 10
    assert game.money == 0
    game.items.append("기름통")
    out = call(game, "refuel")
    assert out["success"] and "돈이 없어" in out["message"] and v["range_km"] == 110

