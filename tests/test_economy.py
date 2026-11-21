"""경제: 일자리와 기술, 물건 팔기, 방 빌리기(은신처), 도박 (survival/economy.py)."""
import json
from types import SimpleNamespace

import pytest

from survival import economy, gamemaster, police, sound
from survival.tools import execute_tool
from survival.ui import render_hud
from tests.helpers import call, reply_with


def town(game, place="마을", hour=12):
    game.place_type = place
    game.elapsed_hours = (hour - game.start_hour) % 24
    game.begin_turn()
    return game


def test_wages_depend_on_place_time_and_skill(game):
    assert game.work_wage("labor")[0] == 0                          # 야생에는 일자리가 없다
    town(game, "마을")
    assert game.work_wage("labor")[0] == 2.0
    game.place_type = "도시"
    assert game.work_wage("labor")[0] == 4.0 and game.work_wage("skilled")[0] == 8.0
    game.skills["labor"] = 2
    assert game.work_wage("labor")[0] == pytest.approx(4.0 * 1.3)
    town(game, "도시", hour=2)
    assert game.work_wage("service")[0] == 0 and game.work_wage("street")[0] > 0   # 한밤중엔 길거리 일만


def test_working_pays_passes_time_and_builds_skill(game):
    town(game, "도시")
    hours = game.elapsed_hours
    out = call(game, "work", job="labor", hours=8)
    assert out["success"] and out["earned"] == 32 and game.money == 82
    assert game.elapsed_hours - hours == 8 and game.turn_flags["time"] == 1
    assert game.skills["labor"] == 1 and game.turn_flags["economy"]["leveled"]
    game.begin_turn()
    assert call(game, "work", job="labor", hours=8)["earned"] == pytest.approx(8 * 4.0 * 1.15)


def test_gm_cannot_pay_wages_or_sales_itself(game):
    town(game)
    out = call(game, "update_status", health=0, satiety=0, hydration=0, energy=0, money=30, money_source="work",
               consumed_items=[], reason="일당")
    assert "work 툴" in out["error"] and game.money == 50
    out = call(game, "update_status", health=0, satiety=0, hydration=0, energy=0, money=30, money_source="sold",
               consumed_items=[], reason="칼을 팖")
    assert "sell_item" in out["error"] and game.money == 50


def test_selling_uses_the_engine_price(game):
    assert call(game, "sell_item", item="다용도 칼")["success"] is False     # 야생에서는 팔 수 없다
    town(game, "도시")
    out = call(game, "sell_item", item="스마트폰")
    assert out["earned"] == 48 and game.money == 98 and not any("스마트폰" in i for i in game.items)
    assert call(game, "sell_item", item="여권")["success"] is False          # 여권은 팔 수 없다
    game.items.append("금목걸이")
    game.stolen_items.append("금목걸이")
    game.place_type = "마을"
    assert call(game, "sell_item", item="금목걸이")["earned"] == 15          # 50 × 0.6 × 장물 0.5


def test_rented_room_is_a_safehouse(game):
    town(game, "도시")
    game.wanted = 50
    outside = game.police_encounter_chance()
    out = call(game, "rent_room", nights=2)
    assert out["success"] and game.money == 10 and game.in_lodging and game.indoor
    assert game.police_encounter_chance() == pytest.approx(outside * economy.SAFEHOUSE_POLICE, abs=0.002)
    game.turn_flags["laying_low"] = True
    game.pass_time(5, "rest")
    assert game.wanted == pytest.approx(50 - 0.3 * 5 * economy.SAFEHOUSE_LAY_LOW)   # 은신처에서는 6배
    assert "LIFE" in render_hud(game) and "지금 은신 중" in render_hud(game)
    assert "은신처" in game.summary()["빌린_방"]


def bet(state, **args):
    """gamble 툴 호출 (툴 인자 'game'이 call()의 첫 인자 이름과 겹쳐서 따로 둔다)."""
    return json.loads(execute_tool(state, "gamble", json.dumps(args)))


def test_gambling(game, monkeypatch):
    assert bet(game, stake=10, game="카드")["success"] is False   # 야생에는 도박판이 없다
    town(game, "도시")
    monkeypatch.setattr(economy.random, "random", lambda: 0.1)
    assert bet(game, stake=10, game="카드")["change"] == 10 and game.money == 60
    game.begin_turn()
    monkeypatch.setattr(economy.random, "random", lambda: 0.6)
    assert bet(game, stake=500, game="주사위")["change"] == -60 and game.money == 0   # 가진 돈까지만
    game.money = 20
    game.begin_turn()
    monkeypatch.setattr(economy.random, "random", lambda: 0.99)
    out = bet(game, stake=20, game="슬롯")
    assert out["jackpot"] and game.money == 120 and sound.turn_sfx(game)["events"] == ["lucky"]


def test_economy_notices_replace_the_missing_money_notice(game, monkeypatch):
    town(game, "도시")
    tool = SimpleNamespace(id="r1", output_text="", output=[SimpleNamespace(
        type="function_call", name="work", call_id="a", arguments=json.dumps({"job": "service", "hours": 4}))])
    reply_with(monkeypatch, tool, SimpleNamespace(id="r2", output=[], output_text="식당에서 설거지를 돕는다."))
    gamemaster.run_turn(game, "식당에서 일한다")
    titles = [n["title"] for n in game.notices]
    assert any(t.startswith("💼 일 — 서비스 4시간, +$20") for t in titles)
    assert not any(t.startswith("💵 수입") for t in titles)                # 같은 돈을 두 번 알리지 않는다
    assert "ticket" in sound.turn_sfx(game)["events"]


def test_old_saves_load_without_economy_fields(game):
    from dataclasses import asdict
    from survival.state import GameState
    data = asdict(game)
    for key in ("skills", "work_hours", "lodging"):
        data.pop(key)
    again = GameState(**data)
    assert again.skills == {} and not again.in_lodging and police.heat_stage(again.wanted) == 0
