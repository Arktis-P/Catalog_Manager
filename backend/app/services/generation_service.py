from __future__ import annotations

import re
import uuid
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import settings
from app.integrations.naia.client import NaiaClient, NaiaClientError
from app.integrations.naia.wildcard_writer import write_character_wildcard
from app.models.character import Character
from app.models.generation_job import GenerationJob
from app.models.image import Image
from app.models.series import Series
from app.services.generation_prompt_builder import (
    GenerationPromptConfig,
    build_character_core,
    build_full_prompt,
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
        series = self.db.query(Series).filter(Series.id == character.series_id).first()
        check = check_generated_image(
            output_path,
            character=character,
            series=series,
        )
        image = Image(
            character_id=character.id,
            generation_job_id=generation_job.id,
            image_path=rel_path,
            auto_tags=check.auto_tags,
            auto_status=check.auto_status,
            hair_match=check.hair_match,
            eye_match=check.eye_match,
            gender_pred=check.gender_pred,
            cover_score=check.cover_score,
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
