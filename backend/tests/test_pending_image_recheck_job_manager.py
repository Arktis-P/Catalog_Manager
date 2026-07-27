from __future__ import annotations

import json
from io import BytesIO

import pytest
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.database import Base
from app.models.global_character import GlobalCharacter
from app.models.global_character_image import GlobalCharacterImage
from app.models.global_character_review import GlobalCharacterReview
from app.models.setting import Setting
from app.routers import generation as generation_router
from app.schemas.generation import PendingImageRecheckStartRequest
from app.services.identity_checker import IdentityCheckResult
from app.services.pending_image_recheck_job_manager import (
    PendingImageRecheckJobManager,
    PendingImageRecheckJobState,
)


@pytest.fixture()
def db() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


@pytest.fixture(autouse=True)
def output_paths(tmp_path, monkeypatch):
    from app import config

    monkeypatch.setattr(config.settings, "project_root", tmp_path)
    monkeypatch.setattr(config.settings, "output_dir", tmp_path / "output")


def _png_bytes() -> bytes:
    output = BytesIO()
    Image.new("RGB", (8, 8), "white").save(output, format="PNG")
    return output.getvalue()


def _character(db: Session, tag: str) -> GlobalCharacter:
    character = GlobalCharacter(
        character_tag=tag,
        display_name=tag,
        post_count=100,
        gender="1girl",
        primary_hair_color="black_hair",
        base_prompt=f"1.2::{tag.replace('_', ' ')}::, black hair",
    )
    db.add(character)
    db.commit()
    db.refresh(character)
    return character


def _image(db: Session, character: GlobalCharacter, rel_path: str) -> GlobalCharacterImage:
    image = GlobalCharacterImage(
        global_character_id=character.id,
        image_path=rel_path,
        quality_status="pass",
        identity_status="old",
        identity_reasons=json.dumps(["old_reason"]),
        is_cover=True,
    )
    db.add(image)
    db.commit()
    db.refresh(image)
    return image


def test_preview_counts_only_non_completed_review_images(db: Session, tmp_path) -> None:
    pending_character = _character(db, "pending_character")
    completed_character = _character(db, "completed_character")
    no_review_character = _character(db, "no_review_character")
    rejected_character = _character(db, "rejected_character")
    _image(db, pending_character, "pending.png")
    _image(db, completed_character, "completed.png")
    _image(db, no_review_character, "no_review.png")
    rejected_image = _image(db, rejected_character, "rejected.png")
    rejected_image.is_rejected = True
    db.add_all(
        [
            GlobalCharacterReview(
                global_character_id=pending_character.id,
                review_status="pending",
                rating=3,
            ),
            GlobalCharacterReview(
                global_character_id=completed_character.id,
                review_status="completed",
                rating=5,
            ),
        ]
    )
    db.commit()

    preview = PendingImageRecheckJobManager().preview(
        db, batch_size=250, tagger_failures_only=False
    )

    assert preview.eligible_images == 2
    assert preview.excluded_completed == 1
    assert preview.missing_files == 2
    assert preview.batch_size == 250
    assert preview.tagger_failures_only is False


def test_preview_defaults_to_tagger_failure_images(db: Session, tmp_path) -> None:
    pending_character = _character(db, "pending_character")
    ok_character = _character(db, "ok_character")
    failed = _image(db, pending_character, "failed.png")
    failed.identity_reasons = json.dumps(["tagger_error"])
    ok = _image(db, ok_character, "ok.png")
    ok.identity_reasons = json.dumps(["character_tag_confident"])
    db.add_all(
        [
            GlobalCharacterReview(
                global_character_id=pending_character.id,
                review_status="pending",
                rating=3,
            ),
            GlobalCharacterReview(
                global_character_id=ok_character.id,
                review_status="pending",
                rating=4,
            ),
        ]
    )
    db.commit()

    preview = PendingImageRecheckJobManager().preview(db, batch_size=100)
    assert preview.eligible_images == 1
    assert preview.tagger_failures_only is True
    assert preview.first_image_id == failed.id


def test_recheck_updates_only_identity_fields_and_skips_missing_files(
    db: Session, tmp_path, monkeypatch
) -> None:
    existing_path = tmp_path / "output" / "generated_images" / "pending_review" / "one.png"
    failing_path = tmp_path / "output" / "generated_images" / "pending_review" / "two.png"
    existing_path.parent.mkdir(parents=True)
    existing_path.write_bytes(_png_bytes())
    failing_path.write_bytes(_png_bytes())
    rel_path = existing_path.relative_to(tmp_path).as_posix()
    failing_rel_path = failing_path.relative_to(tmp_path).as_posix()
    character = _character(db, "hakurei_reimu")
    character.total_generation_attempts = 7
    completed_character = _character(db, "completed_character")
    failing_character = _character(db, "failing_character")
    image = _image(db, character, rel_path)
    missing = _image(db, character, "output/generated_images/pending_review/missing.png")
    completed_image = _image(db, completed_character, rel_path)
    failed_image = _image(db, failing_character, failing_rel_path)
    rejected_image = _image(db, character, rel_path)
    rejected_image.is_rejected = True
    review = GlobalCharacterReview(
        global_character_id=character.id,
        cover_image_id=image.id,
        rating=4,
        final_prompt="do not change",
        review_status="pending",
    )
    db.add_all(
        [
            review,
            GlobalCharacterReview(
                global_character_id=completed_character.id,
                review_status="completed",
                rating=5,
            ),
            GlobalCharacterReview(
                global_character_id=failing_character.id,
                review_status="pending",
                rating=2,
            ),
            Setting(key="hf_token", value="fake-token"),
        ]
    )
    db.commit()

    def fake_identity(*args, **kwargs):
        if kwargs["character_tag"] == "failing_character":
            raise RuntimeError("tagger exploded")
        return IdentityCheckResult(
            status="pass",
            character_confidence=0.91,
            hair_color_confidence=0.82,
            conflicting_character_tag=None,
            conflicting_character_confidence=None,
            reasons=["character_tag_confident"],
            suggested_multicolor_tags=["streaked_hair"],
        )

    monkeypatch.setattr(
        "app.services.pending_image_recheck_job_manager.check_identity",
        fake_identity,
    )
    monkeypatch.setattr(
        "app.services.pending_image_recheck_job_manager.is_local_wd_model_installed",
        lambda *args, **kwargs: True,
    )
    monkeypatch.setattr(
        "app.services.pending_image_recheck_job_manager.SessionLocal",
        lambda: db,
    )
    manager = PendingImageRecheckJobManager()
    job = PendingImageRecheckJobState(
        job_id="job-1", batch_size=100, tagger_failures_only=False
    )
    manager._jobs[job.job_id] = job
    manager._active_job_id = job.job_id
    image_id = image.id
    missing_id = missing.id
    completed_image_id = completed_image.id
    failed_image_id = failed_image.id
    rejected_image_id = rejected_image.id
    character_id = character.id
    review_id = review.id

    manager._run(job.job_id)

    image = db.get(GlobalCharacterImage, image_id)
    missing = db.get(GlobalCharacterImage, missing_id)
    completed_image = db.get(GlobalCharacterImage, completed_image_id)
    failed_image = db.get(GlobalCharacterImage, failed_image_id)
    rejected_image = db.get(GlobalCharacterImage, rejected_image_id)
    character = db.get(GlobalCharacter, character_id)
    review = db.get(GlobalCharacterReview, review_id)
    finished = manager.get_job(job.job_id)
    assert finished.status == "completed"
    assert finished.completed == 1
    assert finished.succeeded == 1
    assert finished.warnings == 0
    assert finished.rejected == 0
    assert finished.failed == 1
    assert finished.skipped == 1
    assert image.identity_status == "pass"
    assert json.loads(image.identity_reasons) == ["character_tag_confident"]
    assert json.loads(image.suggested_multicolor_tags) == ["streaked_hair"]
    assert image.character_confidence == 0.91
    assert image.quality_status == "pass"
    assert image.is_cover is True
    assert missing.identity_status == "old"
    assert completed_image.identity_status == "old"
    assert failed_image.identity_status == "old"
    assert rejected_image.identity_status == "old"
    assert character.total_generation_attempts == 7
    assert review.rating == 4
    assert review.cover_image_id == image.id
    assert review.final_prompt == "do not change"


def test_recheck_fails_fast_when_local_model_is_missing(
    db: Session, tmp_path, monkeypatch
) -> None:
    from app.integrations.image_tagger.hf_wd_tagger import TAGGER_MODEL_UNAVAILABLE

    existing_path = tmp_path / "output" / "generated_images" / "pending_review" / "one.png"
    existing_path.parent.mkdir(parents=True)
    existing_path.write_bytes(_png_bytes())
    rel_path = existing_path.relative_to(tmp_path).as_posix()
    character = _character(db, "hakurei_reimu")
    image = _image(db, character, rel_path)
    db.add_all(
        [
            GlobalCharacterReview(
                global_character_id=character.id,
                review_status="pending",
                rating=3,
            ),
        ]
    )
    db.commit()

    def fail_if_called(*args, **kwargs):
        raise AssertionError("identity check should not run after fatal preflight")

    monkeypatch.setattr(
        "app.services.pending_image_recheck_job_manager.check_identity",
        fail_if_called,
    )
    monkeypatch.setattr(
        "app.services.pending_image_recheck_job_manager.is_local_wd_model_installed",
        lambda *args, **kwargs: False,
    )
    monkeypatch.setattr(
        "app.services.pending_image_recheck_job_manager.SessionLocal",
        lambda: db,
    )
    manager = PendingImageRecheckJobManager()
    job = PendingImageRecheckJobState(
        job_id="job-fast-fail", batch_size=100, tagger_failures_only=False
    )
    manager._jobs[job.job_id] = job
    manager._active_job_id = job.job_id
    image_id = image.id

    manager._run(job.job_id)

    finished = manager.get_job(job.job_id)
    image = db.get(GlobalCharacterImage, image_id)
    assert finished.status == "failed"
    assert finished.identity_reasons == [TAGGER_MODEL_UNAVAILABLE]
    assert finished.completed == 0
    assert image.identity_status == "old"


def test_recheck_fails_fast_when_local_model_becomes_unavailable(
    db: Session, tmp_path, monkeypatch
) -> None:
    from app.integrations.image_tagger.hf_wd_tagger import TAGGER_MODEL_UNAVAILABLE

    existing_path = tmp_path / "output" / "generated_images" / "pending_review" / "one.png"
    existing_path.parent.mkdir(parents=True)
    existing_path.write_bytes(_png_bytes())
    rel_path = existing_path.relative_to(tmp_path).as_posix()
    character = _character(db, "hakurei_reimu")
    image = _image(db, character, rel_path)
    image.identity_reasons = json.dumps(["tagger_error"])
    db.add(
        GlobalCharacterReview(
            global_character_id=character.id,
            review_status="pending",
            rating=3,
        )
    )
    db.commit()

    monkeypatch.setattr(
        "app.services.pending_image_recheck_job_manager.is_local_wd_model_installed",
        lambda *args, **kwargs: True,
    )
    monkeypatch.setattr(
        "app.services.pending_image_recheck_job_manager.check_identity",
        lambda *args, **kwargs: IdentityCheckResult(
            status="warning",
            character_confidence=None,
            hair_color_confidence=None,
            conflicting_character_tag=None,
            conflicting_character_confidence=None,
            reasons=[TAGGER_MODEL_UNAVAILABLE],
            suggested_multicolor_tags=[],
        ),
    )
    monkeypatch.setattr(
        "app.services.pending_image_recheck_job_manager.SessionLocal",
        lambda: db,
    )
    manager = PendingImageRecheckJobManager()
    job = PendingImageRecheckJobState(job_id="job-model-gone", batch_size=100)
    manager._jobs[job.job_id] = job
    manager._active_job_id = job.job_id
    image_id = image.id

    manager._run(job.job_id)

    finished = manager.get_job(job.job_id)
    image = db.get(GlobalCharacterImage, image_id)
    assert finished.status == "failed"
    assert finished.identity_reasons == [TAGGER_MODEL_UNAVAILABLE]
    assert finished.completed == 0
    assert image.identity_status == "old"


def test_pending_recheck_router_preview_start_status_cancel(db: Session, monkeypatch) -> None:
    manager = PendingImageRecheckJobManager()
    job = PendingImageRecheckJobState(job_id="job-api", batch_size=100)

    monkeypatch.setattr(generation_router, "pending_image_recheck_job_manager", manager)
    monkeypatch.setattr(
        manager,
        "start",
        lambda *, batch_size, tagger_failures_only=True: job,
    )

    preview = generation_router.preview_pending_image_recheck(
        batch_size=100, tagger_failures_only=True, db=db
    )
    assert preview.eligible_images == 0
    assert preview.batch_size == 100
    assert preview.tagger_failures_only is True

    started = generation_router.start_pending_image_recheck(
        PendingImageRecheckStartRequest(batch_size=100)
    )
    assert started.job_id == "job-api"

    manager._jobs[job.job_id] = job
    manager._active_job_id = job.job_id
    status = generation_router.get_pending_image_recheck_status()
    assert status.job_id == "job-api"

    cancelled = generation_router.cancel_pending_image_recheck_job(job.job_id)
    assert cancelled.status == "cancelled"


def test_pending_recheck_router_rejects_duplicate(monkeypatch) -> None:
    manager = PendingImageRecheckJobManager()
    monkeypatch.setattr(generation_router, "pending_image_recheck_job_manager", manager)
    monkeypatch.setattr(
        manager,
        "start",
        lambda *, batch_size, tagger_failures_only=True: None,
    )

    with pytest.raises(generation_router.HTTPException) as exc_info:
        generation_router.start_pending_image_recheck(
            PendingImageRecheckStartRequest(batch_size=100)
        )

    assert exc_info.value.status_code == 409


def test_wd_tagger_model_router_status_download_cancel(monkeypatch) -> None:
    from app.integrations.image_tagger.local_wd_tagger import LocalWdModelStatus
    from app.schemas.generation import WdTaggerModelDownloadRequest

    class FakeModelManager:
        def __init__(self) -> None:
            self.cancelled = False

        def status(self, repo_id):
            return LocalWdModelStatus(
                repo_id=repo_id,
                cache_dir="data/models/wd-tagger/repo",
                installed=False,
                downloading=False,
            )

        def start_download(self, repo_id):
            return LocalWdModelStatus(
                repo_id=repo_id,
                cache_dir="data/models/wd-tagger/repo",
                installed=False,
                downloading=True,
                current_file="model.onnx",
            )

        def cancel_download(self, repo_id):
            self.cancelled = True
            return True

    fake_manager = FakeModelManager()
    monkeypatch.setattr(generation_router, "local_wd_model_manager", fake_manager)

    status = generation_router.get_wd_tagger_model_status()
    assert status.installed is False

    started = generation_router.start_wd_tagger_model_download(WdTaggerModelDownloadRequest())
    assert started.downloading is True
    assert started.current_file == "model.onnx"

    cancelled = generation_router.cancel_wd_tagger_model_download(WdTaggerModelDownloadRequest())
    assert fake_manager.cancelled is True
    assert cancelled.repo_id
