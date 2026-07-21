"""Catalogue Manager desktop shell.

Architecture:
  pywebview (WebView2 on Windows) + React GUI + FastAPI backend

The launcher owns the backend process lifecycle. Closing the window stops the server.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
FRONTEND_DIR = PROJECT_ROOT / "frontend"
DIST_DIR = FRONTEND_DIR / "dist"
APP_ICON_PATH = PROJECT_ROOT / "desktop" / "assets" / "appicon.ico"
BACKEND_PORT = 8000
APP_URL = f"http://127.0.0.1:{BACKEND_PORT}"

_backend_process: subprocess.Popen | None = None
_log_handle = None


def runtime_log_dir() -> Path:
    """Use LOCALAPPDATA to avoid OneDrive file locks in the project folder."""
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path.home() / ".local" / "share"
    log_dir = base / "CatalogueManager" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def _hidden_subprocess_kwargs() -> dict:
    if sys.platform != "win32":
        return {}
    return {"creationflags": subprocess.CREATE_NO_WINDOW}


def ensure_frontend_build() -> None:
    dist_index = DIST_DIR / "index.html"
    src_dir = FRONTEND_DIR / "src"

    def build_is_stale() -> bool:
        if not dist_index.is_file():
            return True
        dist_mtime = dist_index.stat().st_mtime
        for path in src_dir.rglob("*"):
            if path.is_file() and path.stat().st_mtime > dist_mtime:
                return True
        return False

    if not build_is_stale():
        return

    print("[desktop] Building frontend...")
    subprocess.run(
        ["npm", "run", "build"],
        cwd=FRONTEND_DIR,
        check=True,
        shell=sys.platform == "win32",
    )


def wait_for_server(url: str, timeout_seconds: int = 90) -> bool:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        process = _backend_process
        if process is None or process.poll() is not None:
            return False
        payload = None
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                payload = json.load(response) if response.status == 200 else None
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError):
            pass
        if process.poll() is not None:
            return False
        if (
            isinstance(payload, dict)
            and payload.get("status") == "ok"
            and payload.get("serve_gui") is True
            and payload.get("gui_ready") is True
        ):
            return True
        time.sleep(0.5)
    return False


def backend_exit_message(log_path: Path | None) -> str:
    if _backend_process is None:
        return "backend process was not started"
    code = _backend_process.poll()
    if code is None:
        return "backend process is still running but /api/health did not respond in time"
    return f"backend process exited early with code {code}"


def read_log_tail(log_path: Path | None, max_lines: int = 20) -> str:
    if log_path is None or not log_path.is_file():
        return ""
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    if not lines:
        return ""
    return "\n".join(lines[-max_lines:])


def _open_log_file() -> tuple[Path | None, object]:
    log_dir = runtime_log_dir()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_path = log_dir / f"backend-{stamp}.log"
    try:
        handle = log_path.open("a", encoding="utf-8")
        return log_path, handle
    except OSError as exc:
        print(f"[desktop] Warning: could not open log file ({exc}). Logging disabled.")
        return None, subprocess.DEVNULL


def _listening_pids(port: int) -> set[int]:
    try:
        result = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return set()

    pids: set[int] = set()
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) < 5 or parts[3].upper() != "LISTENING":
            continue
        local_address = parts[1]
        if local_address.rsplit(":", 1)[-1] != str(port):
            continue
        pid = parts[-1]
        if pid.isdigit() and int(pid) != os.getpid():
            pids.add(int(pid))
    return pids


def _child_process_pids(parent_pid: int) -> set[int]:
    """Return direct Windows children for an owner PID that has already exited."""
    command = (
        "Get-CimInstance Win32_Process "
        f'-Filter "ParentProcessId = {parent_pid}" '
        "| Select-Object -ExpandProperty ProcessId"
    )
    try:
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                command,
            ],
            capture_output=True,
            text=True,
            check=False,
            **_hidden_subprocess_kwargs(),
        )
    except OSError:
        return set()
    if result.returncode != 0:
        return set()
    return {
        int(line.strip())
        for line in result.stdout.splitlines()
        if line.strip().isdigit() and int(line.strip()) != os.getpid()
    }


def _kill_process_tree(pid: int) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["taskkill", "/F", "/T", "/PID", str(pid)],
        capture_output=True,
        text=True,
        **_hidden_subprocess_kwargs(),
    )


def release_listening_port(port: int, timeout_seconds: float = 5) -> None:
    """Stop stray listeners left by a crashed desktop session."""
    if sys.platform != "win32":
        return

    deadline = time.time() + timeout_seconds
    while True:
        pids = _listening_pids(port)
        if not pids:
            return
        for pid in pids:
            result = _kill_process_tree(pid)
            if result.returncode != 0:
                for child_pid in _child_process_pids(pid):
                    _kill_process_tree(child_pid)
        if time.time() >= deadline:
            return
        time.sleep(0.1)


def start_backend() -> Path | None:
    global _backend_process, _log_handle

    if _backend_process and _backend_process.poll() is None:
        stop_backend()

    log_path, _log_handle = _open_log_file()

    env = os.environ.copy()
    env["CATALOGUE_SERVE_GUI"] = "1"

    _backend_process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(BACKEND_PORT),
        ],
        cwd=BACKEND_DIR,
        env=env,
        stdout=_log_handle,
        stderr=subprocess.STDOUT,
        **_hidden_subprocess_kwargs(),
    )
    return log_path


def stop_backend() -> None:
    global _backend_process, _log_handle

    if _backend_process is not None and _backend_process.poll() is None:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(_backend_process.pid)],
                capture_output=True,
                text=True,
            )
        else:
            _backend_process.terminate()
            try:
                _backend_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                _backend_process.kill()

    _backend_process = None

    if _log_handle not in (None, subprocess.DEVNULL):
        try:
            _log_handle.close()
        except OSError:
            pass
    _log_handle = None


def app_icon_path() -> str | None:
    if APP_ICON_PATH.is_file():
        return str(APP_ICON_PATH.resolve())
    return None


_BROWSER_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]


def find_browser() -> Path | None:
    for candidate in _BROWSER_CANDIDATES:
        p = Path(candidate)
        if p.is_file():
            return p
    return None


def open_app_browser(url: str) -> "subprocess.Popen[bytes] | None":
    browser = find_browser()
    if browser is None:
        print(f"[desktop] Chrome/Edge not found. Open manually: {url}", flush=True)
        return None

    if sys.platform == "win32":
        profile_dir = (
            Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
            / "CatalogueManager"
            / "browser-profile"
        )
    else:
        profile_dir = Path.home() / ".local" / "share" / "CatalogueManager" / "browser-profile"
    profile_dir.mkdir(parents=True, exist_ok=True)

    return subprocess.Popen(
        [
            str(browser),
            f"--app={url}",
            f"--user-data-dir={profile_dir}",
            "--new-window",
            "--window-size=1440,900",
            "--no-first-run",
            "--no-default-browser-check",
        ],
        **_hidden_subprocess_kwargs(),
    )


def run_desktop() -> int:
    log_path: Path | None = None
    try:
        ensure_frontend_build()
        release_listening_port(BACKEND_PORT)
        log_path = start_backend()

        if not wait_for_server(f"{APP_URL}/api/health"):
            log_hint = log_path or runtime_log_dir()
            print(f"[desktop] Backend failed to start. See log: {log_hint}", flush=True)
            print(f"[desktop] {backend_exit_message(log_path)}", flush=True)
            tail = read_log_tail(log_path)
            if tail:
                print("[desktop] Last backend log lines:", flush=True)
                print(tail, flush=True)
            stop_backend()
            return 1

        # Bust SPA cache and avoid reusing a stale app tab from the shared profile.
        boot_url = f"{APP_URL}/?_boot={int(time.time())}"
        browser_proc = open_app_browser(boot_url)
        if browser_proc is None:
            # 브라우저를 찾지 못한 경우 URL 출력 후 Ctrl+C 대기
            print(f"[desktop] App running at {APP_URL}  (Ctrl+C to stop)", flush=True)
            if _backend_process is not None:
                _backend_process.wait()
        else:
            browser_proc.wait()

        stop_backend()
        return 0
    except KeyboardInterrupt:
        stop_backend()
        return 0
    except Exception as exc:
        print(f"[desktop] Failed to launch: {exc}", flush=True)
        stop_backend()
        return 1


def main() -> None:
    raise SystemExit(run_desktop())


if __name__ == "__main__":
    main()
