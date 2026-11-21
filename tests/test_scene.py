"""장면과 그림: 장면 유지·그림 지시문·편집·Vision (survival/imagegen.py, app.py) 테스트."""
import sys
from types import SimpleNamespace

from survival import climate, gamemaster, imagegen
from tests.helpers import call


def test_image_prompt_shows_weather_and_no_weapons(game):
    game.weather.update(code=65, description_en="heavy rain", wind_speed=50)
    prompt = imagegen.build_prompt(game)
    assert "raining" in prompt and "Strong wind" in prompt and "no guns" in prompt
    assert "first-person" not in prompt
    game.weather.update(code=75, wind_speed=5)
    assert "snowing" in imagegen.build_prompt(game)
    game.weather.update(code=0)
    assert "IMPORTANT" not in imagegen.build_prompt(game)


def test_scene_change_triggers_redraw_and_shelter(game):
    game.scene_dirty = False
    assert call(game, "set_scene", setting="indoor", place="빈 오두막 안",
                description_en="Inside a small abandoned log cabin with a rusty stove.")["장면이_바뀜"]
    assert game.indoor and game.scene_dirty
    prompt = imagegen.build_prompt(game)
    assert "interior" in prompt.lower() and "log cabin" in prompt and "no guns" in prompt

    game.scene_dirty = False               # 같은 곳이면 다시 그리지 않는다
    assert not call(game, "set_scene", setting="indoor", place="빈 오두막 안", description_en="same")["장면이_바뀜"]
    assert not game.scene_dirty

    game.weather.update(feels_like=-25.0, temperature=-20.0)   # 실내에서는 혹한 피해가 줄어든다
    inside = game.health
    game.pass_time(4, "rest")
    inside_loss = inside - game.health
    game.set_scene("outdoor", "오두막 앞 눈밭", "Snowy clearing in front of a cabin.")
    outside = game.health
    game.pass_time(4, "rest")
    assert outside - game.health > inside_loss * 2

    game.begin_turn()
    call(game, "travel", method="walk", distance_km=10)        # 이동하면 장면은 새 장소의 야외로 초기화
    assert not game.indoor and game.scene_place == "" and game.scene_dirty


def test_image_matches_declared_scene(game):
    game.climate = climate.make_climate("continental", 60, 1)
    game.set_scene("outdoor", "숲 가장자리", "A snowy forest edge with an abandoned log cabin by a frozen stream.",
                   ["버려진 오두막", "얼어붙은 개울"])
    prompt = imagegen.build_prompt(game)
    assert "abandoned log cabin" in prompt and "boreal conifer forest" in prompt and "winter" in prompt
    assert not imagegen.HANGUL.search(prompt)                # 그림 지시문에는 한글이 없다
    assert "untouched nature with no trace of people" in prompt   # 야생에서는 밝히지 않은 건물을 그리지 않는다

    game.scene_seen = ["버려진 오두막", "낡은 헛간"]        # Vision이 그림에서 추가로 발견한 것
    game.begin_turn()
    text = gamemaster.build_input(game, "헛간에 들어간다")
    assert "[화면에 보이는 것" in text and "낡은 헛간" in text and "얼어붙은 개울" in text
    assert "기후" in text and "냉대 기후" in text

    game.set_scene("indoor", "오두막 안", "Inside the cabin.", ["녹슨 난로"])
    assert game.scene_seen == [] and game.visible_things() == ["녹슨 난로"]


def test_describe_image_reads_back_what_was_drawn(tmp_path):
    path = tmp_path / "scene.png"
    path.write_bytes(b"\x89PNG fake")
    seen = {}

    def fake_create(**kwargs):
        seen.update(kwargs)
        return SimpleNamespace(output_text="통나무 오두막, 얼어붙은 호수,\n침엽수림.")

    client = SimpleNamespace(responses=SimpleNamespace(create=fake_create))
    assert imagegen.describe_image(client, str(path)) == ["통나무 오두막", "얼어붙은 호수", "침엽수림"]
    image_part = seen["input"][0]["content"][1]
    assert image_part["type"] == "input_image" and image_part["image_url"].startswith("data:image/png;base64,")
    assert imagegen.describe_image(client, "/없는/파일.png") == []


def test_same_place_keeps_description_and_people(game):
    game.set_scene("indoor", "한국 공관 영사과", "Inside a consular office with a counter and a Korean flag.",
                   ["민원 창구", "태극기"])
    game.scene_dirty = False
    first_desc = game.scene_desc
    assert game.add_character("김민수 영사", "영사과 담당 영사", "40대, 회색 양복, 안경")["look"] == "40대, 회색 양복, 안경"
    # 같은 곳을 다른 말로 다시 설정해도 묘사·그림·인물은 그대로
    assert call(game, "set_scene", setting="indoor", place="영사과 창구",
                description_en="A totally different modern lobby.", visible_features=["대기 번호표"])["장면이_바뀜"] is False
    assert game.scene_desc == first_desc and not game.scene_dirty and game.scene_place == "한국 공관 영사과"
    assert "대기 번호표" in game.scene_features                              # 새로 보이는 것은 덧붙인다
    person = game.add_character("박 영사", "영사과 담당 영사", "20대, 청바지")  # 같은 역할 → 같은 사람
    assert person["name"] == "김민수 영사" and len(game.characters) == 1
    text = gamemaster.build_input(game, "영사에게 묻는다")
    assert "[등장인물" in text and "김민수 영사" in text and "[지금 장면" in text

    assert call(game, "set_scene", setting="outdoor", place="공관 앞 거리",
                description_en="A city street.", visible_features=[])["장면이_바뀜"]    # 밖으로 나가면 바뀐다
    assert game.scene_dirty and game.characters == [] and not game.flags.get("at_embassy")


def test_night_does_not_change_the_scene(game):
    game.set_scene("outdoor", "강가", "A riverbank.", ["강"])
    game.scene_dirty = False
    game.begin_turn()
    game.pass_time(10, "rest")
    game.end_turn(0)
    assert not game.scene_dirty                                              # 낮밤이 바뀌어도 장면은 그대로


def load_app(monkeypatch):
    import importlib
    from unittest.mock import MagicMock
    fake = MagicMock()
    fake.update = lambda **k: k
    monkeypatch.setitem(sys.modules, "gradio", fake)
    sys.modules.pop("app", None)
    return importlib.import_module("app")


def test_image_update_modes(game, monkeypatch):
    app = load_app(monkeypatch)
    game.set_scene("outdoor", "강가", "A riverbank.", ["강"])
    assert app.image_update(game) == "new"                                   # 처음
    game.image_path, game.scene_dirty = "/tmp/a.png", False
    game.image_scene, game.image_night = app.scene_key(game), game.is_night
    game.image_weather = imagegen.weather_category(game.weather.get("code", 0))
    assert app.image_update(game) is None                                    # 그대로
    game.image_night = not game.is_night
    assert app.image_update(game) == "edit"                                  # 야외의 낮밤 변화 → 편집
    game.set_scene("indoor", "어부 오두막 안", "Inside a hut.", ["난로"])
    assert app.image_update(game) == "new"                                   # 장면이 바뀌면 새로
    game.scene_dirty, game.image_scene = False, app.scene_key(game)
    game.image_night = not game.is_night
    assert app.image_update(game) is None                                    # 실내는 낮밤으로 다시 그리지 않는다


def test_edit_keeps_composition(game):
    game.weather.update(code=63)
    game.start_hour, game.elapsed_hours = 6, 0
    prompt = imagegen.build_edit_prompt(game)
    assert "Keep the exact same camera angle" in prompt and "nothing new" in prompt
    assert "dawn" in prompt and "raining" in prompt
    calls = {}

    def fake_edit(**kw):
        calls.update(kw)
        import base64
        return SimpleNamespace(data=[SimpleNamespace(b64_json=base64.b64encode(b"png").decode())])

    client = SimpleNamespace(images=SimpleNamespace(edit=fake_edit))
    import tempfile
    prev = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    prev.write(b"old")
    prev.close()
    path = imagegen.edit_scene(client, game, prev.name)
    assert path and calls["prompt"] == imagegen.build_edit_prompt(game)
    assert imagegen.edit_scene(client, game, "/없는/파일.png") is None         # 실패하면 이전 그림 유지


def test_image_prompt_has_no_hangul_and_uses_local_language(game):
    game.place_name, game.place_name_en = "오스트레일리아, 노던 준주", "Australia, Northern Territory"
    game.country_code, game.country_en = "au", "Australia"
    game.set_scene("outdoor", "도로변 표지판 앞", "A red dirt road with a road sign, spinifex grass.",
                   ["도로 표지판", "붉은 흙길"])
    prompt = imagegen.build_prompt(game)
    assert not imagegen.HANGUL.search(prompt)
    assert "Australia, Northern Territory" in prompt and "written in English" in prompt and "Never use Korean" in prompt
    edit = imagegen.build_edit_prompt(game)
    assert not imagegen.HANGUL.search(edit) and "written in English" in edit

    game.country_code, game.country_en, game.place_name_en = "mn", "Mongolia", ""
    game.scene_desc = "A steppe with a 게르 and a sign."                   # GM이 실수로 한글을 섞어도
    prompt = imagegen.build_prompt(game)
    assert not imagegen.HANGUL.search(prompt) and "Mongolian (Cyrillic)" in prompt
    assert "latitude 46.9, longitude 103.8" in prompt                    # 영어 지명이 없으면 좌표로


def test_indoor_prompt_has_no_hangul(game):
    game.country_code, game.country_en = "th", "Thailand"
    game.set_scene("indoor", "한국 공관 영사과", "Inside a consular office: a counter and a Korean flag.", ["태극기"])
    prompt = imagegen.build_prompt(game)
    assert not imagegen.HANGUL.search(prompt) and "written in Thai" in prompt


def test_location_bar_separates_terrain_and_place(game):
    from survival.ui import render_location
    game.place_type = "마을"
    html = render_location(game)
    assert "지형: " in html and "장소: 마을" in html


def test_added_structures_detects_new_buildings():
    known = ["넓은 초원", "큰 나무", "큰 나무 아래"]
    assert imagegen.added_structures(known, ["큰 나무", "불 켜진 오두막", "초원"]) == ["불 켜진 오두막"]
    assert imagegen.added_structures(known, ["큰 나무", "별이 뜬 하늘", "풀밭"]) == []      # 구조물이 아니면 괜찮다
    assert imagegen.added_structures(["버려진 오두막"], ["오두막", "통나무 오두막"]) == []      # 원래 있던 것


def fake_image_client(descriptions, edits):
    import base64
    replies = iter(descriptions)

    def edit(**kw):
        edits.append(kw["prompt"])
        return SimpleNamespace(data=[SimpleNamespace(b64_json=base64.b64encode(b"png").decode())])

    return SimpleNamespace(images=SimpleNamespace(edit=edit),
                           responses=SimpleNamespace(create=lambda **k: SimpleNamespace(output_text=next(replies))))


def test_checked_edit_retries_then_discards(game, tmp_path):
    prev = tmp_path / "day.png"
    prev.write_bytes(b"day")
    game.set_scene("outdoor", "큰 나무 아래", "A large tree in the savanna.", ["큰 나무"])
    game.scene_seen = ["큰 나무", "초원"]

    edits = []                                      # 1차: 오두막이 생김 → 2차(엄격): 깨끗함 → 받아들임
    client = fake_image_client(["큰 나무, 불 켜진 오두막", "큰 나무, 밤하늘"], edits)
    path, seen = imagegen.checked_edit(client, game, str(prev))
    assert path and seen == ["큰 나무", "밤하늘"] and len(edits) == 2 and "STRICT" in edits[1]
    assert "The picture contains: A large tree in the savanna." in edits[0] and "house" not in edits[0]

    edits = []                                      # 두 번 다 생기면 편집본을 버린다
    client = fake_image_client(["큰 나무, 오두막", "큰 나무, 오두막"], edits)
    assert imagegen.checked_edit(client, game, str(prev)) == (None, None)


def test_draw_scene_keeps_old_image_or_shares_what_is_visible(game, monkeypatch):
    app = load_app(monkeypatch)
    game.set_scene("outdoor", "큰 나무 아래", "A large tree.", ["큰 나무"])
    game.image_path, game.scene_dirty = "/tmp/day.png", False
    game.image_scene, game.image_night = app.scene_key(game), not game.is_night       # 낮밤이 바뀐 상황
    game.image_weather = imagegen.weather_category(game.weather.get("code", 0))
    monkeypatch.setattr(app.savegame, "save", lambda s: None)

    monkeypatch.setattr(app.imagegen, "checked_edit", lambda c, s, p: (None, None))   # 건물이 생겨 버림
    app.draw_scene(game)
    assert game.image_path == "/tmp/day.png"                                         # 이전 그림 유지

    game.image_night = not game.is_night
    monkeypatch.setattr(app.imagegen, "checked_edit", lambda c, s, p: ("/tmp/night.png", ["큰 나무", "달"]))
    app.draw_scene(game)
    assert game.image_path == "/tmp/night.png" and "달" in game.scene_seen          # 보이는 것은 GM에게 전달
    assert "달" in gamemaster.build_input(game, "주변을 본다")


def test_night_wild_prompt_forbids_new_lights(game):
    game.place_type, game.start_hour, game.elapsed_hours = "야생", 21, 0
    game.set_scene("outdoor", "초원", "Open grassland.", ["풀"])
    prompt = imagegen.build_prompt(game)
    assert "moonlight and starlight" in prompt and "artificial" not in prompt


def test_wild_prompts_do_not_name_what_must_not_appear(game):
    game.place_type, game.start_hour, game.elapsed_hours = "야생", 22, 0
    game.set_scene("outdoor", "초원", "Open grassland with a lone acacia tree.", ["아카시아 나무"])
    for prompt in (imagegen.build_prompt(game), imagegen.build_edit_prompt(game)):
        low = prompt.lower()
        # 금지할 물건 이름(집·등불·창문·표지판)을 말하지 않는다: 말하면 이미지 모델이 그것을 그린다
        assert not any(w in low for w in ("house", "lantern", "lamp", "window", "cabin", "sign", "architecture",
                                          "artificial"))
        assert "moonlight and starlight" in prompt
    assert "Relight this exact picture" in imagegen.build_edit_prompt(game)


def test_edit_prompt_pins_down_what_is_in_the_picture(game, tmp_path):
    path = tmp_path / "scene.png"
    path.write_bytes(b"png")
    client = SimpleNamespace(responses=SimpleNamespace(create=lambda **k: SimpleNamespace(
        output_text="큰 바오밥나무 | large baobab tree, 붉은 흙 평원 | red dirt plain, 해 | sun")))
    assert imagegen.read_image(client, str(path)) == (["큰 바오밥나무", "붉은 흙 평원", "해"],
                                                      ["large baobab tree", "red dirt plain", "sun"])
    assert imagegen.describe_image(client, str(path)) == ["큰 바오밥나무", "붉은 흙 평원", "해"]
    game.place_type = "야생"
    game.set_scene("outdoor", "바오밥 아래", "A baobab tree on a plain.", ["바오밥나무"])
    game.scene_seen_en = ["large baobab tree", "red dirt plain"]
    assert "The picture contains: large baobab tree, red dirt plain." in imagegen.build_edit_prompt(game)
    game.place_type = "마을"                                             # 마을의 밤은 있던 불빛만 켜진다
    game.start_hour = 22
    edit = imagegen.build_edit_prompt(game)
    assert "Only lights that already exist" in edit and "written in" in edit
