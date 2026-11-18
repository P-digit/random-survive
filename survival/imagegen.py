"""현재 장면 이미지 생성 (멀티모달 파트, Images API)."""
import base64
import time

from .config import IMAGE_MODEL, LLM_MODEL, OUTPUT_DIR
import re

from .events import BIOMES
from .languages import sign_rule
from .weather import weather_category

# 날씨 분류별로 그림에 반드시 보여야 하는 요소
WEATHER_VISUALS = {
    "rain":  "It is raining: clearly visible streaks of falling rain across the whole frame, "
             "dark grey rain clouds, wet glistening ground with puddles and splashes.",
    "storm": "A violent thunderstorm: towering black storm clouds, a bright lightning bolt in the sky, "
             "heavy sheets of rain blown sideways by the wind, drenched ground.",
    "snow":  "It is snowing: many visible snowflakes falling across the whole frame, "
             "ground and objects covered in fresh white snow, pale overcast sky.",
    "fog":   "Thick fog: distant scenery fades into grey mist, low visibility, damp air.",
    "clear": "",
}

PLACE_EN = {"야생": "untouched wilderness",
            "마을": "at the edge of a small rural village, simple local houses nearby",
            "도시": "on a street of a busy local city, shops and buildings nearby"}


HANGUL = re.compile("[\u1100-\u11FF\u3130-\u318F\uAC00-\uD7A3]+")


def no_hangul(text):
    """그림 지시문에서 한글을 지운다. 한글이 있으면 이미지 모델이 표지판에 엉터리 한글을 그린다."""
    text = HANGUL.sub("", text or "")
    text = re.sub(r"\(\s*\)|\[\s*\]", "", text)
    return re.sub(r"[ \t]{2,}", " ", text).strip()


def region_of(state):
    """그림 지시문에 쓰는 지역 이름(영어). 영어 지명이 없으면 좌표와 나라만."""
    name = no_hangul(state.place_name_en) or no_hangul(state.country_en)
    coords = f"latitude {state.lat}, longitude {state.lon}"
    return f"{name} ({coords})" if name else coords


def build_prompt(state):
    return no_hangul(_build_prompt(state))


def _build_prompt(state):
    w = state.weather
    time_of_day = light_of(state)
    category = weather_category(w.get("code", 0))
    visuals = WEATHER_VISUALS[category]
    if w["wind_speed"] >= 40:
        visuals += " Strong wind: vegetation bending hard, dust, sand or snow blowing through the air."
    weather_line = (f"IMPORTANT, the weather must be clearly noticeable. {visuals} " if visuals else "")
    no_list = ("The frame contains only the place itself: no hands, no arms, no held objects, "
               "no weapons, no guns, no people, no characters, no game HUD, no captions, no watermark.")
    region = region_of(state)
    signs = sign_rule(state.country_code, state.country_en)
    climate = state.climate or {}
    climate_line = (f"Climate: {climate['label_en']}. Season: {climate['season_en']}. "
                    "Ground, vegetation and colors must match this climate and season exactly. "
                    if climate else "")
    # 그림에는 GM이 밝힌 것만 그린다 → 그림에만 있고 게임에는 없는 건물이 생기지 않게 한다.
    # (보이는 것 목록은 한국어라 넣지 않는다. GM의 영어 묘사(scene_desc)에 모두 들어 있다)
    if state.place_type == "야생" and not state.indoor:
        only_line = ("Do NOT draw any building, hut, house, road, vehicle, fence or other man-made structure "
                     "unless it is described above. ")
    else:
        only_line = "Do not add prominent landmarks or vehicles that are not described above. "

    if state.indoor:
        # 실내 장면: GM이 묘사한 공간을 그리고, 날씨는 창문·문틈 너머로 보이게 한다
        inside = state.scene_desc or f"the inside of a simple local building ({state.scene_place})"
        outside = WEATHER_VISUALS[category].split(":")[0] if visuals else w["description_en"]
        return (
            "An atmospheric interior illustration, eye-level view from inside the room. "
            f"Interior: {inside} {only_line}"
            f"The building is in {region}; {climate_line}"
            "furniture, materials and architecture authentic to that region. "
            f"Through the window or doorway: {outside}, {w['temperature']:.0f} degrees Celsius outside, {time_of_day}. "
            "Dim natural light, highly detailed. " + signs + no_list
        )

    focus = f"Scene: {state.scene_desc} " if state.scene_desc else ""
    return (
        "A wide scenic illustration, like a travel documentary establishing shot. "
        f"Location: {region}. {focus}{only_line}"
        f"Surroundings: {BIOMES[state.biome][1]}, {PLACE_EN[state.place_type]}. {climate_line}"
        f"Weather: {w['description_en']}, {w['temperature']:.0f} degrees Celsius, {time_of_day}. "
        + weather_line
        + "Eye-level view, moody atmospheric lighting, highly detailed, "
        "architecture authentic to the region. " + signs + no_list
    )


def describe_image(client, path):
    """생성된 이미지를 Vision(이미지 → 텍스트)으로 읽어, 실제로 그려진 주요 대상을 목록으로 돌려준다.

    이미지 모델이 지시하지 않은 건물 등을 그려 넣는 경우가 있다. 그림에 보이는 것을 게임 마스터에게
    알려 주면 "그림에는 있는데 게임에는 없는" 상황을 막을 수 있다. 실패하면 빈 목록.
    """
    try:
        with open(path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode()
        response = client.responses.create(
            model=LLM_MODEL,
            max_output_tokens=150,
            input=[{"role": "user", "content": [
                {"type": "input_text",
                 "text": "이 그림에서 눈에 띄는 건물, 구조물, 탈것, 지형지물(강, 호수, 바위산, 숲 등)을 "
                         "한국어 명사구로 최대 6개, 쉼표로만 구분해 나열해. 설명이나 문장은 쓰지 마. "
                         "예: 통나무 오두막, 얼어붙은 호수, 침엽수림"},
                {"type": "input_image", "image_url": f"data:image/png;base64,{encoded}", "detail": "low"},
            ]}],
        )
        things = [s.strip(" .\n-") for s in (response.output_text or "").replace("\n", ",").split(",")]
        return [s[:30] for s in things if s][:6]
    except Exception as e:
        print(f"[이미지] 그림 읽기 실패: {e}")
        return []


def light_of(state):
    """시각에 따른 빛. 새벽·낮·해 질 녘·밤."""
    h = state.hour
    if 5 <= h < 7:
        return "at dawn, soft pale light, the sky turning orange at the horizon"
    if 7 <= h < 17:
        return "in daylight"
    if 17 <= h < 20:
        return "at dusk, warm low sunlight and long shadows"
    return "at night, dark sky, only faint natural or artificial light"


def build_edit_prompt(state):
    """같은 장면에서 시간·날씨만 바뀌었을 때, 이전 그림을 고치는 지시문."""
    w = state.weather
    category = weather_category(w.get("code", 0))
    visuals = WEATHER_VISUALS[category] or "Clear weather, no rain or snow."
    if state.indoor:
        change = (f"Change only the light coming through the windows to match: {light_of(state)}; "
                  f"outside the windows: {visuals}")
    else:
        change = f"Change only the lighting and sky to: {light_of(state)}. Weather: {visuals}"
    return no_hangul("Edit this image. It is the same place a few hours later. Keep the exact same camera angle, "
                     "composition, landscape, buildings, room layout, furniture, objects, signs and every person "
                     "exactly as they are; do not add, remove or replace anything. " + change + " "
                     + sign_rule(state.country_code, state.country_en) + "No captions, no watermark.")


def _save(b64):
    image_bytes = base64.b64decode(b64)   # Base64 → 이미지
    OUTPUT_DIR.mkdir(exist_ok=True)
    path = OUTPUT_DIR / f"scene_{int(time.time() * 1000)}.png"
    with open(path, "wb") as f:
        f.write(image_bytes)
    return str(path)


def edit_scene(client, state, previous_path):
    """같은 장면을 유지한 채 빛·날씨만 바꾼 그림을 만든다 (Images API edit). 실패하면 None."""
    try:
        with open(previous_path, "rb") as image:
            result = client.images.edit(
                model=IMAGE_MODEL,
                image=image,
                prompt=build_edit_prompt(state),
                size="1536x1024",
                quality="low",
            )
        return _save(result.data[0].b64_json)
    except Exception as e:
        print(f"[이미지] 편집 실패, 새로 그리지 않고 이전 그림을 유지합니다: {e}")
        return None


def generate_scene(client, state):
    """장면 이미지를 생성해 파일로 저장하고 경로를 반환한다. 실패하면 None."""
    try:
        result = client.images.generate(
            model=IMAGE_MODEL,
            prompt=build_prompt(state),
            size="1536x1024",
            quality="low",   # 비용 절약
        )
        return _save(result.data[0].b64_json)
    except Exception as e:
        print(f"[이미지] 생성 실패: {e}")
        return None
