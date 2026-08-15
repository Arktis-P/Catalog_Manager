from __future__ import annotations

from unittest.mock import Mock

from desktop.network_config import AppProxyConfig
from desktop.socks_bridge import _authenticate_upstream, _negotiate_local_client


def _fake_socket(*responses: bytes) -> Mock:
    sock = Mock()
    sock.recv.side_effect = list(responses)
    return sock


def test_local_client_negotiates_no_auth_and_preserves_domain_target() -> None:
    sock = _fake_socket(
        b"\x05\x01",
        b"\x00",
        b"\x05\x01\x00\x03",
        b"\x0b",
        b"example.com",
        b"\x01\xbb",
    )

    atyp, address, port = _negotiate_local_client(sock)

    assert sock.sendall.call_args_list[0].args[0] == b"\x05\x00"
    assert atyp == 3
    assert address == b"\x0bexample.com"
    assert port == b"\x01\xbb"


def test_upstream_username_password_authentication() -> None:
    sock = _fake_socket(b"\x05\x02", b"\x01\x00")
    config = AppProxyConfig(
        enabled=True,
        upstream_host="proxy.example.test",
        upstream_username="user",
        upstream_password="pass",
    )

    _authenticate_upstream(sock, config)

    sent = [call.args[0] for call in sock.sendall.call_args_list]
    assert sent[0] == b"\x05\x01\x02"
    assert sent[1] == b"\x01\x04user\x04pass"


def test_upstream_no_authentication_when_credentials_are_empty() -> None:
    sock = _fake_socket(b"\x05\x00")
    config = AppProxyConfig(enabled=True, upstream_host="proxy.example.test")

    _authenticate_upstream(sock, config)

    sock.sendall.assert_called_once_with(b"\x05\x01\x00")
