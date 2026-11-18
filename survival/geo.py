"""위치 관련 기능: 랜덤 좌표 뽑기, 지명 찾기, 거리 계산, 한국 방향으로 이동."""
import math
import random
import time

import requests

from .config import SEOUL

ELEVATION_URL = "https://api.open-meteo.com/v1/elevation"
REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"
HEADERS = {"User-Agent": "random-survival-game/0.1 (student project)"}
TIMEOUT = 10


def haversine_km(lat1, lon1, lat2, lon2):
    """두 좌표 사이의 대권 거리(km)."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def distance_to_korea(lat, lon):
    return haversine_km(lat, lon, *SEOUL)


def move_toward_korea(lat, lon, km):
    """현재 위치에서 서울 방향 대권 경로를 따라 km만큼 이동한 좌표를 반환한다."""
    return move_toward(lat, lon, SEOUL[0], SEOUL[1], km)


def bearing_deg(lat1, lon1, lat2, lon2):
    """1에서 2를 바라보는 방위각(도, 북쪽 0, 시계 방향)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def destination(lat, lon, bearing, km):
    """한 지점에서 방위각 bearing 쪽으로 km 떨어진 좌표."""
    d = km / 6371.0
    b = math.radians(bearing)
    p1, l1 = math.radians(lat), math.radians(lon)
    p2 = math.asin(math.sin(p1) * math.cos(d) + math.cos(p1) * math.sin(d) * math.cos(b))
    l2 = l1 + math.atan2(math.sin(b) * math.sin(d) * math.cos(p1), math.cos(d) - math.sin(p1) * math.sin(p2))
    return round(math.degrees(p2), 4), round((math.degrees(l2) + 540) % 360 - 180, 4)


def move_toward(lat, lon, target_lat, target_lon, km):
    """현재 위치에서 목표 지점 방향 대권 경로를 따라 km만큼 이동한 좌표. 목표를 넘으면 목표 지점."""
    total = haversine_km(lat, lon, target_lat, target_lon)
    if total <= 1e-6 or km >= total:
        return target_lat, target_lon
    f = km / total
    p1, l1 = math.radians(lat), math.radians(lon)
    p2, l2 = math.radians(target_lat), math.radians(target_lon)
    d = total / 6371.0  # 각거리
    a = math.sin((1 - f) * d) / math.sin(d)
    b = math.sin(f * d) / math.sin(d)
    x = a * math.cos(p1) * math.cos(l1) + b * math.cos(p2) * math.cos(l2)
    y = a * math.cos(p1) * math.sin(l1) + b * math.cos(p2) * math.sin(l2)
    z = a * math.sin(p1) + b * math.sin(p2)
    new_lat = math.degrees(math.atan2(z, math.sqrt(x * x + y * y)))
    new_lon = math.degrees(math.atan2(y, x))
    return round(new_lat, 4), round(new_lon, 4)


def random_coordinates(n=40):
    """지구 표면에서 균일하게 n개의 좌표를 뽑는다. (남극·북극권 일부는 제외)"""
    lo, hi = math.sin(math.radians(-50)), math.sin(math.radians(68))
    points = []
    for _ in range(n):
        lat = math.degrees(math.asin(random.uniform(lo, hi)))
        lon = random.uniform(-180, 180)
        points.append((round(lat, 4), round(lon, 4)))
    return points


def get_elevations(points):
    """Open-Meteo Elevation API로 여러 좌표의 고도를 한 번에 조회한다. 바다는 0 이하."""
    params = {
        "latitude": ",".join(str(p[0]) for p in points),
        "longitude": ",".join(str(p[1]) for p in points),
    }
    response = requests.get(ELEVATION_URL, params=params, timeout=TIMEOUT)
    response.raise_for_status()
    return response.json()["elevation"]


def is_land(lat, lon):
    """해당 좌표가 육지인지 확인한다. 조회 실패 시에는 None."""
    try:
        return get_elevations([(lat, lon)])[0] > 0
    except Exception:
        return None


def _nominatim(lat, lon, lang):
    params = {"format": "jsonv2", "lat": lat, "lon": lon, "zoom": 8, "accept-language": lang}
    try:
        data = requests.get(REVERSE_URL, params=params, headers=HEADERS, timeout=TIMEOUT).json()
    except Exception:
        return None
    if "error" in data:
        return None
    address = data.get("address", {})
    country = address.get("country", "")
    region = (address.get("state") or address.get("region") or address.get("province")
              or address.get("county") or "")
    name = ", ".join(x for x in [country, region] if x) or data.get("display_name", "")
    return {"country": country, "region": region, "name": name,
            "country_code": str(address.get("country_code", "")).lower()}


def reverse_geocode(lat, lon):
    """좌표 → 지명. (OpenStreetMap Nominatim) 실패하면 None.

    화면에는 한국어 지명(name)을, 그림 지시문에는 영어 지명(name_en)을 쓴다. 그림 지시문에 한글이 섞이면
    이미지 모델이 그림 속 표지판에 엉터리 한글을 그려 넣기 때문이다.
    """
    korean = _nominatim(lat, lon, "ko")
    if korean is None:
        return None
    time.sleep(1.0)                      # Nominatim 이용 규칙: 초당 1회 이하
    english = _nominatim(lat, lon, "en") or {}
    korean["name_en"] = english.get("name", "")
    korean["country_en"] = english.get("country", "")
    return korean


def pick_random_land():
    """한국에서 충분히 먼 랜덤 육지 좌표를 하나 고른다."""
    for _ in range(4):
        points = random_coordinates()
        try:
            elevations = get_elevations(points)
        except Exception:
            break
        for (lat, lon), elev in zip(points, elevations):
            if elev is None or elev <= 0:
                continue  # 바다
            if distance_to_korea(lat, lon) < 1500:
                continue  # 너무 가까우면 재미없음
            return lat, lon, elev
    # API 실패 시 사용하는 예비 좌표 (사하라, 아마존, 몽골, 알래스카, 호주 내륙)
    lat, lon = random.choice([(23.4, 11.2), (-3.5, -62.1), (46.9, 103.8), (64.8, -147.7), (-24.9, 133.4)])
    return lat, lon, 300.0
