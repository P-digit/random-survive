"""모든 테스트에 공통으로 적용되는 설정."""
import socket

import pytest

from survival import climate, geo, state as state_module
from survival.state import GameState
from tests.helpers import fake_weather, patch_everywhere


_real_connect = socket.socket.connect
_blocked = []


def _guarded_connect(sock, address, *args, **kwargs):
    host = address[0] if isinstance(address, tuple) else address
    if sock.family == socket.AF_UNIX or host in ("127.0.0.1", "::1", "localhost"):
        return _real_connect(sock, address, *args, **kwargs)
    _blocked.append(address)
    raise RuntimeError(f"테스트가 외부 네트워크에 접속하려 했다: {address}. 날씨·지명·LLM 호출을 가짜로 바꿔야 한다.")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """테스트는 외부 네트워크를 쓰지 않는다.

    가짜로 바꾸는 것을 빠뜨리면 접속이 막힌다. 날씨 조회처럼 오류를 스스로 삼키고 기본값으로 넘어가는 코드도 있어서,
    막힌 접속이 한 번이라도 있었으면 테스트가 끝날 때 실패시킨다.
    """
    _blocked.clear()
    monkeypatch.setattr(socket.socket, "connect", _guarded_connect)
    yield
    assert not _blocked, f"외부 네트워크 접속 시도(가짜로 바꾸지 않은 호출): {_blocked[:3]}"


@pytest.fixture
def game(monkeypatch):
    """네트워크 호출을 모두 가짜로 바꾼 게임 상태 (몽골 초원에서 시작)."""
    patch_everywhere(monkeypatch, "get_weather", lambda lat, lon: fake_weather())   # state, travel, ...
    monkeypatch.setattr(geo, "reverse_geocode", lambda lat, lon: {"name": "테스트 지역"})
    monkeypatch.setattr(geo, "is_land", lambda lat, lon: True)
    monkeypatch.setattr(state_module, "EARLY_GAME_HOURS", 0)   # 대부분의 테스트는 초반 제한 없이 (따로 테스트함)
    monkeypatch.setattr(state_module.climate_api, "get_climate",
                        lambda lat, lon, weather, today=None: climate.make_climate("temperate", lat, 7))
    lat, lon = 46.9, 103.8
    distance = geo.distance_to_korea(lat, lon)
    return GameState(lat=lat, lon=lon, place_name="몽골", weather=fake_weather(), biome="forest",
                     start_distance=distance, distance=distance)


@pytest.fixture(autouse=True)
def private_hall_of_fame(monkeypatch, tmp_path):
    """업적의 '명예의 전당' 파일을 테스트마다 임시 폴더에 둔다 (실제 saves/ 에 쓰지 않는다)."""
    from survival import achievements
    monkeypatch.setattr(achievements, "HALL_PATH", tmp_path / "hall_of_fame.json")
