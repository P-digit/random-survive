"""경찰과 추격 (survival/police.py) 테스트."""
import json
from dataclasses import asdict
from types import SimpleNamespace

import pytest

from survival import gamemaster, police, sound
from survival.state import GameState
from tests.helpers import call, fix_roll, reply_with


def rolls(monkeypatch, *values):
    it = iter(values)
    monkeypatch.setattr(police.random, "random", lambda: next(it))


def spotted(game, wanted=50, place="도시"):
    """경찰이 지난 턴에 나타난 상태를 만든다 (이번 턴의 입력이 그 대응이다)."""
    game.place_type, game.wanted = place, wanted
    game.pursuit = {"stage": police.heat_stage(wanted), "turn": game.turn, "who": "순찰 중인 경찰관 두 명",
                    "kind": "check", "stolen_vehicle": False}
    game.turn += 1
    game.turn_flags = {"travel": 0, "time": 0, "intake": False, "consumed": False}
    return game


def test_stages_and_stars():
    assert [police.heat_stage(w) for w in (0, 1, 19, 20, 40, 60, 79, 80, 100)] == [0, 1, 1, 2, 3, 4, 4, 5, 5]
    assert police.stars(45) == "★★★☆☆"


def test_encounter_chance_depends_on_place_time_and_looks(game):
    game.wanted = 10
    assert game.police_encounter_chance() == 0                       # ★1(소문)에는 경찰이 찾지 않는다
    game.wanted = 50                                                 # ★3
    game.place_type = "도시"
    city = game.police_encounter_chance()
    game.place_type = "마을"
    village = game.police_encounter_chance()
    game.place_type = "야생"
    wild = game.police_encounter_chance()
    game.flags["on_road"] = True
    road = game.police_encounter_chance()
    assert city > village > road > wild > 0
    game.place_type = "도시"
    game.put_on_disguise("모자와 선글라스")
    assert game.police_encounter_chance() < city                     # 변장하면 덜 알아본다
    game.disguise = {}
    game.vehicle = {"kind": "car", "name": "훔친 차", "range_km": 100, "stolen": True}
    assert game.police_encounter_chance() > city                     # 도난 차량은 눈에 띈다


def test_police_appear_and_chase_at_high_stages(game, monkeypatch):
    monkeypatch.setattr(police.PoliceMixin, "police_encounter_chance", lambda self: 1.0)
    fix_roll(monkeypatch, 0.0)
    game.place_type, game.wanted = "도시", 45                          # ★3 → 검문
    assert game.roll_police()["kind"] == "check"
    assert game.roll_police() is None                                # 이미 마주친 경찰이 있으면 새로 나오지 않는다
    game.pursuit, game.wanted = None, 85                              # ★5 → 특공대와 헬기, 추격
    p = game.roll_police()
    assert p["kind"] == "chase" and "헬기" in p["who"] and game.turn_flags["police"]["phase"] == "spotted"


def test_player_words_become_responses():
    c = police.classify_response
    assert c("골목으로 전력 질주해 도망친다") == "flee"
    assert c("쓰레기통 뒤에 몸을 숨긴다") == "hide"
    assert c("경찰에게 돈을 쥐여 주며 눈감아 달라고 한다") == "bribe"
    assert c("관광객인 척 여권을 보여 주며 둘러댄다") == "bluff"
    assert c("경찰을 밀치고 주먹을 휘두른다") == "fight"
    assert c("두 손을 들고 자수한다") == "surrender"
    assert c("빵을 사러 가게에 들어간다") == "ignore"


def test_fleeing_successfully(game, monkeypatch):
    spotted(game, wanted=50)
    rolls(monkeypatch, 0.0, 0.5)                                     # 성공, 극적이지 않음
    out = game.respond_to_police("flee")
    assert out["outcome"] == "escaped" and game.pursuit is None and game.wanted == pytest.approx(45, abs=0.5)


def test_movie_escape_cuts_more(game, monkeypatch):
    spotted(game, wanted=50)
    rolls(monkeypatch, 0.0, 0.9)                                     # 성공, 극적인 탈출
    out = game.respond_to_police("flee")
    assert "영화 같은 탈출" in out["message"] and game.wanted == pytest.approx(35, abs=0.5)


def test_failed_flight_ends_in_arrest(game, monkeypatch):
    spotted(game, wanted=50)
    game.money = 100
    hours = game.elapsed_hours
    rolls(monkeypatch, 0.99, 0.0)
    out = game.respond_to_police("flee")
    assert out["outcome"] == "arrested" and game.turn_flags["arrested"]
    assert game.money == 50 and game.elapsed_hours - hours >= 24 and game.pursuit is None


def test_surrender_is_lighter(game):
    spotted(game, wanted=50)
    game.money = 100
    hours = game.elapsed_hours
    out = game.respond_to_police("surrender")
    assert out["outcome"] == "arrested" and game.money == 75                     # 벌금 25%
    assert 12 <= game.elapsed_hours - hours < 24 and game.wanted == pytest.approx(0, abs=1)
    assert game.turn_flags["arrested"]["hours"] == 12 and game.turn_flags["time"] == 1   # GM이 시간을 또 흘리지 못함
    assert any("12시간 구금" in n["text"] for n in gamemaster.collect_notices(game))


def test_bribe_needs_money(game, monkeypatch):
    spotted(game, wanted=50)                                         # ★3 → $80
    game.money = 200
    rolls(monkeypatch, 0.0, 0.5)
    out = game.respond_to_police("bribe")
    assert out["outcome"] == "escaped" and game.money == 120 and game.wanted == pytest.approx(25, abs=0.5)
    assert game.turn_flags["money_log"][-1] == {"amount": -80, "why": "경찰 뇌물"}

    spotted(game, wanted=50)
    game.money = 10                                                  # 돈이 모자라면 뇌물은 통하지 않는다
    rolls(monkeypatch, 0.0, 0.5)
    assert game.respond_to_police("bribe")["outcome"] == "arrested"


def test_fighting_the_police_costs_heat(game, monkeypatch):
    spotted(game, wanted=50)
    rolls(monkeypatch, 0.0, 0.5)
    out = game.respond_to_police("fight")
    assert out["outcome"] == "escaped" and game.wanted == pytest.approx(70, abs=0.5) and game.health == 90


def test_ignoring_the_police_usually_ends_in_arrest(game, monkeypatch):
    spotted(game, wanted=50)
    rolls(monkeypatch, 0.5)
    assert game.respond_to_police("ignore")["outcome"] == "arrested"
    spotted(game, wanted=50)
    rolls(monkeypatch, 0.9)
    assert game.respond_to_police("ignore")["outcome"] == "lost"


def test_laying_low_and_disguise(game):
    game.wanted = 30
    game.turn_flags["laying_low"] = True
    game.pass_time(5, "rest")
    assert game.wanted == pytest.approx(30 - 0.3 * 5 * 4)           # 4배 빨리 내려간다
    game.put_on_disguise("머리를 자르고 옷을 갈아입는다")
    assert game.disguised
    game.elapsed_hours += 49
    assert not game.disguised                                        # 48시간이 지나면 풀린다


def test_witnessed_crime_blows_the_disguise(game, monkeypatch):
    game.begin_turn()
    game.put_on_disguise("모자")
    fix_roll(monkeypatch, 0.0)
    monkeypatch.setattr(police.random, "random", lambda: 0.0)
    game.attempt("소매치기", "normal", crime="절도", witnessed="bystanders")
    assert not game.disguised


def test_full_turns_with_the_gm(game, monkeypatch):
    """N턴: 경찰이 나타난다(GM은 체포할 수 없다) → N+1턴: '도망친다'를 GM보다 먼저 엔진이 판정한다."""
    monkeypatch.setattr(police.PoliceMixin, "police_encounter_chance", lambda self: 1.0)
    from survival import state as state_module
    monkeypatch.setattr(state_module, "roll_event", lambda *a, **k: None)
    monkeypatch.setattr(state_module, "roll_major_event", lambda *a, **k: None)
    game.place_type, game.wanted = "도시", 50
    arrest = SimpleNamespace(id="r1", output_text="", output=[SimpleNamespace(
        type="function_call", name="arrest", call_id="a", arguments=json.dumps({"reason": "검문"}))])
    fix_roll(monkeypatch, 0.0)
    reply_with(monkeypatch, arrest, SimpleNamespace(id="r2", output=[], output_text="경찰관 두 명이 다가온다."))
    gamemaster.run_turn(game, "시장을 걷는다")
    assert game.pursuit and not game.turn_flags.get("arrested")               # GM의 체포는 막혔다
    assert any(n["title"].startswith("🚔 경찰") for n in game.notices)
    assert sound.turn_sfx(game)["events"][0] == "arrest"
    assert game.suggestions == ["관광객인 척 태연하게 둘러댄다", "틈을 봐서 골목으로 도망친다", "순순히 손을 들고 자수한다"]
    assert {police.classify_response(t) for t in game.suggestions} == {"bluff", "flee", "surrender"}

    seen = []

    def create(**kwargs):
        seen.append(kwargs)
        return SimpleNamespace(id="r3", output=[], output_text="당신은 골목으로 뛰어들어 경찰을 따돌린다.")
    monkeypatch.setattr(gamemaster, "get_client", lambda: SimpleNamespace(responses=SimpleNamespace(create=create)))
    rolls(monkeypatch, 0.0, 0.5)
    fix_roll(monkeypatch, 0.0)
    gamemaster.run_turn(game, "골목으로 도망친다")
    assert game.pursuit is None and game.turn_flags["police"]["outcome"] == "escaped"
    assert "[경찰 대응 결과 - 엔진이 이미 판정했다]" in seen[0]["input"]
    assert any(n["title"].startswith("🏃 경찰에게서 벗어났다") for n in game.notices)
    assert call(game, "attempt_action", action="도망", difficulty="normal", crime="none", witnessed="none",
                violent=False, item="", stealth=False, success_money=0, success_items=[], victim="")["error"]


def test_old_saves_load_without_police_fields(game):
    data = asdict(game)
    data.pop("pursuit")
    data.pop("disguise")
    again = GameState(**json.loads(json.dumps(data, ensure_ascii=False)))
    assert again.pursuit is None and again.disguise == {} and not again.disguised


def test_custody_does_not_starve_you(game, monkeypatch):
    """실제 플레이에서 찾은 문제: 지친 상태로 체포되면 구금 24시간 동안 굶어 감옥에서 죽었다."""
    spotted(game, wanted=65)
    game.satiety, game.hydration, game.energy, game.health = 3, 2, 5, 25
    rolls(monkeypatch, 0.99, 0.0)
    out = game.respond_to_police("flee")
    assert out["outcome"] == "arrested" and game.status == "playing"
    assert game.satiety > 20 and game.hydration > 20


def test_lay_low_and_disguise_words_in_conjugated_forms():
    """실제 플레이 입력: '숨어 지낸다'를 '숨어 지내'로는 찾지 못했다(낸 ≠ 내)."""
    m = police.mentions
    for text in ("허름한 창고에 숨어 지낸다", "며칠 조용히 지낸다", "은신처에서 몸을 숨기고 쉰다", "잠적한다"):
        assert m(text, police.LAY_LOW_WORDS), text
    for text in ("머리를 짧게 자른다", "수염을 민다", "모자를 눌러쓰고 선글라스를 낀다", "스카프로 얼굴을 가린다"):
        assert m(text, police.DISGUISE_WORDS), text
    assert not m("물을 마시고 쉰다", police.LAY_LOW_WORDS)


def test_lay_low_turn_lowers_heat_faster(game, monkeypatch):
    game.wanted = 30
    reply_with(monkeypatch, SimpleNamespace(id="r", output=[], output_text="창고 구석에 몸을 웅크리고 숨어 지낸다."))
    gamemaster.run_turn(game, "허름한 창고에 숨어 지낸다")
    hours = game.delta["hours"]
    assert game.turn_flags["laying_low"] and game.wanted == pytest.approx(30 - 0.3 * hours * 4, abs=0.01)

