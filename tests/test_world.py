"""세계: 거리·날씨·기후·지형·이벤트 조건·위험도 모델·생존 지식 검색·도시 데이터 테스트."""
import datetime
import math
import random
from types import SimpleNamespace

import pytest

from survival import climate, events as events_module, geo, knowledge, places
from survival.events import classify_biome, roll_event, roll_major_event
from survival.risk_model import predict_risk, train
from tests.helpers import call, fake_weather


def test_distance_and_movement():
    assert geo.distance_to_korea(*geo.SEOUL) == pytest.approx(0, abs=1e-6)
    assert geo.haversine_km(37.5665, 126.978, 35.6762, 139.6503) == pytest.approx(1150, rel=0.03)  # 서울-도쿄
    before = geo.distance_to_korea(46.9, 103.8)
    lat, lon = geo.move_toward_korea(46.9, 103.8, 500)
    assert geo.distance_to_korea(lat, lon) == pytest.approx(before - 500, abs=2)
    assert geo.move_toward_korea(37.0, 127.0, 9999) == geo.SEOUL


def test_weather_follows_game_clock(game):
    game.set_weather(fake_weather(25, hourly=[{"temperature": 25.0, "feels_like": 25.0},
                                              {"temperature": 20.0, "feels_like": 19.0},
                                              {"temperature": 4.0, "feels_like": 1.0}]))
    game.pass_time(2, "rest")
    assert game.weather["temperature"] == 4.0 and "hourly" not in game.weather
    game.pass_time(5, "rest")
    assert game.weather["temperature"] == 4.0   # 예보 끝을 넘어가면 마지막 값 유지


def test_risk_model_learns_and_orders_situations():
    _, accuracy = train(save=False)
    assert accuracy > 0.75
    safe = predict_risk(fake_weather(20), 100, 90, 90, 90, is_night=False, in_wild=False)
    deadly = predict_risk(fake_weather(-25, wind_speed=50, precipitation=5), 30, 10, 10, 10,
                          is_night=True, in_wild=True)
    assert safe["level"] == 0 and deadly["level"] == 2
    assert sum(deadly["probs"]) == pytest.approx(1.0)


def test_biome_and_events():
    assert classify_biome(70, fake_weather(-20)) == "snow"
    assert classify_biome(23, fake_weather(38, humidity=12)) == "desert"
    assert classify_biome(-3, fake_weather(27, humidity=88)) == "jungle"
    rng = random.Random(0)
    kinds = [e["kind"] for e in (roll_event("desert", "야생", 2, rng) for _ in range(300)) if e]
    assert kinds.count("danger") > len(kinds) / 2      # 위험 등급이 높으면 위험 이벤트가 많다


def test_keyword_search_finds_relevant_chunk():
    docs = knowledge.search(None, "뱀에 물렸을 때 어떻게 해야 해?")
    assert any("뱀" in d for d in docs)


def test_numpy_vector_search_without_chromadb(monkeypatch, tmp_path):
    """가짜 임베딩(글자 포함 여부)으로 numpy 벡터 검색 경로를 검증한다."""
    keys = ["뱀", "여권", "물", "불", "눈"]

    def fake_embed(client, texts):
        return [[float(k in t) + 0.01 for k in keys] for t in texts]

    monkeypatch.setattr(knowledge, "embed", fake_embed)
    monkeypatch.setattr(knowledge, "embed_cache_path", lambda: tmp_path / "e.json")
    monkeypatch.setattr(knowledge, "_matrix", None)
    docs = knowledge.numpy_search(object(), "여권", n_results=2)
    assert "여권" in docs[0] and (tmp_path / "e.json").exists()


def test_events_fit_the_scene(game):
    rng = random.Random(3)
    for _ in range(50):                     # 실내에서는 지나가는 차량·헬기·보급 상자가 나오지 않는다
        offer = roll_major_event("도시", False, indoor=True, rng=rng)
        assert offer["id"] in ("korean", "news", "embassy")
    assert roll_major_event("야생", True, indoor=True, rng=rng) is None

    game.set_scene("indoor", "동굴 안", "Inside a dark cave.")
    game.turn = 20                          # 기회가 나올 차례여도, 맞는 것이 없으면 나오지 않는다
    game.begin_turn()
    assert game.offer is None
    from survival.events import EVENTS
    indoor_texts = {e["text"] for e in EVENTS if e.get("indoor")}
    assert game.event is None or game.event["text"] in indoor_texts   # 실내에서는 실내 이벤트만

    game.set_scene("outdoor", "", "")
    game.begin_turn()
    assert game.offer is not None           # 밖으로 나오면 밀린 기회가 찾아온다
    call(game, "reject_event", reason="상황에 맞지 않음")
    assert game.offer is None and game.event is None


def test_climate_zones_from_yearly_records():
    zone = climate.classify_zone
    assert zone([14, 16, 20, 25, 30, 34, 36, 35, 31, 26, 20, 15], [2] * 12) == "desert"              # 사하라
    assert zone([26, 26, 27, 27, 27, 26, 26, 27, 27, 27, 27, 26], [250] * 12) == "rainforest"       # 아마존
    assert zone([25, 27, 29, 30, 29, 27, 26, 26, 26, 27, 26, 25], [0, 0, 5, 30, 120, 180, 250, 260, 200, 90, 10, 0]) == "savanna"
    assert zone([-2, 0, 5, 12, 18, 22, 25, 26, 21, 14, 7, 0], [20, 25, 45, 80, 100, 130, 390, 350, 140, 50, 50, 25]) == "temperate"  # 서울
    assert zone([-40, -35, -22, -7, 6, 15, 19, 15, 6, -8, -28, -38], [10, 8, 7, 10, 20, 35, 40, 38, 30, 20, 15, 12]) == "continental"  # 야쿠츠크
    assert zone([-28, -28, -26, -18, -7, 1, 5, 4, -1, -9, -18, -24], [5] * 12) == "polar"
    assert zone([5] * 12, [50] * 12, elevation=3800) == "alpine"
    assert climate.current_season(37, 1, "temperate") == "겨울"
    assert climate.current_season(-34, 1, "temperate") == "여름"          # 남반구는 반대
    assert climate.current_season(5, 8, "savanna", [0, 0, 5, 30, 120, 180, 250, 260, 200, 90, 10, 0]) == "우기"


def test_climate_api_parsing_and_fallback(monkeypatch):
    days = [datetime.date(2025, 11, 7) + datetime.timedelta(days=i) for i in range(365)]

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"daily": {"time": [d.isoformat() for d in days],
                              "temperature_2m_mean": [30.0 if 5 <= d.month <= 9 else 16.0 for d in days],
                              "precipitation_sum": [0.05] * 365}}

    monkeypatch.setattr(climate.requests, "get", lambda *a, **k: FakeResponse())
    result = climate.get_climate(23.4, 11.2, fake_weather(20), today=datetime.date(2026, 11, 17))
    assert result["zone"] == "desert" and result["biome"] == "desert" and result["source"] == "기록"
    assert result["season"] == "가을" and result["t_warm"] == 30 and result["p_ann"] == 18
    assert "사막 기후" in climate.describe(result)

    def broken(*a, **k):
        raise OSError("network down")
    monkeypatch.setattr(climate.requests, "get", broken)
    guess = climate.get_climate(23.4, 11.2, fake_weather(38, humidity=10))
    assert guess["zone"] == "desert" and guess["source"] == "추정"


def test_biome_follows_climate_not_todays_weather():
    desert = climate.make_climate("desert", 23, 1)
    assert classify_biome(23, fake_weather(6, humidity=70), desert) == "desert"      # 사막의 추운 밤도 사막
    taiga = climate.make_climate("continental", 62, 1)
    assert classify_biome(62, fake_weather(-25), taiga) == "snow"                    # 냉대의 한겨울은 설원
    assert classify_biome(62, fake_weather(18), taiga) == "forest"


def ctx(**kw):
    base = {"night": False, "indoor": False, "weather": "clear", "temp": 15, "season": "여름"}
    base.update(kw)
    return base


def test_events_follow_place_time_weather():
    texts = lambda *a, **k: {e["text"] for e in events_module.candidates(*a, **k)}  # noqa: E731
    wild_night = texts("야생", "savanna", ctx(night=True))
    assert any("사자" in s for s in wild_night) and not any("코끼리" in s for s in wild_night)
    assert not any("경찰" in s or "소매치기" in s for s in wild_night)          # 야생에는 사람 이벤트 없음
    city = texts("도시", "desert", ctx())
    assert any("소매치기" in s for s in city) and not any("전갈" in s or "사자" in s for s in city)
    assert not texts("도시", "desert", ctx(night=True)) & {s for s in city if "소매치기" in s}
    assert any("와디" in s for s in texts("야생", "desert", ctx(weather="rain")))
    assert not any("와디" in s for s in texts("야생", "desert", ctx(weather="clear")))
    assert any("밤과 도토리" in s for s in texts("야생", "forest", ctx(season="가을")))
    assert not any("밤과 도토리" in s for s in texts("야생", "forest", ctx(season="봄")))
    assert any("열사병" in s for s in texts("야생", "desert", ctx(temp=40)))
    assert not any("열사병" in s for s in texts("야생", "desert", ctx(temp=20)))
    cave = texts("야생", "snow", ctx(indoor=True, weather="snow"))
    assert any("지붕" in s for s in cave) and not any("늑대" in s for s in cave)
    for place in ("야생", "마을", "도시"):
        for biome in ("snow", "alpine", "desert", "jungle", "savanna", "forest"):
            for night in (False, True):
                for indoor in (False, True):
                    assert len(events_module.candidates(place, biome, ctx(night=night, indoor=indoor))) >= 3


def test_roll_event_uses_context():
    rng = random.Random(2)
    seen = [events_module.roll_event("jungle", "야생", 2, rng, ctx(night=True, weather="rain"))
            for _ in range(200)]
    texts = {e["text"] for e in seen if e}
    assert texts and all(events_module.matches(next(x for x in events_module.EVENTS if x["text"] == s),
                                                "야생", "jungle", ctx(night=True, weather="rain")) for s in texts)


def test_temperature_follows_time_of_day(game):
    game.start_hour, game.start_offset, game.utc_offset, game.elapsed_hours = 12, 0, 0, 0
    profile = [{"hour": (12 + i) % 24, "temperature": 20 + 10 * math.cos(2 * math.pi * ((12 + i) % 24 - 15) / 24),
                "feels_like": 20.0} for i in range(30)]
    game.set_weather(fake_weather(22, hourly=profile, utc_offset=0))
    noon = game.weather["temperature"]
    game.pass_time(12, "rest")                                       # 자정
    midnight = game.weather["temperature"]
    assert game.hour == 0 and midnight < noon - 10
    for _ in range(2):                                               # 예보(30시간)를 넘어가도 낮밤이 반복된다
        game.satiety = game.hydration = game.health = 100
        game.pass_time(12, "rest")
    assert game.hour == 0 and game.weather["temperature"] == pytest.approx(midnight)


def test_diurnal_curve_without_forecast(game):
    game.biome = "desert"
    game.start_hour, game.elapsed_hours = 15, 0
    game.set_weather(fake_weather(40, humidity=10, hourly=[]))
    assert game.weather["temperature"] == pytest.approx(40)          # 오후 3시 최고
    game.pass_time(12, "rest")                                       # 새벽 3시
    assert game.hour == 3 and game.weather["temperature"] == pytest.approx(40 - 2 * 11)


def test_clock_switches_to_local_time_zone(game):
    game.start_hour, game.start_offset, game.utc_offset, game.elapsed_hours = 10, 1, 1, 0
    profile = [{"hour": (17 + i) % 24, "temperature": 5.0, "feels_like": 5.0} for i in range(48)]
    game.set_weather(fake_weather(5, hourly=profile, utc_offset=8))   # 시차 +7시간 지역으로 이동
    assert game.hour == 17 and game.is_night is False
    game.pass_time(3, "rest")
    assert game.hour == 20 and game.is_night


def test_positive_events_everywhere():
    """어떤 상황에서도 그 상황에 맞는 긍정 이벤트가 3개 이상 있어야 한다."""
    for place in ("야생", "마을", "도시"):
        for biome in ("snow", "alpine", "desert", "jungle", "savanna", "forest"):
            for night in (False, True):
                for indoor in (False, True):
                    for weather in ("clear", "rain", "snow", "storm", "fog"):
                        for temp in (-10, 15, 35):
                            c = ctx(night=night, indoor=indoor, weather=weather, temp=temp)
                            lucky = [e for e in events_module.candidates(place, biome, c) if e["kind"] == "lucky"]
                            assert len(lucky) >= 3, (place, biome, c)
    texts = [e["text"] for e in events_module.EVENTS]
    assert len(texts) == len(set(texts))                             # 중복 이벤트 없음


def test_city_data_is_sane():
    assert len(places.CITY_LIST) > 200
    for c in places.CITY_LIST:
        assert -60 < c["lat"] < 75 and -180 <= c["lon"] <= 180 and c["mission"] in ("", "대", "영")
    near = places.nearest_city(-23.9, 133.5)
    assert near["name"] == "앨리스스프링스" and near["km"] < 50
    assert places.nearest_city(20.0, 0.0, max_km=100) is None


def test_reverse_geocode_returns_korean_and_english(monkeypatch):
    answers = {"ko": {"address": {"country": "오스트레일리아", "state": "노던 준주", "country_code": "AU"}},
               "en": {"address": {"country": "Australia", "state": "Northern Territory", "country_code": "AU"}}}

    def fake_get(url, params=None, **kw):
        return SimpleNamespace(json=lambda: answers[params["accept-language"]])

    monkeypatch.setattr(geo.requests, "get", fake_get)
    monkeypatch.setattr(geo.time, "sleep", lambda s: None)
    place = geo.reverse_geocode(-23.7, 133.9)
    assert place["name"] == "오스트레일리아, 노던 준주" and place["country_code"] == "au"
    assert place["name_en"] == "Australia, Northern Territory" and place["country_en"] == "Australia"


def test_every_city_country_has_a_sign_language():
    from survival.languages import SIGN_LANGUAGE
    assert {c["country"] for c in places.CITY_LIST} <= set(SIGN_LANGUAGE)


def test_season_wording_fits_barren_climates():
    assert climate.make_climate("desert", -23.9, 11)["season_en"] == "spring"
    assert "green" in climate.make_climate("temperate", 37, 4)["season_en"]
