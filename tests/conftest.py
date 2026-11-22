"""모든 테스트에 공통으로 적용되는 설정."""
import socket

import pytest

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
