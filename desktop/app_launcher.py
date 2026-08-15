"""Catalogue Manager desktop entry point with optional app-scoped proxy routing."""

from __future__ import annotations

import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

from desktop import launcher
from desktop.network_config import AppProxyConfig, load_app_proxy_config

_proxy_process: subprocess.Popen | None = None
_proxy_log_handle = None
_proxy_config = AppProxyConfig()


def _port_is_open(host: str, port: int, timeout: float = 0.25) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _start_proxy_endpoint(config: AppProxyConfig, timeout_seconds: float = 10) -> None:
    global _proxy_process, _proxy_log_handle
    if not config.enabled:
        return
    config.validate()

    if _port_is_open(config.listen_host, config.listen_port):
        print(
            f"[desktop] Using existing local SOCKS5 endpoint at "
            f"{config.listen_host}:{config.listen_port}.",
            flush=True,
        )
        return

    log_path = launcher.runtime_log_dir() / "proxy.log"
    _proxy_log_handle = log_path.open("a", encoding="utf-8")

    if config.mode == "ssh":
        ssh_exe = shutil.which("ssh")
        if not ssh_exe:
            raise RuntimeError("Windows OpenSSH client (ssh.exe) was not found in PATH")
        key_path = config.ssh_key_path
        if not key_path.is_file():
            raise RuntimeError(f"SSH key file not found: {key_path}")
        command = [
            ssh_exe,
            "-N",
            "-D",
            f"{config.listen_host}:{config.listen_port}",
            "-o",
            "ExitOnForwardFailure=yes",
            "-o",
            "ServerAliveInterval=30",
            "-o",
            "ServerAliveCountMax=3",
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-o",
            "IdentitiesOnly=yes",
            "-p",
            str(config.ssh_port),
            "-i",
            str(key_path),
            config.ssh_target,
        ]
    else:
        command = [sys.executable, "-m", "desktop.socks_bridge"]

    _proxy_process = subprocess.Popen(
        command,
        cwd=launcher.PROJECT_ROOT,
        stdout=_proxy_log_handle,
        stderr=subprocess.STDOUT,
        **launcher._hidden_subprocess_kwargs(),
    )

    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if _port_is_open(config.listen_host, config.listen_port):
            mode_label = "SSH dynamic forward" if config.mode == "ssh" else "SOCKS5 bridge"
            print(
                f"[desktop] {mode_label} ready at {config.listen_host}:{config.listen_port}.",
                flush=True,
            )
            return
        if _proxy_process.poll() is not None:
            break
        time.sleep(0.1)

    exit_code = _proxy_process.poll() if _proxy_process is not None else None
    _stop_proxy_endpoint()
    raise RuntimeError(
        f"App proxy failed to start (exit={exit_code}). See {log_path}."
    )


def _stop_proxy_endpoint() -> None:
    global _proxy_process, _proxy_log_handle
    if _proxy_process is not None and _proxy_process.poll() is None:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(_proxy_process.pid)],
                capture_output=True,
                text=True,
            )
        else:
            _proxy_process.terminate()
            try:
                _proxy_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                _proxy_process.kill()
    _proxy_process = None

    if _proxy_log_handle not in (None, subprocess.DEVNULL):
        try:
            _proxy_log_handle.close()
        except OSError:
            pass
    _proxy_log_handle = None


def _open_app_browser(url: str, profile_dir: Path) -> "subprocess.Popen[bytes] | None":
    browser = launcher.find_browser()
    if browser is None:
        print(f"[desktop] Chrome/Edge not found. Open manually: {url}", flush=True)
        if _proxy_config.enabled:
            print(
                "[desktop] Manual browser launch will NOT inherit the app proxy. "
                f"Use --proxy-server={_proxy_config.browser_proxy_url}.",
                flush=True,
            )
        return None

    args = [
        str(browser),
        f"--app={url}",
        f"--user-data-dir={profile_dir}",
        "--new-window",
        "--window-size=1440,900",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    if _proxy_config.enabled:
        args.append(f"--proxy-server={_proxy_config.browser_proxy_url}")
        print(
            f"[desktop] Browser external traffic: {_proxy_config.browser_proxy_url}",
            flush=True,
        )

    return subprocess.Popen(args, **launcher._hidden_subprocess_kwargs())


def run_desktop() -> int:
    global _proxy_config
    try:
        _proxy_config = load_app_proxy_config()
        _start_proxy_endpoint(_proxy_config)
        launcher.open_app_browser = _open_app_browser
        return launcher.run_desktop()
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"[desktop] Failed to initialize app proxy: {exc}", flush=True)
        return 1
    finally:
        _stop_proxy_endpoint()


def main() -> None:
    raise SystemExit(run_desktop())


if __name__ == "__main__":
    main()
