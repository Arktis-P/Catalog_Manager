from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

from desktop import app_launcher
from desktop.network_config import AppProxyConfig


def test_browser_proxy_flag_is_added_only_when_enabled(monkeypatch) -> None:
    browser = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    profile = Path(r"C:\Temp\CatalogueManagerProfile")
    popen = Mock(return_value=Mock())

    monkeypatch.setattr(app_launcher.launcher, "find_browser", lambda: browser)
    monkeypatch.setattr(app_launcher.subprocess, "Popen", popen)
    monkeypatch.setattr(app_launcher.launcher, "_hidden_subprocess_kwargs", lambda: {})
    monkeypatch.setattr(
        app_launcher,
        "_proxy_config",
        AppProxyConfig(
            enabled=True,
            listen_host="127.0.0.1",
            listen_port=1180,
            upstream_host="proxy.example.test",
        ),
    )

    app_launcher._open_app_browser("http://127.0.0.1:8000", profile)

    args = popen.call_args.args[0]
    assert "--proxy-server=socks5://127.0.0.1:1180" in args
    assert "--app=http://127.0.0.1:8000" in args


def test_browser_proxy_flag_is_absent_when_disabled(monkeypatch) -> None:
    browser = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    popen = Mock(return_value=Mock())

    monkeypatch.setattr(app_launcher.launcher, "find_browser", lambda: browser)
    monkeypatch.setattr(app_launcher.subprocess, "Popen", popen)
    monkeypatch.setattr(app_launcher.launcher, "_hidden_subprocess_kwargs", lambda: {})
    monkeypatch.setattr(app_launcher, "_proxy_config", AppProxyConfig(enabled=False))

    app_launcher._open_app_browser("http://127.0.0.1:8000", Path("profile"))

    args = popen.call_args.args[0]
    assert not any(arg.startswith("--proxy-server=") for arg in args)
