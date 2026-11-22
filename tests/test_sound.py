"""배경 소리(survival/sound.py) 테스트: 게임 상태 → 소리 층 크기."""
import html
import json

from survival import sound, ui


def layers(state):
    return sound.soundscape(state)["layers"]


def test_no_sound_before_start_and_after_the_end(game):
    assert sound.soundscape(None)["key"] == "silent"
    game.status = "dead"
    assert set(layers(game).values()) == {0.0}


def test_daytime_forest_has_birds_not_crickets(game):
    l = layers(game)
    assert set(l) == set(sound.LAYERS) and all(0 <= v <= 1 for v in l.values())
    assert l["birds"] > 0.3 and l["insects"] == 0 and l["rain"] == 0 and l["thunder"] == 0
    assert l["crowd"] == 0 and l["traffic"] == 0


def test_night_brings_crickets_and_silences_birds(game):
    game.elapsed_hours = 10   # 22시
    assert game.is_night
    l = layers(game)
    assert l["birds"] == 0 and l["insects"] > 0.3


def test_cold_or_snow_has_no_insects(game):
    game.elapsed_hours = 10
    game.weather.update(temperature=-5)
    assert layers(game)["insects"] == 0


def test_rain_follows_real_precipitation_and_storm_thunders(game):
    game.weather.update(code=61, precipitation=1.0)
    light = layers(game)["rain"]
    game.weather.update(code=65, precipitation=6.0)
    heavy = layers(game)["rain"]
    assert 0 < light < heavy <= 1
    assert layers(game)["thunder"] == 0
    game.weather.update(code=95)
    assert layers(game)["thunder"] > 0


def test_wind_follows_biome_and_wind_speed(game):
    calm = layers(game)["wind"]
    game.weather.update(wind_speed=50)
    assert layers(game)["wind"] > calm
    game.weather.update(wind_speed=5)
    game.biome = "snow"
    assert layers(game)["wind"] > calm


def test_scene_contents_add_water_and_fire(game):
    game.scene_place = "강가 모래톱"
    game.scene_features = ["모닥불"]
    l = layers(game)
    assert l["stream"] > 0 and l["fire"] > 0 and l["waves"] == 0
    game.scene_place, game.scene_features, game.scene_seen_en = "해변", [], ["ocean waves"]
    l = layers(game)
    assert l["waves"] > 0 and l["fire"] == 0


def test_similar_words_are_not_water(game):
    game.scene_place = "강풍이 부는 언덕"
    game.scene_features = ["강아지", "바닥에 떨어진 나뭇가지"]
    l = layers(game)
    assert l["stream"] == 0 and l["waves"] == 0


def test_town_and_city_are_busier_than_the_wild(game):
    game.place_type = "마을"
    town = layers(game)
    game.place_type = "도시"
    city = layers(game)
    assert 0 < town["crowd"] < city["crowd"] and 0 < town["traffic"] < city["traffic"]
    game.elapsed_hours = 12   # 자정
    assert layers(game)["crowd"] < city["crowd"]


def test_indoor_muffles_outside_but_keeps_the_fire(game):
    game.weather.update(code=63, precipitation=3.0, wind_speed=30)
    outside = layers(game)
    game.set_scene("indoor", "빈 오두막 안", "inside an empty log cabin", ["벽난로"])
    cue = sound.soundscape(game)
    inside = cue["layers"]
    assert cue["indoor"] is True
    assert inside["wind"] < outside["wind"] and 0 < inside["rain"] < outside["rain"]
    assert inside["fire"] == 0.6


def test_cue_key_changes_only_when_sound_changes(game):
    first = sound.soundscape(game)["key"]
    game.turn += 1
    assert sound.soundscape(game)["key"] == first
    game.elapsed_hours = 10
    assert sound.soundscape(game)["key"] != first


def test_cue_is_rendered_safely_into_html(game):
    game.scene_place = '따옴표 "강" <b>'
    cue = sound.soundscape(game)
    rendered = ui.render_sound_cue(cue)
    assert rendered.startswith('<div id="rs-sound-cue" hidden data-cue="') and "<b>" not in rendered
    data = rendered.split('data-cue="', 1)[1].rsplit('"', 1)[0]
    assert json.loads(html.unescape(data)) == cue


def test_sound_script_is_loaded_in_head():
    head = ui.sound_head()
    assert head.startswith("<script>") and "rs-sound-cue" in head and "AudioContext" in head


def test_sound_engine_runs_in_a_fake_browser(game):
    """sound.js를 Node의 가짜 Web Audio·DOM에서 실제로 돌린다: 클릭 전 무음, 클릭 후 층 크기 적용, 끄기 버튼."""
    import shutil
    import subprocess
    from pathlib import Path

    import pytest
    node = shutil.which("node")
    if not node:
        pytest.skip("node가 없어 소리 엔진 실행 테스트를 건너뜀")
    game.scene_features = ["모닥불"]
    game.weather.update(code=61, precipitation=2.0)
    cue = dict(sound.soundscape(game), sfx=sound.turn_sfx(game))
    harness = Path(__file__).resolve().parent / "js" / "sound_harness.js"
    out = subprocess.run([node, str(harness), str(ui.SOUND_JS_PATH), json.dumps(cue)],
                         capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    result = json.loads(out.stdout.strip().splitlines()[-1])
    assert result["controls"] is True
    assert result["beforeClick"]["running"] is False
    assert set(v for v in result["beforeClick"]["levels"].values()) == {None}   # 클릭 전에는 소리 장치도 없다
    after = result["afterClick"]
    assert after["running"] is True
    assert after["levels"]["fire"] > 0 and after["levels"]["rain"] > 0 and after["levels"]["birds"] > 0
    assert after["levels"]["thunder"] == 0 and after["levels"]["waves"] == 0
    assert result["occasionalPlayed"] > 0
    assert result["muted"]["on"] is False and "🔇" in result["muted"]["label"]
    assert json.loads(result["muted"]["saved"])["on"] is False
    assert result["errors"] == []
    assert set(result["effects"]) == set(sound.SFX)          # 엔진이 고르는 효과음을 브라우저가 모두 안다
    assert result["sfxPlayed"] > len(sound.SFX)              # 모든 효과음이 오류 없이 울렸다
    assert result["sfxReplayed"] == 0 and result["sfxWhileMuted"] == 0
    assert result["hidden"] == {"running": False, "played": 0} and result["visibleAgain"] is True


# ---------- 사건 효과음 ----------
def sfx(state):
    return sound.turn_sfx(state)["events"]


def test_quiet_turn_has_no_effects(game):
    game.turn_flags = {"travel": 0, "time": 0, "intake": False, "consumed": False}
    assert sfx(game) == [] and sound.turn_sfx(None) == {"events": [], "nonce": ""}


def test_effects_follow_what_happened(game):
    game.turn_flags = {"attempt": {"success": True}, "moved": {"how": "도보", "km": 5}}
    assert sfx(game) == ["success", "travel"]
    game.turn_flags = {"attempt": {"success": False}, "arrested": {"where": "검문소"}}
    assert sfx(game) == ["arrest", "fail"]
    game.turn_flags = {"new_lead": "L1"}
    assert sfx(game) == ["clue"]
    game.turn_flags = {"lead_result": {"danger": False}, "new_lead": "L2"}
    assert sfx(game) == ["discover"]                       # 단서를 확인한 턴에는 새 단서 소리를 겹치지 않는다
    game.turn_flags = {"offer_declined": {"accept": "트럭에 탄다"}}
    assert sfx(game) == ["dismiss"]


def test_danger_offer_and_lucky_events(game):
    game.turn_flags = {}
    game.event = {"kind": "danger", "text": "늑대"}
    assert sfx(game) == ["danger"]
    game.event = {"kind": "lucky", "text": "열매"}
    game.offer = {"id": "trucker", "turn": game.turn, "accept": "트럭에 탄다"}
    assert sfx(game) == ["offer", "lucky"]
    game.offer["turn"] = game.turn - 1                     # 지난 턴에 나온 기회는 다시 울리지 않는다
    assert sfx(game) == ["lucky"]


def test_at_most_three_effects_most_important_first(game):
    game.turn_flags = {"arrested": {"where": "검문소"}, "attempt": {"success": False}, "new_lead": "L1",
                       "ticket": {"item": "버스표"}, "moved": {"how": "버스"}}
    game.event = {"kind": "danger"}
    assert sfx(game) == ["arrest", "fail", "danger"]


def test_win_and_death_replace_everything(game):
    game.turn_flags = {"moved": {}, "attempt": {"success": True}}
    game.status = "won"
    assert sfx(game) == ["win"]
    game.status = "dead"
    assert sfx(game) == ["death"]


def test_nonce_changes_every_turn_and_game(game):
    first = sound.turn_sfx(game)["nonce"]
    assert sound.turn_sfx(game)["nonce"] == first          # 같은 턴의 화면 갱신은 같은 값
    game.turn += 1
    game.elapsed_hours += 0.5
    assert sound.turn_sfx(game)["nonce"] != first
    game.turn, game.elapsed_hours, game.lat = 0, 0, game.lat + 1   # 새 게임의 같은 턴 번호
    assert sound.turn_sfx(game)["nonce"] != first


def test_every_engine_effect_is_known():
    assert set(sound.SFX) == {"win", "death", "arrest", "success", "fail", "danger", "offer", "discover", "clue",
                              "lucky", "engine", "ticket", "travel", "dismiss"}


def test_resume_view_sends_the_turn_without_effects(game, monkeypatch):
    """이어하기 화면은 저장된 마지막 턴의 효과음을 다시 울리지 않는다(같은 nonce, 빈 목록)."""
    import app
    game.turn_flags = {"attempt": {"success": True}}
    loud = app.sound_cue(game)
    quiet = app.sound_cue(game, quiet=True)

    def payload(rendered):
        return json.loads(html.unescape(rendered.split('data-cue="', 1)[1].rsplit('"', 1)[0]))
    assert payload(loud)["sfx"]["events"] == ["success"]
    assert payload(quiet)["sfx"] == {"events": [], "nonce": payload(loud)["sfx"]["nonce"]}
    assert payload(quiet)["layers"] == payload(loud)["layers"]


def test_critical_success_sparkles(game):
    game.turn_flags = {"attempt": {"success": True, "critical": True}}
    assert sfx(game) == ["success", "lucky"]

