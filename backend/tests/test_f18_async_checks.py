from __future__ import annotations

import json
import threading
import time
from types import SimpleNamespace

from app.services.v2_generation_job_manager import V2GenerationJobManager
from app.services.v2_generation_pipeline import V2AsyncCheckResult


def wait_until(predicate, timeout: float = 2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.01)
    raise AssertionError("condition was not reached before timeout")


def make_character(character_id: int):
    return SimpleNamespace(
        id=character_id,
        character_tag=f"character_{character_id}",
        total_generation_attempts=0,
        prompt_variant_attempts=json.dumps({"initial": 1}),
        last_failure_reason=None,
    )


class FakeDb:
    def get(self, model, item_id):
        if model.__name__ == "GlobalCharacter":
            return make_character(item_id)
        return SimpleNamespace(
            quality_status="pass",
            quality_reasons="[]",
            identity_status="pass",
            identity_reasons="[]",
            is_provisional=True,
        )

    def close(self):
        pass


class FakeGenerationService:
    def __init__(self, _db):
        pass

    def naia_status(self):
        return {"ready": True}


class FakeAsyncPipeline:
    generated: list[int] = []
    check_gate = threading.Event()
    block_checks = False
    reject_first = False

    def __init__(self, _db):
        pass

    def prepare_async_character(self, character_id, **_kwargs):
        return SimpleNamespace(
            character_id=character_id,
            previous_status="not_generated",
            attempt_in_variant=0,
        )

    def wait_before_async_generation(self, **_kwargs):
        if self.generated:
            time.sleep(0.03)
        return True

    def generate_async_attempt(self, state, **_kwargs):
        state.attempt_in_variant += 1
        self.generated.append(state.character_id)
        return len(self.generated)

    def check_async_attempt(self, state, image_id):
        if self.block_checks:
            self.check_gate.wait(timeout=1.0)
        if self.reject_first and state.character_id == 1 and state.attempt_in_variant == 1:
            return V2AsyncCheckResult(state, None, True)
        result = SimpleNamespace(
            character_id=state.character_id,
            image_id=image_id,
            generation_status="generated",
            generation_attempts=state.attempt_in_variant,
        )
        return V2AsyncCheckResult(state, result, False)

    def cancel_async_character(self, _state):
        pass


def patch_dependencies(monkeypatch):
    from app.services import v2_generation_job_manager as module

    FakeAsyncPipeline.generated = []
    FakeAsyncPipeline.check_gate = threading.Event()
    FakeAsyncPipeline.block_checks = False
    FakeAsyncPipeline.reject_first = False
    monkeypatch.setattr(module, "SessionLocal", FakeDb)
    monkeypatch.setattr(module, "GenerationService", FakeGenerationService)
    monkeypatch.setattr(module, "V2GenerationPipeline", FakeAsyncPipeline)


def test_generation_continues_while_checks_run_and_job_waits_for_drain(monkeypatch):
    patch_dependencies(monkeypatch)
    FakeAsyncPipeline.block_checks = True
    manager = V2GenerationJobManager()
    monkeypatch.setattr(
        manager,
        "_target_characters",
        lambda _db, ids, _rerun: [make_character(item_id) for item_id in (ids or [])],
    )

    job = manager.start(character_ids=[1, 2], rerun=True)
    wait_until(lambda: manager.get_job(job.job_id).generated == 2)

    snapshot = manager.get_job(job.job_id)
    assert snapshot.status == "running"
    assert snapshot.checks_completed == 0
    assert FakeAsyncPipeline.generated == [1, 2]

    FakeAsyncPipeline.check_gate.set()
    wait_until(lambda: manager.get_job(job.job_id).status == "completed")
    snapshot = manager.get_job(job.job_id)
    assert snapshot.completed == 2
    assert snapshot.checks_completed == 2


def test_reject_regeneration_is_inserted_before_remaining_generation(monkeypatch):
    patch_dependencies(monkeypatch)
    FakeAsyncPipeline.reject_first = True
    manager = V2GenerationJobManager()
    monkeypatch.setattr(
        manager,
        "_target_characters",
        lambda _db, ids, _rerun: [make_character(item_id) for item_id in (ids or [])],
    )

    job = manager.start(character_ids=[1, 2, 3], rerun=True)
    wait_until(lambda: manager.get_job(job.job_id).status == "completed")

    assert FakeAsyncPipeline.generated[0] == 1
    assert FakeAsyncPipeline.generated.count(1) == 2
    assert FakeAsyncPipeline.generated.index(1, 1) < FakeAsyncPipeline.generated.index(3)
    assert sorted(FakeAsyncPipeline.generated) == [1, 1, 2, 3]
    snapshot = manager.get_job(job.job_id)
    assert snapshot.generated == 4
    assert snapshot.checks_completed == 4
    assert snapshot.completed == 3
