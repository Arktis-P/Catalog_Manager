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
        AppProxyConfig(enabled=True, listen_host="127.0.0.1", listen_port=1180),
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


def test_japan_ssh_mode_starts_dynamic_forward(monkeypatch, tmp_path: Path) -> None:
    key_file = tmp_path / "test-key"
    key_file.write_text("test", encoding="utf-8")
    process = Mock()
    process.poll.return_value = None
    popen = Mock(return_value=process)
    port_checks = iter([False, True])

    monkeypatch.setattr(app_launcher, "_port_is_open", lambda *_args, **_kwargs: next(port_checks))
    monkeypatch.setattr(app_launcher.shutil, "which", lambda name: r"C:\Windows\System32\OpenSSH\ssh.exe")
    monkeypatch.setattr(app_launcher.subprocess, "Popen", popen)
    monkeypatch.setattr(app_launcher.launcher, "runtime_log_dir", lambda: tmp_path)
    monkeypatch.setattr(app_launcher.launcher, "_hidden_subprocess_kwargs", lambda: {})

    config = AppProxyConfig(
        enabled=True,
        mode="ssh",
        expected_country="JP",
        listen_host="127.0.0.1",
        listen_port=1080,
        ssh_host="203.0.113.10",
        ssh_port=22,
        ssh_user="ubuntu",
        ssh_key_file=str(key_file),
    )

    app_launcher._start_proxy_endpoint(config)

    args = popen.call_args.args[0]
    assert "-D" in args
    assert "127.0.0.1:1080" in args
    assert "-N" in args
    assert "ubuntu@203.0.113.10" in args
    assert "ExitOnForwardFailure=yes" in args

    if app_launcher._proxy_log_handle is not None:
        app_launcher._proxy_log_handle.close()
    app_launcher._proxy_log_handle = None
    app_launcher._proxy_process = None
