import io
import json
import urllib.error
from unittest.mock import Mock

import pytest

from desktop import launcher


class FakeResponse(io.BytesIO):
    def __init__(self, payload: dict, status: int = 200) -> None:
        super().__init__(json.dumps(payload).encode("utf-8"))
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


@pytest.fixture(autouse=True)
def restore_backend_process():
    original = launcher._backend_process
    yield
    launcher._backend_process = original


def _run_single_health_check(monkeypatch, payload: dict, process: Mock | None = None) -> bool:
    launcher._backend_process = process or Mock(poll=Mock(return_value=None))
    ticks = iter([0.0, 0.0, 2.0])
    monkeypatch.setattr(launcher.time, "time", lambda: next(ticks))
    monkeypatch.setattr(launcher.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        launcher.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: FakeResponse(payload),
    )
    return launcher.wait_for_server("http://127.0.0.1:8000/api/health", timeout_seconds=1)


def test_wait_for_server_rejects_non_gui_health(monkeypatch) -> None:
    assert not _run_single_health_check(
        monkeypatch,
        {"status": "ok", "serve_gui": False, "gui_ready": True},
    )


def test_wait_for_server_rejects_gui_not_ready(monkeypatch) -> None:
    assert not _run_single_health_check(
        monkeypatch,
        {"status": "ok", "serve_gui": True, "gui_ready": False},
    )


def test_wait_for_server_accepts_ready_gui_health(monkeypatch) -> None:
    assert _run_single_health_check(
        monkeypatch,
        {"status": "ok", "serve_gui": True, "gui_ready": True},
    )


def test_wait_for_server_rejects_health_when_owned_process_exits(monkeypatch) -> None:
    process = Mock()
    process.poll.side_effect = [None, 10048]

    assert not _run_single_health_check(
        monkeypatch,
        {"status": "ok", "serve_gui": True, "gui_ready": True},
        process,
    )


@pytest.mark.parametrize(
    "failure",
    ["invalid-json", "network-error"],
)
def test_wait_for_server_handles_invalid_response(monkeypatch, failure: str) -> None:
    launcher._backend_process = Mock(poll=Mock(return_value=None))
    ticks = iter([0.0, 0.0, 2.0])
    monkeypatch.setattr(launcher.time, "time", lambda: next(ticks))
    monkeypatch.setattr(launcher.time, "sleep", lambda _seconds: None)

    def open_url(*_args, **_kwargs):
        if failure == "network-error":
            raise urllib.error.URLError("connection refused")
        response = FakeResponse({})
        response.seek(0)
        response.truncate(0)
        response.write(b"not-json")
        response.seek(0)
        return response

    monkeypatch.setattr(launcher.urllib.request, "urlopen", open_url)

    assert not launcher.wait_for_server(
        "http://127.0.0.1:8000/api/health", timeout_seconds=1
    )


def test_release_listening_port_kills_process_tree_and_waits(monkeypatch) -> None:
    monkeypatch.setattr(launcher.sys, "platform", "win32")
    monkeypatch.setattr(launcher, "_listening_pids", Mock(side_effect=[{4321}, set()]))
    monkeypatch.setattr(launcher.time, "time", Mock(side_effect=[0.0, 0.0]))
    monkeypatch.setattr(launcher.time, "sleep", lambda _seconds: None)
    kill = Mock(return_value=Mock(returncode=0))
    monkeypatch.setattr(launcher, "_kill_process_tree", kill)

    launcher.release_listening_port(8000, timeout_seconds=1)

    kill.assert_called_once_with(4321)
    assert launcher._listening_pids.call_count == 2


def test_release_listening_port_kills_orphan_child_when_owner_is_gone(
    monkeypatch,
) -> None:
    monkeypatch.setattr(launcher.sys, "platform", "win32")
    monkeypatch.setattr(launcher, "_listening_pids", Mock(side_effect=[{38444}, set()]))
    children = Mock(return_value={46012})
    monkeypatch.setattr(launcher, "_child_process_pids", children)
    monkeypatch.setattr(launcher.time, "time", Mock(side_effect=[0.0, 0.0]))
    monkeypatch.setattr(launcher.time, "sleep", lambda _seconds: None)

    def kill(pid: int):
        return Mock(returncode=1 if pid == 38444 else 0)

    kill_tree = Mock(side_effect=kill)
    monkeypatch.setattr(launcher, "_kill_process_tree", kill_tree)

    launcher.release_listening_port(8000, timeout_seconds=1)

    children.assert_called_once_with(38444)
    assert [call.args[0] for call in kill_tree.call_args_list] == [38444, 46012]
