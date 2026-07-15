from __future__ import annotations

import re
import uuid
from datetime import datetime
from pathlib import Path

from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.config import settings
from app.integrations.danbooru.appearance_extractor import normalize_gender
from app.integrations.naia.client import NaiaClient, NaiaClientError
from app.integrations.naia.generation_runner import (
    generate_and_fetch_image,
    wait_between_naia_generations,
)
from app.integrations.naia.wildcard_writer import write_character_wildcard
from app.models.character import Character
from app.models.generation_job import GenerationJob
from app.models.global_character import GlobalCharacter
from app.models.global_character_generation_job import GlobalCharacterGenerationJob
from app.models.global_character_image import GlobalCharacterImage
from app.models.global_character_review import GlobalCharacterReview
from app.models.image import Image
from app.models.review import Review
from app.models.series import Series
from app.services.generation_prompt_builder import (
    GenerationPromptConfig,
    build_character_core,
    build_full_prompt,
    build_prompt_from_character_core,
    build_queue_manifest,
    export_queue_manifest,
)
from app.services.image_auto_checker import check_generated_image
from app.services.settings_service import SettingsService

def _safe_filename_tag(character_tag: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_\-]+", "_", character_tag.strip().lower())
    slug = re.sub(r"_+", "_", slug).strip("_")
    return slug or "character"


class GenerationService:
    def __init__(self, db: Session):
        self.db = db
        self._settings = SettingsService(db)

    def get_naia_base_url(self) -> str:
        return self._settings.get_naia_base_url()

    def get_naia_portable_dir(self) -> Path:
        return Path(self._settings.get_naia_portable_dir())

    def get_wildcards_dir(self) -> Path:
        return self.get_naia_portable_dir() / "user-data" / "wildcards"

    def get_pending_images_dir(self) -> Path:
        return settings.output_dir / "generated_images" / "pending_review"

    def get_images_per_character(self) -> int:
        return self._settings.get_generation_images_per_character()

    def naia_status(self) -> dict[str, object]:
        base_url = self.get_naia_base_url()
        portable_dir = self.get_naia_portable_dir()
        wildcards_dir = self.get_wildcards_dir()
        result: dict[str, object] = {
            "configured": portable_dir.exists(),
            "base_url": base_url,
            "portable_dir": str(portable_dir),
            "wildcards_dir": str(wildcards_dir),
            "ready": False,
            "message": "",
        }
        if not portable_dir.exists():
            result["message"] = f"NAIA Portable 경로를 찾을 수 없습니다: {portable_dir}"
            return result
        try:
            payload = NaiaClient(base_url).check_health()
            result["ready"] = True
            result["message"] = "NAIA 연결됨"
            result["api_mode"] = payload.get("api_mode")
            result["is_generating"] = payload.get("is_generating")
        except NaiaClientError as exc:
            result["message"] = str(exc)
        return result

    def list_generation_candidates(
        self,
        series_id: int,
        *,
        require_confirmed: bool = True,
        exclude_needs_check: bool = True,
        needs_check_only: bool = False,
        search: str | None = None,
    ) -> list[Character]:
        query = (
            self.db.query(Character)
            .filter(Character.series_id == series_id)
            .filter(Character.generation_prompt.isnot(None))
            .filter(Character.generation_prompt != "")
        )
        if needs_check_only:
            query = query.filter(Character.status == "needs_check")
        elif exclude_needs_check:
            query = query.filter(Character.status != "needs_check")
        if require_confirmed:
            query = query.filter(Character.appearance_confirmed.is_(True))
        if search:
            pattern = f"%{search.strip()}%"
            query = query.filter(
                (Character.character_tag.ilike(pattern)) | (Character.display_name.ilike(pattern))
            )
        return query.order_by(Character.post_count.desc(), Character.character_tag.asc()).all()

    def get_candidate_stats(self, series_id: int) -> dict[str, int]:
        base = self.db.query(Character).filter(Character.series_id == series_id)
        total = base.count()
        with_prompt = base.filter(
            Character.generation_prompt.isnot(None),
            Character.generation_prompt != "",
        ).count()
        confirmed_with_prompt = base.filter(
            Character.generation_prompt.isnot(None),
            Character.generation_prompt != "",
            Character.appearance_confirmed.is_(True),
        ).count()
        needs_check_with_prompt = base.filter(
            Character.generation_prompt.isnot(None),
            Character.generation_prompt != "",
            Character.status == "needs_check",
        ).count()
        return {
            "total_characters": total,
            "with_prompt": with_prompt,
            "confirmed_with_prompt": confirmed_with_prompt,
            "unconfirmed_with_prompt": max(0, with_prompt - confirmed_with_prompt),
            "needs_check_with_prompt": needs_check_with_prompt,
        }

    def _raise_no_eligible_error(
        self,
        skipped: list[dict[str, object]],
        *,
        require_confirmed: bool,
    ) -> None:
        unconfirmed = sum(1 for item in skipped if item.get("reason") == "외형 미확정")
        no_prompt = sum(1 for item in skipped if item.get("reason") == "generation_prompt 없음")
        if require_confirmed and unconfirmed > 0 and no_prompt == 0:
            raise ValueError(
                "생성 가능한 캐릭터가 없습니다. "
                f"generation_prompt는 {unconfirmed}명 있으나 외형 태그 Confirm이 되지 않았습니다. "
                "Review 탭에서 Confirm하거나, Generation 화면의 "
                "'외형 태그 확정된 캐릭터만 포함' 체크를 해제하세요."
            )
        if no_prompt > 0 and unconfirmed == 0:
            raise ValueError(
                "생성 가능한 캐릭터가 없습니다. "
                f"generation_prompt가 없는 캐릭터 {no_prompt}명입니다. "
                "외형 태그 추출을 먼저 실행하세요."
            )
        raise ValueError(
            "생성 가능한 캐릭터가 없습니다. "
            f"(외형 미확정 {unconfirmed}명, generation_prompt 없음 {no_prompt}명)"
        )

    def get_prompt_config(self) -> GenerationPromptConfig:
        return self._settings.get_generation_prompt_config()

    def preview_prompt(
        self,
        character_id: int,
        *,
        prompt_level: int = 1,
        prompt_config: GenerationPromptConfig | None = None,
    ) -> dict[str, str | int]:
        character = self.db.query(Character).filter(Character.id == character_id).first()
        if not character:
            raise ValueError("Character not found")
        config = prompt_config or self.get_prompt_config()
        prompt, negative = build_full_prompt(
            character,
            prompt_level=prompt_level,
            prompt_config=config,
        )
        return {
            "character_id": character.id,
            "character_tag": character.character_tag,
            "prompt_level": prompt_level,
            "prompt": prompt,
            "negative_prompt": negative,
            "prompt_prefix": config.prefix,
            "prompt_suffix": config.suffix,
        }

    def prepare_queue(
        self,
        series_id: int,
        *,
        character_ids: list[int] | None,
        prompt_level: int,
        require_confirmed: bool = True,
        prompt_config: GenerationPromptConfig | None = None,
    ) -> dict[str, object]:
        series = self.db.query(Series).filter(Series.id == series_id).first()
        if not series:
            raise ValueError("Series not found")

        config = prompt_config or self.get_prompt_config()
        if character_ids:
            characters = (
                self.db.query(Character)
                .filter(Character.series_id == series_id, Character.id.in_(character_ids))
                .order_by(Character.post_count.desc(), Character.character_tag.asc())
                .all()
            )
        else:
            characters = self.list_generation_candidates(
                series_id,
                require_confirmed=require_confirmed,
            )

        eligible: list[Character] = []
        skipped: list[dict[str, object]] = []
        for character in characters:
            core = build_character_core(character, prompt_level)
            if not core:
                skipped.append(
                    {
                        "id": character.id,
                        "character_tag": character.character_tag,
                        "reason": "generation_prompt 없음",
                    }
                )
                continue
            if character.status == "needs_check":
                skipped.append(
                    {
                        "id": character.id,
                        "character_tag": character.character_tag,
                        "reason": character.needs_check_reason or "needs_check",
                    }
                )
                continue
            if require_confirmed and not character.appearance_confirmed:
                skipped.append(
                    {
                        "id": character.id,
                        "character_tag": character.character_tag,
                        "reason": "외형 미확정",
                    }
                )
                continue
            eligible.append(character)

        if not eligible:
            self._raise_no_eligible_error(skipped, require_confirmed=require_confirmed)

        queue_id = f"{series.series_tag}_{uuid.uuid4().hex[:8]}"
        wildcard_lines = [build_character_core(character, prompt_level) or "" for character in eligible]
        wildcard_path = write_character_wildcard(self.get_wildcards_dir(), queue_id, wildcard_lines)

        sample_prompt, negative_prompt = build_full_prompt(
            eligible[0],
            prompt_level=prompt_level,
            prompt_config=config,
            queue_id=queue_id,
            use_wildcard=True,
        )
        manifest = build_queue_manifest(
            queue_id=queue_id,
            series_tag=series.series_tag,
            series_id=series.id,
            prompt_level=prompt_level,
            wildcard_path=wildcard_path,
            characters=[
                {
                    "id": character.id,
                    "character_tag": character.character_tag,
                    "display_name": character.display_name,
                    "generation_prompt": character.generation_prompt,
                    "character_core": build_character_core(character, prompt_level),
                }
                for character in eligible
            ],
            prompt_template=sample_prompt,
            negative_prompt=negative_prompt,
            prompt_prefix=config.prefix,
            prompt_suffix=config.suffix,
        )
        manifest_path = export_queue_manifest(
            settings.output_dir / "naia_queues" / f"{queue_id}.json",
            manifest,
        )

        return {
            "queue_id": queue_id,
            "series_id": series.id,
            "series_tag": series.series_tag,
            "prompt_level": prompt_level,
            "character_count": len(eligible),
            "skipped": skipped,
            "wildcard_path": str(wildcard_path),
            "manifest_path": str(manifest_path),
            "prompt_template": sample_prompt,
            "negative_prompt": negative_prompt,
            "prompt_prefix": config.prefix,
            "prompt_suffix": config.suffix,
            "characters": manifest["characters"],
        }

    def create_generation_jobs(
        self,
        queue_payload: dict[str, object],
        *,
        images_per_character: int,
    ) -> list[GenerationJob]:
        jobs: list[GenerationJob] = []
        prompt_level = int(queue_payload.get("prompt_level") or 1)
        stored = self.get_prompt_config()
        config = GenerationPromptConfig(
            prefix=str(queue_payload.get("prompt_prefix") or stored.prefix),
            suffix=str(queue_payload.get("prompt_suffix") or stored.suffix),
            negative_prompt=str(queue_payload.get("negative_prompt") or stored.negative_prompt),
        )
        negative_prompt = config.negative_prompt
        characters = queue_payload.get("characters")
        if not isinstance(characters, list):
            return jobs

        for item in characters:
            if not isinstance(item, dict):
                continue
            character_id = item.get("id")
            if not isinstance(character_id, int):
                continue
            character = self.db.query(Character).filter(Character.id == character_id).first()
            if not character:
                continue
            prompt, _ = build_full_prompt(
                character,
                prompt_level=prompt_level,
                prompt_config=config,
            )
            for _ in range(images_per_character):
                job = GenerationJob(
                    character_id=character.id,
                    prompt_level=prompt_level,
                    prompt=prompt,
                    negative_prompt=negative_prompt,
                    count=1,
                    status="pending",
                )
                self.db.add(job)
                jobs.append(job)
        self.db.commit()
        for job in jobs:
            self.db.refresh(job)
        return jobs

    def import_generated_image(
        self,
        *,
        character: Character,
        generation_job: GenerationJob,
        image_bytes: bytes,
        created_at: datetime | None = None,
        skip_checks: bool = False,
    ) -> Image:
        pending_dir = self.get_pending_images_dir()
        pending_dir.mkdir(parents=True, exist_ok=True)
        timestamp = (created_at or datetime.now()).strftime("%Y%m%d_%H%M%S")
        filename = f"{timestamp}_{_safe_filename_tag(character.character_tag)}.png"
        output_path = pending_dir / filename
        counter = 1
        while output_path.exists():
            output_path = pending_dir / f"{timestamp}_{_safe_filename_tag(character.character_tag)}_{counter}.png"
            counter += 1
        output_path.write_bytes(image_bytes)

        rel_path = output_path.relative_to(settings.project_root).as_posix()
        if skip_checks:
            check = None
        else:
            series = self.db.query(Series).filter(Series.id == character.series_id).first()
            check = check_generated_image(
                output_path,
                character=character,
                series=series,
                hf_token=self._settings.get_hf_token() or None,
                hf_wd_model=self._settings.get_hf_wd_model() or None,
            )
        image = Image(
            character_id=character.id,
            generation_job_id=generation_job.id,
            image_path=rel_path,
            auto_tags=check.auto_tags if check else None,
            auto_status=check.auto_status if check else None,
            hair_match=check.hair_match if check else None,
            eye_match=check.eye_match if check else None,
            gender_pred=check.gender_pred if check else None,
            cover_score=check.cover_score if check else None,
        )
        generation_job.status = "completed"
        generation_job.output_path = rel_path
        character.status = "generated"
        self.db.add(image)
        self.db.commit()
        self.db.refresh(image)
        return image

    def mark_job_failed(self, generation_job: GenerationJob, error: str) -> None:
        generation_job.status = "failed"
        self.db.commit()

    @staticmethod
    def suggest_prompt_level(character: Character) -> int:
        """캐릭터 인지도·태그 풍부도 기반 추천 레벨 (1~3)."""
        if character.post_count >= 1000:
            return 1
        if character.post_count >= 300:
            return 2
        tag_count = (
            len([t for t in (character.hair_color or "").split(",") if t.strip()])
            + len([t for t in (character.eye_color or "").split(",") if t.strip()])
            + len([t for t in (character.feature_tags or "").split(",") if t.strip()])
            + (1 if character.multi_color_hair else 0)
        )
        if tag_count >= 4:
            return 3
        if tag_count >= 2:
            return 2
        return 1

    def suggest_batch_level(
        self,
        *,
        series_id: int,
        character_ids: list[int] | None = None,
    ) -> dict[str, object]:
        """배치 캐릭터들의 추천 레벨 (최댓값 + 분포 반환)."""
        if character_ids:
            characters = (
                self.db.query(Character)
                .filter(Character.series_id == series_id, Character.id.in_(character_ids))
                .all()
            )
        else:
            characters = self.list_generation_candidates(series_id)
        if not characters:
            return {"suggested_level": 1, "breakdown": {}}
        breakdown: dict[int, int] = {}
        for char in characters:
            lv = self.suggest_prompt_level(char)
            breakdown[lv] = breakdown.get(lv, 0) + 1
        suggested = max(breakdown.keys())
        return {"suggested_level": suggested, "breakdown": breakdown}

    def auto_select_cover(self, character_id: int, images: list[Image]) -> Image | None:
        """생성된 이미지 중 최고 cover_score 이미지를 커버로 자동 설정합니다."""
        non_rejected = [img for img in images if not img.is_rejected]
        if not non_rejected:
            return None
        pass_images = [img for img in non_rejected if img.auto_status == "pass"]
        candidates = pass_images if pass_images else non_rejected
        best = max(candidates, key=lambda img: img.cover_score or 0.0)
        review = self.db.query(Review).filter(Review.character_id == character_id).first()
        if not review:
            review = Review(character_id=character_id)
            self.db.add(review)
        review.cover_image_id = best.id
        self.db.commit()
        return best

    # ── 캐릭터 목록(GlobalCharacter) 중심 생성 ──────────────────────────
    # Character/Series 기반 생성 파이프라인과 완전히 독립적으로 동작하도록
    # GlobalCharacter*_ 전용 테이블(global_character_images 등)만 사용한다.

    def list_generation_candidates_global(
        self,
        *,
        search: str | None = None,
        limit: int = 300,
    ) -> list[GlobalCharacter]:
        """특징 태그 수집이 완료(collect_status == completed)되었고 아직 이미지가
        생성되지 않은 GlobalCharacter만 반환한다."""
        generated_ids = select(GlobalCharacterImage.global_character_id).distinct()
        query = (
            self.db.query(GlobalCharacter)
            .filter(GlobalCharacter.collect_status == "completed")
            .filter(~GlobalCharacter.id.in_(generated_ids))
        )
        if search:
            pattern = f"%{search.strip()}%"
            query = query.filter(
                (GlobalCharacter.character_tag.ilike(pattern)) | (GlobalCharacter.display_name.ilike(pattern))
            )
        return (
            query.order_by(GlobalCharacter.post_count.desc(), GlobalCharacter.id.asc())
            .limit(limit)
            .all()
        )

    def get_candidate_stats_global(self) -> dict[str, int]:
        total_completed = (
            self.db.query(GlobalCharacter).filter(GlobalCharacter.collect_status == "completed").count()
        )
        generated_ids = select(GlobalCharacterImage.global_character_id).distinct()
        already_generated = (
            self.db.query(GlobalCharacter)
            .filter(GlobalCharacter.collect_status == "completed")
            .filter(GlobalCharacter.id.in_(generated_ids))
            .count()
        )
        return {
            "total_completed": total_completed,
            "already_generated": already_generated,
            "remaining": max(0, total_completed - already_generated),
        }

    def prepare_queue_global(
        self,
        character_ids: list[int],
        *,
        prompt_level: int,
        prompt_config: GenerationPromptConfig | None = None,
    ) -> dict[str, object]:
        config = prompt_config or self.get_prompt_config()
        characters = (
            self.db.query(GlobalCharacter)
            .filter(GlobalCharacter.id.in_(character_ids))
            .order_by(GlobalCharacter.post_count.desc(), GlobalCharacter.character_tag.asc())
            .all()
        )

        eligible: list[GlobalCharacter] = []
        skipped: list[dict[str, object]] = []
        for character in characters:
            core = build_character_core(character, prompt_level)
            if not core:
                skipped.append(
                    {"id": character.id, "character_tag": character.character_tag, "reason": "외형 태그 없음"}
                )
                continue
            if character.collect_status != "completed":
                skipped.append(
                    {
                        "id": character.id,
                        "character_tag": character.character_tag,
                        "reason": "특징 태그 수집 미완료",
                    }
                )
                continue
            eligible.append(character)

        if not eligible:
            raise ValueError("생성 가능한 캐릭터가 없습니다. (외형 태그 없음 또는 특징 태그 수집 미완료)")

        queue_id = f"characters_{uuid.uuid4().hex[:8]}"
        wildcard_lines = [build_character_core(character, prompt_level) or "" for character in eligible]
        wildcard_path = write_character_wildcard(self.get_wildcards_dir(), queue_id, wildcard_lines)

        sample_prompt, negative_prompt = build_full_prompt(
            eligible[0],
            prompt_level=prompt_level,
            prompt_config=config,
            queue_id=queue_id,
            use_wildcard=True,
        )
        manifest = build_queue_manifest(
            queue_id=queue_id,
            series_tag="characters",
            series_id=0,
            prompt_level=prompt_level,
            wildcard_path=wildcard_path,
            characters=[
                {
                    "id": character.id,
                    "character_tag": character.character_tag,
                    "display_name": character.display_name,
                    "generation_prompt": getattr(character, "generation_prompt", None),
                    "character_core": build_character_core(character, prompt_level),
                }
                for character in eligible
            ],
            prompt_template=sample_prompt,
            negative_prompt=negative_prompt,
            prompt_prefix=config.prefix,
            prompt_suffix=config.suffix,
        )
        manifest_path = export_queue_manifest(
            settings.output_dir / "naia_queues" / f"{queue_id}.json",
            manifest,
        )

        return {
            "queue_id": queue_id,
            "prompt_level": prompt_level,
            "character_count": len(eligible),
            "skipped": skipped,
            "wildcard_path": str(wildcard_path),
            "manifest_path": str(manifest_path),
            "prompt_template": sample_prompt,
            "negative_prompt": negative_prompt,
            "prompt_prefix": config.prefix,
            "prompt_suffix": config.suffix,
            "characters": manifest["characters"],
        }

    def create_generation_jobs_global(
        self,
        queue_payload: dict[str, object],
        *,
        images_per_character: int,
    ) -> list[GlobalCharacterGenerationJob]:
        jobs: list[GlobalCharacterGenerationJob] = []
        prompt_level = int(queue_payload.get("prompt_level") or 1)
        stored = self.get_prompt_config()
        config = GenerationPromptConfig(
            prefix=str(queue_payload.get("prompt_prefix") or stored.prefix),
            suffix=str(queue_payload.get("prompt_suffix") or stored.suffix),
            negative_prompt=str(queue_payload.get("negative_prompt") or stored.negative_prompt),
        )
        negative_prompt = config.negative_prompt
        characters = queue_payload.get("characters")
        if not isinstance(characters, list):
            return jobs

        for item in characters:
            if not isinstance(item, dict):
                continue
            character_id = item.get("id")
            if not isinstance(character_id, int):
                continue
            character = self.db.query(GlobalCharacter).filter(GlobalCharacter.id == character_id).first()
            if not character:
                continue
            prompt, _ = build_full_prompt(
                character,
                prompt_level=prompt_level,
                prompt_config=config,
            )
            for _ in range(images_per_character):
                job = GlobalCharacterGenerationJob(
                    global_character_id=character.id,
                    prompt_level=prompt_level,
                    prompt=prompt,
                    negative_prompt=negative_prompt,
                    count=1,
                    status="pending",
                )
                self.db.add(job)
                jobs.append(job)
        self.db.commit()
        for job in jobs:
            self.db.refresh(job)
        return jobs

    def import_generated_image_global(
        self,
        *,
        character: GlobalCharacter,
        generation_job: GlobalCharacterGenerationJob,
        image_bytes: bytes,
        created_at: datetime | None = None,
        skip_checks: bool = False,
    ) -> GlobalCharacterImage:
        pending_dir = self.get_pending_images_dir()
        pending_dir.mkdir(parents=True, exist_ok=True)
        timestamp = (created_at or datetime.now()).strftime("%Y%m%d_%H%M%S")
        filename = f"{timestamp}_{_safe_filename_tag(character.character_tag)}.png"
        output_path = pending_dir / filename
        counter = 1
        while output_path.exists():
            output_path = pending_dir / f"{timestamp}_{_safe_filename_tag(character.character_tag)}_{counter}.png"
            counter += 1
        output_path.write_bytes(image_bytes)

        rel_path = output_path.relative_to(settings.project_root).as_posix()
        if skip_checks:
            check = None
        else:
            check = check_generated_image(
                output_path,
                character=character,
                series=None,
                hf_token=self._settings.get_hf_token() or None,
                hf_wd_model=self._settings.get_hf_wd_model() or None,
            )
        image = GlobalCharacterImage(
            global_character_id=character.id,
            generation_job_id=generation_job.id,
            image_path=rel_path,
            auto_tags=check.auto_tags if check else None,
            auto_status=check.auto_status if check else None,
            hair_match=check.hair_match if check else None,
            eye_match=check.eye_match if check else None,
            gender_pred=check.gender_pred if check else None,
            cover_score=check.cover_score if check else None,
        )
        generation_job.status = "completed"
        generation_job.output_path = rel_path
        self.db.add(image)
        self.db.commit()
        self.db.refresh(image)
        return image

    def mark_job_failed_global(self, generation_job: GlobalCharacterGenerationJob, error: str) -> None:
        generation_job.status = "failed"
        self.db.commit()

    def auto_select_cover_global(
        self, global_character_id: int, images: list[GlobalCharacterImage]
    ) -> GlobalCharacterImage | None:
        """생성된 이미지 중 최고 cover_score 이미지를 커버로 자동 설정합니다."""
        non_rejected = [img for img in images if not img.is_rejected]
        if not non_rejected:
            return None
        pass_images = [img for img in non_rejected if img.auto_status == "pass"]
        candidates = pass_images if pass_images else non_rejected
        best = max(candidates, key=lambda img: img.cover_score or 0.0)
        review = (
            self.db.query(GlobalCharacterReview)
            .filter(GlobalCharacterReview.global_character_id == global_character_id)
            .first()
        )
        if not review:
            review = GlobalCharacterReview(global_character_id=global_character_id)
            self.db.add(review)
        review.cover_image_id = best.id
        self.db.commit()
        return best

    def _resolve_review_gender(self, character: Character | GlobalCharacter, gender: str | None) -> str:
        if gender:
            normalized = normalize_gender(gender)
            if normalized in {"1girl", "1boy", "no_humans"}:
                return normalized
        return normalize_gender(character.gender) or "1girl"

    def _clear_character_review_images(self, character: Character) -> int:
        removed = 0
        images = (
            self.db.query(Image)
            .filter(Image.character_id == character.id, Image.is_rejected.is_(False))
            .all()
        )
        for image in images:
            file_path = settings.project_root / image.image_path
            if file_path.is_file():
                file_path.unlink()
            self.db.delete(image)
            removed += 1

        review = character.review
        if not review and removed:
            review = Review(character_id=character.id)
            self.db.add(review)
            character.review = review
        if review:
            review.cover_image_id = None
            review.review_status = "pending"

        if removed:
            self.db.flush()
        return removed

    def regenerate_review_images(
        self,
        character_id: int,
        *,
        prompt_core: str,
        gender: str | None = None,
        progress_callback: Callable[[dict[str, object]], None] | None = None,
    ) -> Character:
        character = (
            self.db.query(Character)
            .options(joinedload(Character.images), joinedload(Character.review))
            .filter(Character.id == character_id)
            .first()
        )
        if not character:
            raise ValueError("Character not found")

        status = self.naia_status()
        if not status.get("ready"):
            raise ValueError(str(status.get("message") or "NAIA가 준비되지 않았습니다."))

        resolved_gender = self._resolve_review_gender(character, gender)
        if gender:
            character.gender = resolved_gender

        prompt, negative_prompt = build_prompt_from_character_core(
            prompt_core,
            gender=resolved_gender,
            prompt_config=self.get_prompt_config(),
        )
        image_count = self.get_images_per_character()
        self._clear_character_review_images(character)
        # 재생성 명령 시점의 프롬프트를 리뷰에 저장해, 목록이 갱신돼도 그대로 표시되게 한다.
        review = character.review
        if not review:
            review = Review(character_id=character.id)
            self.db.add(review)
            character.review = review
        review.final_prompt = prompt_core.strip() or None
        # NAIA 생성은 수 분이 걸리므로, 그동안 SQLite 쓰기 트랜잭션을 열어두면
        # 다른 요청(리뷰 완료, 병합 등)이 전부 잠겨 멈춘다. 생성 전에 즉시 커밋한다.
        self.db.commit()

        if progress_callback:
            progress_callback(
                {
                    "phase": "generating",
                    "message": f"{character.character_tag} 기존 이미지 교체 · 생성 0/{image_count}",
                    "current": 0,
                    "total": image_count,
                }
            )

        client = NaiaClient(self.get_naia_base_url())
        known_history_ids = {
            str(item.get("history_id") or "")
            for item in client.list_history(page=0, per_page=20).get("images", [])
            if isinstance(item, dict)
        }
        known_history_ids.discard("")

        for index in range(image_count):
            if index > 0:
                wait_between_naia_generations()

            if progress_callback:
                progress_callback(
                    {
                        "phase": "generating",
                        "message": f"{character.character_tag} NAIA 생성 {index + 1}/{image_count}",
                        "current": index,
                        "total": image_count,
                    }
                )

            generation_job = GenerationJob(
                character_id=character.id,
                prompt_level=1,
                prompt=prompt,
                negative_prompt=negative_prompt,
                count=1,
                status="pending",
            )
            self.db.add(generation_job)
            # flush만 하면 NAIA 응답을 기다리는 내내 쓰기 잠금이 유지된다. 즉시 커밋.
            self.db.commit()

            try:
                image_bytes, _ = generate_and_fetch_image(
                    client,
                    prompt=prompt,
                    negative_prompt=negative_prompt,
                    known_history_ids=known_history_ids,
                )
            except Exception as exc:
                self.mark_job_failed(generation_job, str(exc))
                raise ValueError(f"NAIA 이미지 생성 실패 ({index + 1}/{image_count}): {exc}") from exc

            self.import_generated_image(
                character=character,
                generation_job=generation_job,
                image_bytes=image_bytes,
                skip_checks=True,
            )

            if progress_callback:
                progress_callback(
                    {
                        "phase": "generating",
                        "message": f"{character.character_tag} 저장 완료 {index + 1}/{image_count}",
                        "current": index + 1,
                        "total": image_count,
                    }
                )

        character.status = "generated"
        self.db.commit()

        refreshed = (
            self.db.query(Character)
            .options(
                joinedload(Character.images),
                joinedload(Character.review),
                joinedload(Character.series),
            )
            .filter(Character.id == character_id)
            .first()
        )
        if not refreshed:
            raise ValueError("Character not found after regenerate")

        # 재생성 완료 후 최고 점수 이미지를 커버로 자동 선택
        if refreshed.images:
            self.auto_select_cover(character_id, list(refreshed.images))

        return refreshed

    def _clear_global_character_review_images(self, character: GlobalCharacter) -> int:
        removed = 0
        images = (
            self.db.query(GlobalCharacterImage)
            .filter(
                GlobalCharacterImage.global_character_id == character.id,
                GlobalCharacterImage.is_rejected.is_(False),
            )
            .all()
        )
        for image in images:
            file_path = settings.project_root / image.image_path
            if file_path.is_file():
                file_path.unlink()
            self.db.delete(image)
            removed += 1

        review = character.review
        if not review and removed:
            review = GlobalCharacterReview(global_character_id=character.id)
            self.db.add(review)
            character.review = review
        if review:
            review.cover_image_id = None
            review.review_status = "pending"

        if removed:
            self.db.flush()
        return removed

    def regenerate_review_images_global(
        self,
        global_character_id: int,
        *,
        prompt_core: str,
        gender: str | None = None,
        progress_callback: Callable[[dict[str, object]], None] | None = None,
    ) -> GlobalCharacter:
        """`regenerate_review_images`의 GlobalCharacter(캐릭터 목록) 버전.
        '캐릭터 목록' 리뷰 탭은 series 전용 Character 테이블이 아니라 GlobalCharacter를
        다루므로, 이 메서드가 없으면 재생성 요청이 엉뚱한(id가 우연히 겹치는) series
        캐릭터에 적용되는 문제가 생긴다."""
        character = (
            self.db.query(GlobalCharacter)
            .options(joinedload(GlobalCharacter.images), joinedload(GlobalCharacter.review))
            .filter(GlobalCharacter.id == global_character_id)
            .first()
        )
        if not character:
            raise ValueError("Character not found")

        status = self.naia_status()
        if not status.get("ready"):
            raise ValueError(str(status.get("message") or "NAIA가 준비되지 않았습니다."))

        resolved_gender = self._resolve_review_gender(character, gender)
        if gender:
            character.gender = resolved_gender

        prompt, negative_prompt = build_prompt_from_character_core(
            prompt_core,
            gender=resolved_gender,
            prompt_config=self.get_prompt_config(),
        )
        image_count = self.get_images_per_character()
        self._clear_global_character_review_images(character)
        # 재생성 명령 시점의 프롬프트를 리뷰에 저장해, 목록이 갱신돼도 그대로 표시되게 한다.
        review = character.review
        if not review:
            review = GlobalCharacterReview(global_character_id=character.id)
            self.db.add(review)
            character.review = review
        review.final_prompt = prompt_core.strip() or None
        # NAIA 생성은 수 분이 걸리므로, 그동안 SQLite 쓰기 트랜잭션을 열어두면
        # 다른 요청(리뷰 완료, 병합 등)이 전부 잠겨 멈춘다. 생성 전에 즉시 커밋한다.
        self.db.commit()

        if progress_callback:
            progress_callback(
                {
                    "phase": "generating",
                    "message": f"{character.character_tag} 기존 이미지 교체 · 생성 0/{image_count}",
                    "current": 0,
                    "total": image_count,
                }
            )

        client = NaiaClient(self.get_naia_base_url())
        known_history_ids = {
            str(item.get("history_id") or "")
            for item in client.list_history(page=0, per_page=20).get("images", [])
            if isinstance(item, dict)
        }
        known_history_ids.discard("")

        for index in range(image_count):
            if index > 0:
                wait_between_naia_generations()

            if progress_callback:
                progress_callback(
                    {
                        "phase": "generating",
                        "message": f"{character.character_tag} NAIA 생성 {index + 1}/{image_count}",
                        "current": index,
                        "total": image_count,
                    }
                )

            generation_job = GlobalCharacterGenerationJob(
                global_character_id=character.id,
                prompt_level=1,
                prompt=prompt,
                negative_prompt=negative_prompt,
                count=1,
                status="pending",
            )
            self.db.add(generation_job)
            # flush만 하면 NAIA 응답을 기다리는 내내 쓰기 잠금이 유지된다. 즉시 커밋.
            self.db.commit()

            try:
                image_bytes, _ = generate_and_fetch_image(
                    client,
                    prompt=prompt,
                    negative_prompt=negative_prompt,
                    known_history_ids=known_history_ids,
                )
            except Exception as exc:
                self.mark_job_failed_global(generation_job, str(exc))
                raise ValueError(f"NAIA 이미지 생성 실패 ({index + 1}/{image_count}): {exc}") from exc

            self.import_generated_image_global(
                character=character,
                generation_job=generation_job,
                image_bytes=image_bytes,
                skip_checks=True,
            )

            if progress_callback:
                progress_callback(
                    {
                        "phase": "generating",
                        "message": f"{character.character_tag} 저장 완료 {index + 1}/{image_count}",
                        "current": index + 1,
                        "total": image_count,
                    }
                )

        self.db.commit()

        refreshed = (
            self.db.query(GlobalCharacter)
            .options(joinedload(GlobalCharacter.images), joinedload(GlobalCharacter.review))
            .filter(GlobalCharacter.id == global_character_id)
            .first()
        )
        if not refreshed:
            raise ValueError("Character not found after regenerate")

        if refreshed.images:
            self.auto_select_cover_global(global_character_id, list(refreshed.images))

        return refreshed
