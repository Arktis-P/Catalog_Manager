from __future__ import annotations

import threading
import time
from types import SimpleNamespace

from app.services.relevance_collect_job_manager import RelevanceCollectJobManager
from app.services.v2_generation_job_manager import V2GenerationJobManager


def wait_until(predicate, timeout: float = 2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.01)
    raise AssertionError("condition was not reached before timeout")


def test_relevance_collect_respects_runtime_concurrency(monkeypatch):
    manager = RelevanceCollectJobManager()
    monkeypatch.setattr(manager, "_get_max_concurrent", lambda: 2)

    state_lock = threading.Lock()
    active = 0
    max_active = 0

    def run_one(job_id: str, character_id: int):
        nonlocal active, max_active
        with state_lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.05)
        with state_lock:
            active -= 1
        return character_id, f"character_{character_id}", None

    monkeypatch.setattr(manager, "_run_one", run_one)

    job = manager.start([1, 2, 3, 4])
    completed = wait_until(lambda: manager.get_job(job.job_id).status == "completed")

    assert completed is True
    snapshot = manager.get_job(job.job_id)
    assert snapshot.current == 4
    assert snapshot.success_count == 4
    assert max_active == 2


def test_relevance_collect_pause_resume_and_cancel_paused(monkeypatch):
    manager = RelevanceCollectJobManager()
    monkeypatch.setattr(manager, "_get_max_concurrent", lambda: 1)

    started: list[int] = []
    first_started = threading.Event()

    def run_one(job_id: str, character_id: int):
        started.append(character_id)
        if character_id == 1:
            first_started.set()
        time.sleep(0.05)
        return character_id, f"character_{character_id}", None

    monkeypatch.setattr(manager, "_run_one", run_one)

    job = manager.start([1, 2])
    first_started.wait(timeout=1.0)
    wait_until(lambda: manager.get_job(job.job_id).status == "running")

    assert manager.pause(job.job_id) is True
    wait_until(lambda: manager.get_job(job.job_id).status == "paused")
    snapshot = manager.get_job(job.job_id)
    assert snapshot.current == 1
    assert started == [1]

    assert manager.resume(job.job_id) is True
    wait_until(lambda: manager.get_job(job.job_id).status == "completed")
    assert started == [1, 2]

    second = manager.start([3, 4])
    wait_until(lambda: manager.get_job(second.job_id).status == "running")
    assert manager.pause(second.job_id) is True
    wait_until(lambda: manager.get_job(second.job_id).status == "paused")
    assert manager.cancel(second.job_id) is True
    wait_until(lambda: manager.get_job(second.job_id).status == "cancelled")


class FakeDb:
    def close(self) -> None:
        pass

    def get(self, *_args, **_kwargs):
        return None


class FakeGenerationService:
    def __init__(self, _db):
        pass

    def naia_status(self):
        return {"ready": True}


class FakePipeline:
    started: list[int] = []
    first_started = threading.Event()

    def __init__(self, _db):
        pass

    def run_character(self, character_id: int, **_kwargs):
        self.started.append(character_id)
        if character_id == 1:
            self.first_started.set()
        time.sleep(0.05)
        return SimpleNamespace(
            image_id=None,
            generation_status="generated",
            generation_attempts=1,
        )


def make_v2_character(character_id: int):
    return SimpleNamespace(
        id=character_id,
        character_tag=f"character_{character_id}",
        total_generation_attempts=0,
        prompt_variant_attempts="{}",
        last_failure_reason=None,
    )


def patch_v2_dependencies(monkeypatch):
    from app.services import v2_generation_job_manager as module

    FakePipeline.started = []
    FakePipeline.first_started = threading.Event()
    monkeypatch.setattr(module, "SessionLocal", lambda: FakeDb())
    monkeypatch.setattr(module, "GenerationService", FakeGenerationService)
    monkeypatch.setattr(module, "V2GenerationPipeline", FakePipeline)


def test_v2_generation_pause_and_resume(monkeypatch):
    patch_v2_dependencies(monkeypatch)
    manager = V2GenerationJobManager()
    monkeypatch.setattr(
        manager,
        "_target_characters",
        lambda _db, _ids, _rerun: [make_v2_character(1), make_v2_character(2)],
    )

    job = manager.start(character_ids=[1, 2], rerun=True)
    FakePipeline.first_started.wait(timeout=1.0)
    wait_until(lambda: manager.get_job(job.job_id).status == "running")

    assert manager.pause(job.job_id) is True
    wait_until(lambda: manager.get_job(job.job_id).status == "paused")
    assert manager.get_job(job.job_id).current == 1
    assert FakePipeline.started == [1]

    assert manager.resume(job.job_id) is True
    wait_until(lambda: manager.get_job(job.job_id).status == "completed")
    assert FakePipeline.started == [1, 2]


def test_v2_generation_cancel_while_paused(monkeypatch):
    patch_v2_dependencies(monkeypatch)
    manager = V2GenerationJobManager()
    monkeypatch.setattr(
        manager,
        "_target_characters",
        lambda _db, _ids, _rerun: [make_v2_character(1), make_v2_character(2)],
    )

    job = manager.start(character_ids=[1, 2], rerun=True)
    FakePipeline.first_started.wait(timeout=1.0)
    wait_until(lambda: manager.get_job(job.job_id).status == "running")

    assert manager.pause(job.job_id) is True
    wait_until(lambda: manager.get_job(job.job_id).status == "paused")
    assert manager.cancel(job.job_id) is True
    wait_until(lambda: manager.get_job(job.job_id).status == "cancelled")
    assert FakePipeline.started == [1]


def test_v2_regeneration_preempts_running_generation_and_auto_resumes(monkeypatch):
    patch_v2_dependencies(monkeypatch)
    manager = V2GenerationJobManager()
    characters_by_id = {
        1: make_v2_character(1),
        2: make_v2_character(2),
        9: make_v2_character(9),
    }
    monkeypatch.setattr(
        manager,
        "_target_characters",
        lambda _db, ids, _rerun: [characters_by_id[item_id] for item_id in (ids or [])],
    )

    generation = manager.start(character_ids=[1, 2], rerun=True)
    FakePipeline.first_started.wait(timeout=1.0)
    wait_until(lambda: manager.get_job(generation.job_id).status == "running")

    regeneration = manager.start_regeneration(9, base_prompt="edited", character_tag="character_9")

    assert regeneration is not None
    wait_until(lambda: manager.get_job(generation.job_id).status == "paused")
    assert "자동" in manager.get_job(generation.job_id).message
    wait_until(lambda: manager.get_job(regeneration.job_id).status == "completed")
    wait_until(lambda: manager.get_job(generation.job_id).status == "completed")

    assert FakePipeline.started == [1, 9, 2]
    assert manager.get_job(regeneration.job_id).kind == "regenerate"
    assert manager.get_job(regeneration.job_id).character_tag == "character_9"
