"""여정 기록과 업적 (survival/achievements.py)."""
from types import SimpleNamespace

from survival import achievements, gamemaster, sound
from tests.helpers import reply_with


ESCAPED = {"phase": "resolved", "action": "flee", "outcome": "escaped", "chance": 0.5, "effects": [], "who": "경찰"}


def end(game, **flags):
    """한 턴을 이 기록으로 끝낸다."""
    game.begin_turn()
    game.turn_flags.update(flags)
    game.end_turn(0.5)
    return game.turn_flags.get("achievements") or []


def test_stats_come_from_the_turn_record(game):
    end(game, moved={"how": "도보", "km": 20}, earned=12, paid=5)
    end(game, attempt={"illegal": True, "critical": True}, economy={"kind": "work", "hours": 6})
    end(game, police=ESCAPED, arrested={"where": "x"}, vehicle={"name": "차"})
    st = game.stats
    assert st["walked_km"] == 20
    assert st["turns"] == 3 and st["km"] == 20 and st["earned"] == 12 and st["spent"] == 5
    assert st["crimes"] == 1 and st["criticals"] == 1 and st["work_hours"] == 6
    assert st["escapes"] == 1 and st["arrests"] == 1 and st["vehicles"] == 1


def test_achievements_unlock_once_with_a_notice_and_sound(game, monkeypatch):
    assert end(game, moved={"how": "도보", "km": 20}) == ["first_steps"]
    assert end(game, moved={"how": "도보", "km": 20}) == []                # 한 번만
    for _ in range(3):
        unlocked = end(game, police=ESCAPED)
    assert unlocked == ["escape_artist"] and game.achievements == ["first_steps", "escape_artist"]
    notices = gamemaster.collect_notices(game)
    assert any(n["title"] == "🏆 업적 — 탈주 전문가" for n in notices)
    assert sound.turn_sfx(game)["events"][0] == "discover"


def test_countries_and_heat(game):
    for code in ("mn", "cn", "kz"):
        game.country_code = code
        end(game)
    assert game.stats["countries"] == ["mn", "cn", "kz"] and "globetrotter" in game.achievements
    game.wanted = 85
    end(game)
    assert game.stats["max_heat"] == 5 and "most_wanted" in game.achievements


def test_winning_clean_and_rich(game):
    game.money = 1500
    game.status = "won"
    end(game)
    assert {"law_abiding", "rich_return", "speedrun", "bare_feet"} <= set(game.achievements)
    summary = achievements.run_summary(game)
    assert "귀환 성공" in summary and "금의환향" in summary and "명예의 전당" in summary


def test_hall_of_fame_persists_across_runs(game, tmp_path):
    end(game, moved={"how": "도보", "km": 20})
    hall = achievements.load_hall()
    assert hall["first_steps"]["count"] == 1
    from survival.state import GameState
    other = GameState(lat=game.lat, lon=game.lon, place_name="x", weather=game.weather, biome="forest")
    end(other, moved={"how": "도보", "km": 5})
    assert achievements.load_hall()["first_steps"]["count"] == 2


def test_hall_of_fame_can_be_disabled(game, monkeypatch):
    monkeypatch.setattr(achievements, "HALL_ENABLED", False)
    end(game, moved={"how": "도보", "km": 20})
    assert achievements.load_hall() == {} and "first_steps" in game.achievements


def test_game_over_shows_the_run_summary(game, monkeypatch):
    import app
    game.health = 1
    reply_with(monkeypatch, SimpleNamespace(id="r", output=[], output_text="당신은 쓰러진다."))
    game.hydration = game.satiety = 0
    outputs = list(app.play("사막을 계속 걷는다", game, False))
    final_chat = outputs[-1][1]
    assert game.status == "dead" and "여정 결산" in final_chat[-1]["content"]
    assert game.death_reason in final_chat[-1]["content"]                     # 사망 원인도 보여 준다


def test_old_saves_load_without_stats(game):
    from dataclasses import asdict
    from survival.state import GameState
    data = asdict(game)
    data.pop("stats")
    data.pop("achievements")
    again = GameState(**data)
    assert again.stats == {} and again.achievements == []
