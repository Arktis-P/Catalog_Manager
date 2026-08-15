from __future__ import annotations

from unittest.mock import Mock

from app.integrations.danbooru import client as client_module


def _new_client() -> client_module.DanbooruClient:
    return client_module.DanbooruClient(username="test-user", api_key="test-key", request_delay=0)


def test_pybooru_stays_direct_when_app_proxy_is_disabled(monkeypatch) -> None:
    fake_danbooru = Mock(return_value=Mock())
    monkeypatch.setattr(client_module, "Danbooru", fake_danbooru)
    monkeypatch.setattr(client_module.settings, "app_proxy_enabled", False)

    _ = _new_client().client

    assert fake_danbooru.call_args.kwargs["proxies"] is None


def test_pybooru_uses_only_loopback_app_proxy_when_enabled(monkeypatch) -> None:
    fake_danbooru = Mock(return_value=Mock())
    monkeypatch.setattr(client_module, "Danbooru", fake_danbooru)
    monkeypatch.setattr(client_module.settings, "app_proxy_enabled", True)
    monkeypatch.setattr(client_module.settings, "app_proxy_host", "127.0.0.1")
    monkeypatch.setattr(client_module.settings, "app_proxy_port", 1180)

    _ = _new_client().client

    assert fake_danbooru.call_args.kwargs["proxies"] == {
        "http": "socks5h://127.0.0.1:1180",
        "https": "socks5h://127.0.0.1:1180",
    }


def test_pybooru_rejects_non_loopback_proxy_listener(monkeypatch) -> None:
    monkeypatch.setattr(client_module.settings, "app_proxy_enabled", True)
    monkeypatch.setattr(client_module.settings, "app_proxy_host", "192.168.0.10")
    monkeypatch.setattr(client_module.settings, "app_proxy_port", 1080)

    try:
        _new_client().client
    except ValueError as exc:
        assert "loopback" in str(exc)
    else:
        raise AssertionError("expected non-loopback app proxy to be rejected")
