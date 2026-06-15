"""Catalogue Manager desktop shell.

Architecture:
  pywebview (WebView2 on Windows) + React GUI + FastAPI backend

The launcher owns the backend process lifecycle. Closing the window stops the server.
"""

from __future__ import annotations

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
    if (DIST_DIR / "index.html").exists():
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
        if _backend_process is not None and _backend_process.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return True
        except (urllib.error.URLError, TimeoutError):
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


def release_listening_port(port: int) -> None:
    """Stop stray listeners left by a crashed desktop session."""
    if sys.platform != "win32":
        return
    try:
        result = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return
    needle = f":{port}"
    for line in result.stdout.splitlines():
        if "LISTENING" not in line or needle not in line:
            continue
        parts = line.split()
        if not parts:
            continue
        pid = parts[-1]
        if pid.isdigit() and int(pid) != os.getpid():
            subprocess.run(
                ["taskkill", "/F", "/PID", pid],
                capture_output=True,
                text=True,
                **_hidden_subprocess_kwargs(),
            )


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


def ensure_windows_app_identity() -> None:
    """Group taskbar entry under our icon instead of python.exe on Windows."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("CatalogueManager.Desktop.1")
    except Exception:
        pass


def run_desktop() -> int:
    import webview

    ensure_windows_app_identity()
    icon = app_icon_path()
    if icon is None:
        print(f"[desktop] Warning: app icon not found at {APP_ICON_PATH}")

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

        window = webview.create_window(
            "Catalogue Manager",
            APP_URL,
            width=1440,
            height=900,
            min_size=(1024, 720),
            background_color="#0f1419",
        )
        window.events.closed += stop_backend
        webview.start(gui="edgechromium", icon=icon)
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
