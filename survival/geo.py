"""위치 관련 기능: 랜덤 좌표 뽑기, 지명 찾기, 거리 계산, 한국 방향으로 이동."""
import math
import random

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
    total = distance_to_korea(lat, lon)
    if total <= 1e-6 or km >= total:
        return SEOUL
    f = km / total
    p1, l1 = math.radians(lat), math.radians(lon)
    p2, l2 = math.radians(SEOUL[0]), math.radians(SEOUL[1])
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


def reverse_geocode(lat, lon):
    """좌표 → 지명. (OpenStreetMap Nominatim) 실패하면 None."""
    params = {"format": "jsonv2", "lat": lat, "lon": lon, "zoom": 8, "accept-language": "ko"}
    try:
        response = requests.get(REVERSE_URL, params=params, headers=HEADERS, timeout=TIMEOUT)
        data = response.json()
    except Exception:
        return None
    if "error" in data:
        return None
    address = data.get("address", {})
    country = address.get("country", "")
    region = (address.get("state") or address.get("region") or address.get("province")
              or address.get("county") or "")
    name = ", ".join(x for x in [country, region] if x) or data.get("display_name", "")
    return {"country": country, "region": region, "name": name}


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
