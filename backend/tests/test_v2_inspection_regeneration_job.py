from app.services.v2_generation_job_manager import V2GenerationJobManager


def test_inspection_regeneration_is_visible_and_cancellable() -> None:
    manager = V2GenerationJobManager()

    job = manager.start_inspection_regeneration(
        101,
        character_tag="test_character",
        max_attempts=2,
    )

    assert job is not None
    assert job.kind == "regenerate"
    assert job.status == "running"
    assert job.phase == "inspection_regeneration_generating"
    assert job.prompt_variant_attempts["inspection_regeneration"] == 1
    assert any(item.job_id == job.job_id for item in manager.list_visible_jobs(limit=20))

    assert manager.update_inspection_regeneration(
        job.job_id,
        phase="checking",
        current=1,
        generated=1,
        checks_completed=1,
        message="검사 중",
    )
    current = manager.get_job(job.job_id)
    assert current is not None
    assert current.phase == "inspection_regeneration_checking"
    assert current.current == 1
    assert current.generated == 1
    assert current.checks_completed == 1

    # Pending-inspection regenerations are driven by the bounded inspector loop, so
    # pause is intentionally unsupported while cancellation remains available.
    assert manager.pause(job.job_id) is False
    assert manager.cancel(job.job_id) is True
    assert manager.is_inspection_regeneration_cancelled(job.job_id) is True

    finished = manager.finish_inspection_regeneration(
        job.job_id,
        status="completed",
        message="완료",
    )
    assert finished is not None
    assert finished.status == "cancelled"
    assert finished.phase == "inspection_regeneration_cancelled"

    # Finishing releases the per-character regeneration lock.
    next_job = manager.start_inspection_regeneration(
        101,
        character_tag="test_character",
        max_attempts=2,
    )
    assert next_job is not None
