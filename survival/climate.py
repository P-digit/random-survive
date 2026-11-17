"""기후 판별: 최근 1년간의 실제 기온·강수량 기록으로 그 좌표의 기후대를 분류한다.

'지금 날씨'는 그날그날 달라지지만 '기후'는 그 땅의 성격이다. 사하라는 밤에 추워도 사막이고,
시베리아는 여름에 더워도 냉대 기후다. Open-Meteo의 과거 기록 API(키 불필요)를 사용한다.
"""
import datetime

import requests

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

# 기후대: (한글 이름, 이미지 프롬프트용 영어, 대응하는 지형)
ZONES = {
    "polar":       ("한대 기후", "polar tundra climate, treeless frozen ground, permanent snow and ice", "snow"),
    "alpine":      ("고산 기후", "high-altitude alpine climate, bare rock, sparse low vegetation", "alpine"),
    "desert":      ("사막 기후", "arid desert climate, bare sand and rock, almost no vegetation", "desert"),
    "steppe":      ("스텝 기후", "semi-arid steppe climate, dry short grass, few trees", "savanna"),
    "rainforest":  ("열대우림 기후", "tropical rainforest climate, dense lush evergreen jungle, very humid", "jungle"),
    "savanna":     ("사바나 기후", "tropical savanna climate, tall grass with scattered trees", "savanna"),
    "temperate":   ("온대 기후", "temperate climate, mixed broadleaf forest and farmland", "forest"),
    "continental": ("냉대 기후", "cold continental climate, boreal conifer forest (taiga)", "forest"),
}

SEASON_EN = {"봄": "spring, fresh green growth", "여름": "summer, full green foliage",
             "가을": "autumn, yellow and red foliage", "겨울": "winter, bare trees",
             "우기": "rainy season, lush and wet", "건기": "dry season, dry yellowed vegetation"}


def classify_zone(monthly_temp, monthly_precip, elevation=0.0):
    """월평균 기온(12개)과 월 강수량(12개)으로 기후대를 분류한다. (쾨펜 분류를 단순화)"""
    t_ann = sum(monthly_temp) / len(monthly_temp)
    t_cold, t_warm = min(monthly_temp), max(monthly_temp)
    p_ann = sum(monthly_precip)
    if elevation >= 2500:
        return "alpine"
    if t_warm < 10:
        return "polar"
    dry_limit = 20 * t_ann + 140          # 이보다 비가 적으면 건조 기후
    if p_ann < dry_limit / 2:
        return "desert"
    if p_ann < dry_limit:
        return "steppe"
    if t_cold >= 18:
        return "rainforest" if p_ann >= 1800 or min(monthly_precip) >= 60 else "savanna"
    if t_cold <= -3:
        return "continental"
    return "temperate"


def current_season(latitude, month, zone, monthly_precip=None):
    """지금 계절. 열대에서는 봄여름가을겨울 대신 우기/건기로 나눈다."""
    if zone in ("rainforest", "savanna") or abs(latitude) < 15:
        if monthly_precip and len(monthly_precip) == 12:
            return "우기" if monthly_precip[month - 1] >= sum(monthly_precip) / 12 else "건기"
        return "우기"
    seasons = ["겨울", "겨울", "봄", "봄", "봄", "여름", "여름", "여름", "가을", "가을", "가을", "겨울"]
    if latitude < 0:                      # 남반구는 계절이 반대
        month = (month + 5) % 12 + 1
    return seasons[month - 1]


def make_climate(zone, latitude, month, monthly_temp=None, monthly_precip=None, source="기록"):
    label, label_en, biome = ZONES[zone]
    season = current_season(latitude, month, zone, monthly_precip)
    climate = {"zone": zone, "label": label, "label_en": label_en, "biome": biome,
               "season": season, "season_en": SEASON_EN[season], "source": source}
    if monthly_temp:
        climate.update(t_ann=round(sum(monthly_temp) / 12, 1), t_cold=round(min(monthly_temp), 1),
                       t_warm=round(max(monthly_temp), 1), p_ann=round(sum(monthly_precip)))
    return climate


def guess_zone(latitude, weather):
    """기록을 가져오지 못했을 때: 위도와 지금 날씨로 대략 추정한다."""
    lat, temp, humidity = abs(latitude), weather["temperature"], weather["humidity"]
    if weather["elevation"] >= 2500:
        return "alpine"
    if lat >= 66:
        return "polar"
    if humidity < 35 and temp >= 18:
        return "desert"
    if lat < 12 and humidity >= 65:
        return "rainforest"
    if lat < 28:
        return "savanna"
    return "continental" if lat >= 50 else "temperate"


def get_climate(latitude, longitude, weather, today=None):
    """좌표의 기후 정보를 반환한다. 최근 1년 기록을 쓰고, 실패하면 추정값을 쓴다."""
    today = today or datetime.date.today()
    end = today - datetime.timedelta(days=10)       # 기록은 며칠 늦게 올라온다
    start = end - datetime.timedelta(days=364)
    try:
        response = requests.get(ARCHIVE_URL, timeout=15, params={
            "latitude": latitude, "longitude": longitude,
            "start_date": start.isoformat(), "end_date": end.isoformat(),
            "daily": "temperature_2m_mean,precipitation_sum", "timezone": "auto"})
        response.raise_for_status()
        daily = response.json()["daily"]
        temps = {m: [] for m in range(1, 13)}
        rains = {m: 0.0 for m in range(1, 13)}
        for day, temp, rain in zip(daily["time"], daily["temperature_2m_mean"], daily["precipitation_sum"]):
            month = int(str(day)[5:7])
            if temp is not None:
                temps[month].append(float(temp))
            rains[month] += float(rain or 0)
        if any(not values for values in temps.values()):
            raise ValueError("기록이 부족함")
        monthly_temp = [sum(temps[m]) / len(temps[m]) for m in range(1, 13)]
        monthly_precip = [rains[m] for m in range(1, 13)]
        zone = classify_zone(monthly_temp, monthly_precip, weather["elevation"])
        return make_climate(zone, latitude, today.month, monthly_temp, monthly_precip)
    except Exception:
        return make_climate(guess_zone(latitude, weather), latitude, today.month, source="추정")


def describe(climate):
    """'사막 기후 · 건기 · 연평균 27°C · 연강수 40mm' 형태의 한 줄 설명."""
    if not climate:
        return "알 수 없음"
    text = f"{climate['label']} · 지금은 {climate['season']}"
    if "t_ann" in climate:
        text += (f" · 연평균 {climate['t_ann']:.0f}°C (가장 추운 달 {climate['t_cold']:.0f}°C, "
                 f"가장 더운 달 {climate['t_warm']:.0f}°C) · 연강수 {climate['p_ann']:,}mm")
    return text
