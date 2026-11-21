"""상황에 맞는 배경 소리(사운드스케이프): 게임 상태 → 소리 층별 크기.

그림을 고를 때 쓰는 것과 같은 상태(지형, 날씨, 밤낮, 실내외, 장소, 장면에 보이는 것)로 소리를 정한다.
그래서 그림·서술·소리가 서로 어긋나지 않는다. 실제 소리는 브라우저가 Web Audio로 합성한다(ui.SOUND_JS).
여기서는 '무엇이 얼마나 크게 들려야 하는가'만 정한다 (각 층 0~1).
"""
from .weather import weather_category

LAYERS = ("wind", "rain", "thunder", "birds", "insects", "stream", "waves", "fire", "crowd", "traffic")

# 지형별 기본값 (야생, 날씨 영향 전)
BIOME_WIND = {"desert": 0.35, "snow": 0.5, "alpine": 0.5, "savanna": 0.25, "forest": 0.15, "jungle": 0.05}
BIOME_BIRDS = {"jungle": 0.6, "forest": 0.5, "savanna": 0.4, "alpine": 0.15, "desert": 0.05, "snow": 0.0}
BIOME_INSECTS = {"jungle": 0.7, "savanna": 0.5, "forest": 0.4, "desert": 0.2, "alpine": 0.1, "snow": 0.0}

# 장면에 보이는 것 → 소리 (GM이 밝힌 것, 그림에서 읽어 낸 것, 장면 이름)
STREAM_WORDS = ("강", "개울", "시냇물", "냇물", "계곡", "폭포", "물줄기", "river", "stream", "creek", "waterfall")
WAVE_WORDS = ("바다", "해변", "해안", "바닷가", "파도", "항구", "부두", "sea", "ocean", "beach", "coast", "waves",
              "harbor", "harbour")
FIRE_WORDS = ("모닥불", "불씨", "화덕", "난로", "벽난로", "캠프파이어", "장작불", "campfire", "fireplace", "bonfire",
              "stove")
# '강'이 '강아지·강도·강풍'에, '바다'가 '바닥'에 걸리지 않게 그대로 쓰이지 않는 말
NOT_STREAM = ("강아지", "강도", "강풍", "강한", "강하게", "강력", "강제")


def _clamp(value):
    return round(max(0.0, min(1.0, value)), 2)


def scene_text(state):
    """지금 장면을 이루는 말들 (소리 판정용)."""
    words = [state.scene_place] + list(state.scene_features) + list(state.scene_seen) + list(state.scene_seen_en)
    return " ".join(str(w) for w in words if w).lower()


def _has(text, words, exclude=()):
    for blocked in exclude:
        text = text.replace(blocked, " ")
    return any(w.lower() in text for w in words)


def soundscape(state):
    """지금 들려야 할 배경 소리. {"layers": {층: 0~1}, "indoor": bool, "key": 변화 감지용 문자열}"""
    silent = {"layers": {name: 0.0 for name in LAYERS}, "indoor": False, "key": "silent"}
    if state is None or state.status != "playing":
        return silent

    weather = state.weather or {}
    category = weather_category(weather.get("code", 0))
    wind_speed = float(weather.get("wind_speed") or 0)
    precipitation = float(weather.get("precipitation") or 0)
    temperature = float(weather.get("temperature") if weather.get("temperature") is not None else 15)
    night = state.is_night
    indoor = state.indoor
    wild = state.place_type == "야생"
    town = state.place_type == "마을"
    city = state.place_type == "도시"
    scene = scene_text(state)

    layers = {}
    # 바람: 지형 기본값 + 실제 풍속. 눈보라·폭풍이면 더 세다
    base_wind = BIOME_WIND.get(state.biome, 0.15) if wild else 0.08
    layers["wind"] = base_wind + wind_speed / 60 + {"snow": 0.2, "storm": 0.3}.get(category, 0)

    # 비: 실제 강수량(mm/h)에 비례
    layers["rain"] = (0.3 + precipitation / 8) if category in ("rain", "storm") else 0.0
    layers["thunder"] = 0.8 if category == "storm" else 0.0

    # 새(낮)와 벌레(밤). 비가 오면 줄고, 추우면 벌레가 없다
    birds = BIOME_BIRDS.get(state.biome, 0.3) if wild else (0.25 if town else 0.1)
    layers["birds"] = 0.0 if night else birds * (0.3 if category in ("rain", "storm", "snow") else 1.0)
    insects = BIOME_INSECTS.get(state.biome, 0.3) if wild else (0.2 if town else 0.05)
    if not night:
        insects = insects * 0.4 if state.biome == "jungle" and wild else 0.0   # 낮에는 정글의 매미 소리만
    if temperature < 8 or category in ("snow", "storm"):
        insects = 0.0
    layers["insects"] = insects

    # 장면에 보이는 물과 불
    layers["stream"] = 0.5 if _has(scene, STREAM_WORDS, NOT_STREAM) else 0.0
    layers["waves"] = 0.6 if _has(scene, WAVE_WORDS) else 0.0
    layers["fire"] = 0.6 if _has(scene, FIRE_WORDS) else 0.0

    # 사람과 차: 마을·도시, 도로 위, 공항
    crowd = 0.5 if city else 0.25 if town else 0.0
    traffic = 0.5 if city else 0.12 if town else (0.3 if state.flags.get("on_road") else 0.0)
    if state.flags.get("at_airport"):
        crowd, traffic = max(crowd, 0.5), max(traffic, 0.3)
    if night:
        crowd, traffic = crowd * 0.4, traffic * 0.5
    layers["crowd"], layers["traffic"] = crowd, traffic

    # 실내: 바깥 소리는 줄고(지붕 위 빗소리는 남는다), 안의 불 소리는 그대로
    if indoor:
        for name in ("wind", "birds", "insects", "stream", "waves", "traffic"):
            layers[name] *= 0.3
        layers["rain"] *= 0.5
        if not state.flags.get("at_airport"):
            layers["crowd"] *= 0.4

    layers = {name: _clamp(layers.get(name, 0.0)) for name in LAYERS}
    key = "|".join(f"{name}:{layers[name]}" for name in LAYERS) + f"|in:{int(indoor)}"
    return {"layers": layers, "indoor": indoor, "key": key}


# ---------- 사건 효과음 ----------
# 이번 턴에 일어난 중요한 일 → 짧은 효과음. 중요 알림(gamemaster.collect_notices)과 같은 기록(turn_flags)을 본다.
SFX = ("win", "death", "arrest", "success", "fail", "danger", "offer", "discover", "clue", "lucky", "engine",
       "ticket", "travel", "dismiss")
MAX_SFX = 3   # 한 턴에 많아도 세 개까지 (중요한 것부터)


def turn_sfx(state):
    """이번 턴의 효과음. {"events": [이름...], "nonce": 턴마다 다른 값}

    같은 턴의 화면이 여러 번 갱신되어도(진행 중 표시, 그림 갱신) nonce가 같으니 브라우저는 한 번만 울린다.
    """
    if state is None:
        return {"events": [], "nonce": ""}
    nonce = f"{state.turn}:{state.elapsed_hours:g}:{state.lat:.4f}:{state.lon:.4f}:{state.status}"
    if state.status == "won":
        return {"events": ["win"], "nonce": nonce}
    if state.status == "dead":
        return {"events": ["death"], "nonce": nonce}

    flags = state.turn_flags or {}
    events = []
    if flags.get("arrested"):
        events.append("arrest")
    result = flags.get("offer_result")
    if result:
        events.append("fail" if result.get("bad") else "success")
    attempt = flags.get("attempt")
    if attempt:
        events.append("success" if attempt.get("success") else "fail")
    found = flags.get("lead_result")
    if found:
        events.append("danger" if found.get("danger") else "discover")
    event = state.event or {}
    if event.get("kind") == "danger" and not found:
        events.append("danger")
    if state.offer and state.offer.get("turn") == state.turn:
        events.append("offer")
    if flags.get("new_lead") and not found:
        events.append("clue")
    if event.get("kind") == "lucky":
        events.append("lucky")
    if flags.get("vehicle") and state.vehicle:
        events.append("engine")
    if flags.get("ticket"):
        events.append("ticket")
    if flags.get("moved"):
        events.append("travel")
    if flags.get("offer_declined") or flags.get("offer_expired") or \
            (flags.get("pre_offer") or {}).get("kind") == "redo":
        events.append("dismiss")
    return {"events": list(dict.fromkeys(events))[:MAX_SFX], "nonce": nonce}
