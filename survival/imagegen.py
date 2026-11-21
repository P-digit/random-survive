"""현재 장면 이미지 생성 (멀티모달 파트, Images API. Gemini는 llm.GeminiImages가 같은 모양으로 그린다)."""
import base64
import time

from .config import IMAGE_MODEL, LLM_MODEL, OUTPUT_DIR
from .llm import image_mime
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
    wild = is_wild(state)
    if wild:
        only_line = ("Everything else in the frame is untouched nature with no trace of people: only land, "
                     "plants, rocks, water and sky. ")
        if state.is_night or state.hour >= 17 or state.hour < 7:
            only_line += "The only light comes from the sky itself (sun, moon, stars). "
    else:
        only_line = "Do not add prominent landmarks or vehicles that are not described above. "
    signs = signs if has_text_surfaces(state) else ""

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
        + ("vegetation and landforms authentic to the region. " if wild else "architecture authentic to the region. ")
        + signs + no_list
    )


def describe_image(client, path):
    """그림에 보이는 것을 한국어 목록으로. (read_image의 한국어 쪽)"""
    return read_image(client, path)[0]


def read_image(client, path):
    """생성된 이미지를 Vision(이미지 → 텍스트)으로 읽어, 실제로 그려진 주요 대상을 목록으로 돌려준다.

    이미지 모델이 지시하지 않은 건물 등을 그려 넣는 경우가 있다. 그림에 보이는 것을 게임 마스터에게
    알려 주면 "그림에는 있는데 게임에는 없는" 상황을 막을 수 있다. 실패하면 빈 목록.
    """
    try:
        with open(path, "rb") as f:
            data = f.read()
        encoded = base64.b64encode(data).decode()
        response = client.responses.create(
            model=LLM_MODEL,
            max_output_tokens=150,
            input=[{"role": "user", "content": [
                {"type": "input_text",
                 "text": "이 그림에서 눈에 띄는 건물, 구조물, 탈것, 지형지물(강, 호수, 바위산, 숲 등)과 하늘의 "
                         "광원(해, 달)을 최대 6개, 쉼표로만 구분해 나열해. 각 항목은 '한국어 명사구 | English noun "
                         "phrase' 형식. 설명이나 문장은 쓰지 마. "
                         "예: 통나무 오두막 | log cabin, 얼어붙은 호수 | frozen lake, 침엽수림 | conifer forest"},
                {"type": "input_image", "image_url": f"data:{image_mime(data)};base64,{encoded}", "detail": "low"},
            ]}],
        )
        things = [s.strip(" .\n-") for s in (response.output_text or "").replace("\n", ",").split(",")]
        ko, en = [], []
        for thing in [s for s in things if s][:6]:
            left, _, right = thing.partition("|")
            if left.strip(" .-"):
                ko.append(left.strip(" .-")[:30])
                if right.strip(" .-"):
                    en.append(right.strip(" .-")[:40])
        return ko, en
    except Exception as e:
        print(f"[이미지] 그림 읽기 실패: {e}")
        return [], []


def is_wild(state):
    return state.place_type == "야생" and not state.indoor


TEXT_SURFACES = re.compile(r"\b(signs?|signboards?|billboards?|posters?|shops?|stores?|stalls?|buildings?|houses?|"
                           r"huts?|cabins?|roads?|streets?|labels?|stations?|markets?|villages?|towns?)\b", re.I)


def has_text_surfaces(state):
    """그림에 글자가 들어갈 만한 것(표지판·가게·건물·길)이 있는가. 없으면 글자 규칙을 넣지 않는다.

    (표지판·가게 이름 이야기를 하면 이미지 모델이 아무것도 없는 들판에 표지판을 세운다)
    """
    if not is_wild(state):
        return True
    known = " ".join(list(state.scene_features) + list(state.scene_seen))
    return bool(TEXT_SURFACES.search(state.scene_desc or "")) or any(w in known for w in STRUCTURE_WORDS)


def light_of(state):
    """시각에 따른 빛. 새벽·낮·해 질 녘·밤. 야생의 밤은 달빛·별빛만 (불빛을 말하면 집·등불을 그려 넣는다)."""
    h = state.hour
    if not (5 <= h < 20) and is_wild(state):
        return "at night, lit only by moonlight and starlight, deep blue tones, the land in soft silhouette"
    if 5 <= h < 7:
        return "at dawn, soft pale light, the sky turning orange at the horizon"
    if 7 <= h < 17:
        return "in daylight"
    if 17 <= h < 20:
        return "at dusk, warm low sunlight and long shadows"
    return "at night, dark sky, only faint natural or artificial light"


# Vision이 읽어 낸 대상 중 '사람이 만든 구조물'로 보는 말. 장면에 없던 것이 그림에 생겼는지 확인할 때 쓴다
STRUCTURE_WORDS = ("집", "주택", "건물", "오두막", "통나무", "헛간", "농가", "창고", "천막", "텐트", "움막", "막사", "캐빈",
                   "마을", "가로등", "전봇대", "전신주", "송전탑", "철탑", "탑", "다리", "울타리", "담장", "도로", "포장",
                   "차", "트럭", "자동차", "교회", "사원", "성당", "모스크", "공장", "가게", "상점", "정자", "컨테이너",
                   "창문", "불빛", "등불", "램프", "조명", "간판", "표지판", "벽", "지붕", "굴뚝")
def inventory_en(state):
    """그림에 들어 있는 것(영어). Vision이 읽어 낸 목록이 있으면 그것, 없으면 GM의 영어 묘사."""
    things = [no_hangul(s) for s in state.scene_seen_en if no_hangul(s)]
    if things:
        return ", ".join(things[:8])
    return no_hangul(state.scene_desc) or BIOMES[state.biome][1]


def _similar(a, b):
    """같은 대상을 가리키는지: 한쪽이 다른 쪽을 포함하거나, 두 글자 이상 낱말을 함께 쓴다('버려진 오두막' ≈ '통나무 오두막')."""
    flat_a, flat_b = a.replace(" ", ""), b.replace(" ", "")
    if flat_a in flat_b or flat_b in flat_a:
        return True
    return bool({w for w in a.split() if len(w) >= 2} & {w for w in b.split() if len(w) >= 2})


def added_structures(known, seen):
    """그림에서 읽어 낸 것(seen) 중, 장면에 원래 있던 것(known)과 겹치지 않는 사람이 만든 구조물."""
    known = [k for k in known if k]
    added = []
    for item in seen:
        if not any(w in item for w in STRUCTURE_WORDS):
            continue
        if any(_similar(item, k) or _similar(k, item) for k in known):
            continue
        added.append(item)
    return added


def build_edit_prompt(state, strict=False):
    """같은 장면에서 시간·날씨만 바뀌었을 때, 이전 그림을 고치는 지시문.

    이미지 모델은 '몇 시간 뒤의 같은 장소'라고 하면 장면을 새로 상상해 그리고, '건물·등불을 넣지 마라'처럼
    금지할 낱말을 나열하면 오히려 그 낱말을 그린다. 그래서 (1) 사진 보정 작업으로 틀을 잡고, (2) 그림에 들어
    있는 것을 긍정형 목록으로 못 박고, (3) 빛의 출처를 정해 준다.
    """
    w = state.weather
    category = weather_category(w.get("code", 0))
    visuals = WEATHER_VISUALS[category] or "Clear weather, no rain or snow."
    if state.indoor:
        change = (f"Change only the light coming through the windows to match: {light_of(state)}; "
                  f"outside the windows: {visuals}")
    else:
        change = f"New lighting and sky: {light_of(state)}. Weather: {visuals}"
    if is_wild(state):
        source = "This is uninhabited wilderness: every light in the result comes from the sky. "
    else:
        source = "Only lights that already exist in the picture may glow. "
    strict_line = ("STRICT: the previous attempt drew new objects. Treat the picture as a fixed photograph; change "
                   "only brightness, color and the sky, every outline stays identical. " if strict else "")
    signs = sign_rule(state.country_code, state.country_en) if has_text_surfaces(state) else ""
    return no_hangul(
        "Relight this exact picture. This is a photo-editing job, like color grading: adjust only the global "
        "light, shadows, sky and weather effects on top of the existing image. Keep the exact same camera angle, "
        "composition, horizon and every shape, object and person exactly where they are. "
        f"The picture contains: {inventory_en(state)}. The result contains exactly these things and nothing new. "
        + source + strict_line + change + " " + signs + "No captions, no watermark.")


EXTENSIONS = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}


def _save(b64):
    image_bytes = base64.b64decode(b64)   # Base64 → 이미지
    OUTPUT_DIR.mkdir(exist_ok=True)
    # 공급자마다 형식이 다르다(OpenAI PNG, Gemini JPEG). 확장자를 실제 형식에 맞춘다
    path = OUTPUT_DIR / f"scene_{int(time.time() * 1000)}.{EXTENSIONS[image_mime(image_bytes)]}"
    with open(path, "wb") as f:
        f.write(image_bytes)
    return str(path)


def known_things(state):
    """지금 장면에 원래 있는 것들 (GM이 밝힌 것 + 이전 그림에서 읽어 낸 것 + 장면 이름)."""
    return list(state.scene_features) + list(state.scene_seen) + [state.scene_place]


def checked_edit(client, state, previous_path):
    """빛·날씨만 바꾼 그림을 만들고, 장면에 없던 건물·구조물이 생기지 않았는지 Vision으로 확인한다.

    생겼으면 더 엄격하게 한 번 더 고치고, 그래도 생기면 편집본을 버린다(이전 그림 유지).
    반환: (그림 경로, 그 그림에서 읽어 낸 것들) 또는 (None, None)
    """
    known = known_things(state)
    for strict in (False, True):
        path = edit_scene(client, state, previous_path, strict=strict)
        if not path:
            return None, None
        seen, seen_en = read_image(client, path)
        extra = added_structures(known, seen)
        if not extra:
            if seen_en:
                state.scene_seen_en = seen_en
            return path, seen
        print(f"[이미지] 편집이 장면에 없던 것을 그렸습니다({', '.join(extra)}). "
              + ("더 엄격하게 다시 고칩니다." if not strict else "편집본을 버리고 이전 그림을 유지합니다."))
    return None, None


def edit_scene(client, state, previous_path, strict=False):
    """같은 장면을 유지한 채 빛·날씨만 바꾼 그림을 만든다 (Images API edit). 실패하면 None."""
    try:
        with open(previous_path, "rb") as image:
            result = client.images.edit(
                model=IMAGE_MODEL,
                image=image,
                prompt=build_edit_prompt(state, strict=strict),
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
