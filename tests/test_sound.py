"""배경 소리(survival/sound.py) 테스트: 게임 상태 → 소리 층 크기."""
import html
import json

from survival import sound, ui
from tests import test_engine

game = test_engine.game   # 게임 상태 픽스처 재사용 (몽골, 온대림, 1일차 12시, 맑음)


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
    cue = sound.soundscape(game)
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
