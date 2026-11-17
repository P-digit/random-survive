"""Open-Meteo에서 현재 날씨와 시간별 예보를 가져온다. (API 키 필요 없음)"""
import requests

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# WMO 날씨 코드 → (한글 설명, 이모지, 이미지 프롬프트용 영어)
WEATHER_CODES = {
    0: ("맑음", "☀️", "clear sky"),
    1: ("대체로 맑음", "🌤️", "mostly clear sky"),
    2: ("구름 조금", "⛅", "partly cloudy"),
    3: ("흐림", "☁️", "overcast"),
    45: ("안개", "🌫️", "foggy"),
    48: ("짙은 안개", "🌫️", "dense freezing fog"),
    51: ("약한 이슬비", "🌦️", "light drizzle"),
    53: ("이슬비", "🌦️", "drizzle"),
    55: ("강한 이슬비", "🌧️", "heavy drizzle"),
    56: ("어는 이슬비", "🌧️", "freezing drizzle"),
    57: ("강한 어는 이슬비", "🌧️", "freezing drizzle"),
    61: ("약한 비", "🌦️", "light rain"),
    63: ("비", "🌧️", "rain"),
    65: ("폭우", "🌧️", "heavy rain"),
    66: ("어는 비", "🌧️", "freezing rain"),
    67: ("강한 어는 비", "🌧️", "freezing rain"),
    71: ("약한 눈", "🌨️", "light snowfall"),
    73: ("눈", "🌨️", "snowfall"),
    75: ("폭설", "❄️", "heavy snowfall"),
    77: ("싸락눈", "🌨️", "snow grains"),
    80: ("소나기", "🌦️", "rain showers"),
    81: ("강한 소나기", "🌧️", "heavy rain showers"),
    82: ("매우 강한 소나기", "⛈️", "violent rain showers"),
    85: ("눈 소나기", "🌨️", "snow showers"),
    86: ("강한 눈 소나기", "❄️", "heavy snow showers"),
    95: ("뇌우", "⛈️", "thunderstorm"),
    96: ("우박 동반 뇌우", "⛈️", "thunderstorm with hail"),
    99: ("강한 우박 동반 뇌우", "⛈️", "violent thunderstorm with hail"),
}


def weather_category(code):
    """날씨 코드를 장면 이미지에 영향을 주는 큰 분류로 묶는다."""
    if code in (95, 96, 99):
        return "storm"
    if code in (71, 73, 75, 77, 85, 86):
        return "snow"
    if code in (51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82):
        return "rain"
    if code in (45, 48):
        return "fog"
    return "clear"


def _parse_hourly(data):
    """현재 시각부터의 시간별 예보 목록. 게임 속 시간이 흐르면 이 목록에서 날씨를 꺼내 쓴다."""
    try:
        hourly = data["hourly"]
        times = hourly["time"]
        now = str(data["current"]["time"])[:13]          # 'YYYY-MM-DDTHH'
        start = next((i for i, t in enumerate(times) if str(t)[:13] == now), 0)
        result = []
        for i in range(start, len(times)):
            temp = hourly["temperature_2m"][i]
            if temp is None:
                break
            code = int(hourly["weather_code"][i] or 0)
            desc, emoji, desc_en = WEATHER_CODES.get(code, ("알 수 없음", "❔", "unknown weather"))
            result.append({
                "temperature": float(temp),
                "feels_like": float(hourly["apparent_temperature"][i] if hourly["apparent_temperature"][i] is not None else temp),
                "humidity": float(hourly["relative_humidity_2m"][i] or 50),
                "precipitation": float(hourly["precipitation"][i] or 0),
                "wind_speed": float(hourly["wind_speed_10m"][i] or 0),
                "code": code, "description": desc, "emoji": emoji, "description_en": desc_en,
            })
        return result
    except Exception:
        return []


def get_weather(latitude, longitude):
    """해당 좌표의 현재 날씨를 딕셔너리로 반환한다. 실패 시 기본값을 돌려준다."""
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "current": "temperature_2m,relative_humidity_2m,apparent_temperature,"
                   "precipitation,weather_code,wind_speed_10m,is_day",
        "hourly": "temperature_2m,relative_humidity_2m,apparent_temperature,"
                  "precipitation,weather_code,wind_speed_10m",
        "forecast_days": 4,
        "timezone": "auto",
    }
    try:
        response = requests.get(FORECAST_URL, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        cur = data["current"]
        code = int(cur.get("weather_code", 0))
        desc, emoji, desc_en = WEATHER_CODES.get(code, ("알 수 없음", "❔", "unknown weather"))
        return {
            "ok": True,
            "temperature": float(cur["temperature_2m"]),
            "feels_like": float(cur.get("apparent_temperature", cur["temperature_2m"])),
            "humidity": float(cur.get("relative_humidity_2m", 50)),
            "precipitation": float(cur.get("precipitation", 0)),
            "wind_speed": float(cur.get("wind_speed_10m", 0)),
            "is_day": bool(cur.get("is_day", 1)),
            "code": code,
            "description": desc,
            "emoji": emoji,
            "description_en": desc_en,
            "elevation": float(data.get("elevation", 0) or 0),
            "local_hour": int(str(cur.get("time", "T12:00")).split("T")[1][:2]),
            "hourly": _parse_hourly(data),
        }
    except Exception:
        return {
            "ok": False, "temperature": 15.0, "feels_like": 15.0, "humidity": 50.0,
            "precipitation": 0.0, "wind_speed": 5.0, "is_day": True, "code": -1,
            "description": "관측 불가", "emoji": "❔", "description_en": "unknown weather",
            "elevation": 0.0, "local_hour": 12, "hourly": [],
        }
