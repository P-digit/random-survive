"""의뢰(사이드 미션): 배달과 밀수 (survival/missions.py)."""
from types import SimpleNamespace

import pytest

from survival import geo, gamemaster, missions, sound
from survival import state as state_module
from tests.helpers import call, reply_with


def offered(game, kind="deliver", place="도시", monkeypatch=None):
    """의뢰가 지난 턴에 제안된 상태를 만든다."""
    game.place_type = place
    city, km = missions.pick_destination(game.lat, game.lon)
    game.mission_offer = {"kind": kind, "giver": "화물 중개인", "item": missions.PACKAGE[kind], "target": city["name"],
                          "lat": city["lat"], "lon": city["lon"], "country": city["country"], "km": km,
                          "direction": "동쪽", "reward": missions.reward_for(kind, km),
                          "hours": missions.deadline_hours(kind, km), "turn": game.turn}
    game.turn += 1
    game.turn_flags = {"travel": 0, "time": 0, "intake": False, "consumed": False}
    return game.mission_offer


def test_destination_is_a_real_city_toward_korea(game):
    city, km = missions.pick_destination(game.lat, game.lon)
    assert city and missions.DELIVERY_RANGE[0] <= km <= missions.DELIVERY_RANGE[1]
    assert geo.distance_to_korea(city["lat"], city["lon"]) < geo.distance_to_korea(game.lat, game.lon)


def test_rewards_and_deadlines_scale_with_distance():
    assert missions.reward_for("deliver", 400) == 100 and missions.reward_for("smuggle", 400) == 310
    assert missions.deadline_hours("deliver", 400) == 34


def test_mission_givers_appear_only_in_towns(game, monkeypatch):
    monkeypatch.setattr(missions.random, "random", lambda: 0.0)
    game.place_type = "야생"
    assert game.roll_mission() is None
    game.place_type = "도시"
    offer = game.roll_mission()
    assert offer and offer["turn"] == game.turn and game.turn_flags["mission"]["phase"] == "offered"
    assert offer["kind"] == "smuggle"                                   # 주사위 0.0 → 밀수 쪽
    assert game.roll_mission() is None                                  # 제안이 있으면 새로 나오지 않는다


def test_accepting_words():
    a = missions.accepts_mission
    assert a("의뢰를 맡겠다고 한다") and a("좋아, 내가 배달하겠다") and a("수락한다")
    assert not a("의뢰는 거절한다") and not a("빵을 산다") and not a("싫어, 안 해")


def test_accepting_gives_the_package(game):
    offer = offered(game)
    out = game.resolve_mission_offer("의뢰를 맡겠다고 한다")
    assert out["accepted"] and game.mission["target"] == offer["target"]
    assert offer["item"] in game.items and game.mission_offer is None
    assert game.mission["deadline"] == pytest.approx(game.elapsed_hours + offer["hours"])


def test_ignoring_lets_the_offer_pass(game):
    offered(game)
    assert game.resolve_mission_offer("시장에서 빵을 산다") == {"accepted": False}
    assert game.mission is None and game.turn_flags["mission"]["phase"] == "passed"


def test_arriving_completes_and_pays(game):
    offer = offered(game)
    game.resolve_mission_offer("맡겠다")
    game.lat, game.lon = offer["lat"], offer["lon"]
    assert game.check_mission() == "done"
    assert game.money == 50 + offer["reward"] and offer["item"] not in game.items and game.mission is None
    assert any("의뢰" in f["text"] for f in game.facts)
    notices = gamemaster.collect_notices(game)
    assert any(n["title"].startswith("📦 의뢰 완료") for n in notices)
    assert "success" in sound.turn_sfx(game)["events"]


def test_deadline_and_lost_package_fail(game):
    offered(game)
    game.resolve_mission_offer("맡겠다")
    game.elapsed_hours = game.mission["deadline"] + 1
    assert game.check_mission() == "failed" and "기한" in game.turn_flags["mission"]["why"]
    offered(game)
    game.resolve_mission_offer("맡겠다")
    game.items.remove(game.mission["item"])
    assert game.check_mission() == "failed" and "잃었다" in game.turn_flags["mission"]["why"]


def test_smuggling_is_confiscated_on_arrest(game):
    offered(game, kind="smuggle")
    game.resolve_mission_offer("맡겠다")
    assert game.carrying_contraband and game.mission["item"] in game.stolen_items
    game.wanted = 30
    game._arrest("검문")
    assert game.check_mission() == "failed"


def test_customs_can_stop_contraband_at_a_border(game, monkeypatch):
    offered(game, kind="smuggle")
    game.resolve_mission_offer("맡겠다")
    game.country_code = "mn"
    monkeypatch.setattr(missions.random, "random", lambda: 0.0)
    monkeypatch.setattr(geo, "reverse_geocode", lambda lat, lon: {"name": "국경 너머", "country_code": "cn"})
    game.place_type = "마을"
    game.begin_turn()
    game.turn_flags["player_text"] = "버스를 타고 간다"
    call(game, "travel", method="bus", distance_km=100)
    assert game.pursuit and "세관" in game.pursuit["who"]


def test_go_to_the_mission_target(game):
    offer = offered(game)
    game.resolve_mission_offer("맡겠다")
    game.money = 500
    game.begin_turn()
    game.turn_flags["player_text"] = "의뢰 목적지로 간다"
    out = call(game, "go_to", target="mission")
    assert out["success"] and offer["target"] in out["message"]                  # 기차로 그 도시에 도착
    game.end_turn(0.5)
    assert game.turn_flags["mission"]["phase"] == "done" and game.money > 500


def test_full_turns_with_the_gm(game, monkeypatch):
    monkeypatch.setattr(state_module, "roll_event", lambda *a, **k: None)
    monkeypatch.setattr(state_module, "roll_major_event", lambda *a, **k: None)
    monkeypatch.setattr(missions, "MISSION_CHANCE", {"도시": 1.0, "마을": 1.0})
    monkeypatch.setattr(missions, "SMUGGLE_SHARE", 0.0)
    game.place_type = "도시"
    reply_with(monkeypatch, SimpleNamespace(id="r", output=[], output_text="중개인이 다가온다."))
    gamemaster.run_turn(game, "시장을 둘러본다")
    assert game.mission_offer and game.suggestions[0] == "의뢰를 맡겠다고 한다"
    assert any(n["title"].startswith("📦 의뢰 —") for n in game.notices)

    seen = []

    def create(**kwargs):
        seen.append(kwargs)
        return SimpleNamespace(id="r2", output=[], output_text="소포를 받아 든다.")
    monkeypatch.setattr(gamemaster, "get_client", lambda: SimpleNamespace(responses=SimpleNamespace(create=create)))
    gamemaster.run_turn(game, game.suggestions[0])
    assert game.mission and "[의뢰 수락 - 엔진이 처리했다]" in seen[0]["input"] and "[맡은 의뢰]" in seen[0]["input"]


def test_errand_runner_achievement(game):
    for _ in range(3):
        offer = offered(game)
        game.resolve_mission_offer("맡겠다")
        game.lat, game.lon = offer["lat"], offer["lon"]
        game.end_turn(0.5)
    assert "errand_runner" in game.achievements and game.stats["missions"] == 3


def test_old_saves_load_without_missions(game):
    from dataclasses import asdict
    from survival.state import GameState
    data = asdict(game)
    data.pop("mission")
    data.pop("mission_offer")
    again = GameState(**data)
    assert again.mission is None and not again.carrying_contraband


def test_asking_for_work_brings_a_mission_giver(game, monkeypatch):
    """3회차 플레이 테스트: '의뢰가 있는지 묻는다'에 매번 '의뢰는 없다'는 답만 돌아왔다."""
    monkeypatch.setattr(missions.random, "random", lambda: 0.5)          # 평소 확률(15%)로는 안 나오는 값
    game.place_type = "야생"
    assert game.seek_mission("의뢰가 있는지 사람들에게 묻는다") is None
    game.place_type = "도시"
    assert game.roll_mission() is None
    offer = game.seek_mission("의뢰가 있는지 사람들에게 묻는다")             # 직접 찾으면 70%
    assert offer and game.turn_flags["mission"]["phase"] == "offered"
    assert game.seek_mission("일거리를 찾는다") is None                      # 이미 제안이 있다
