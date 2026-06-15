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
    build_character_core,
    build_full_prompt,
    build_queue_manifest,
    export_queue_manifest,
)
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
        search: str | None = None,
    ) -> list[Character]:
        query = (
            self.db.query(Character)
            .filter(Character.series_id == series_id)
            .filter(Character.generation_prompt.isnot(None))
            .filter(Character.generation_prompt != "")
        )
        if require_confirmed:
            query = query.filter(Character.appearance_confirmed.is_(True))
        if search:
            pattern = f"%{search.strip()}%"
            query = query.filter(
                (Character.character_tag.ilike(pattern)) | (Character.display_name.ilike(pattern))
            )
        return query.order_by(Character.post_count.desc(), Character.character_tag.asc()).all()

    def preview_prompt(
        self,
        character_id: int,
        *,
        prompt_level: int = 1,
    ) -> dict[str, str | int]:
        character = self.db.query(Character).filter(Character.id == character_id).first()
        if not character:
            raise ValueError("Character not found")
        prompt, negative = build_full_prompt(character, prompt_level=prompt_level)
        return {
            "character_id": character.id,
            "character_tag": character.character_tag,
            "prompt_level": prompt_level,
            "prompt": prompt,
            "negative_prompt": negative,
        }

    def prepare_queue(
        self,
        series_id: int,
        *,
        character_ids: list[int] | None,
        prompt_level: int,
        require_confirmed: bool = True,
    ) -> dict[str, object]:
        series = self.db.query(Series).filter(Series.id == series_id).first()
        if not series:
            raise ValueError("Series not found")

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
            raise ValueError("생성 가능한 캐릭터가 없습니다.")

        queue_id = f"{series.series_tag}_{uuid.uuid4().hex[:8]}"
        wildcard_lines = [build_character_core(character, prompt_level) or "" for character in eligible]
        wildcard_path = write_character_wildcard(self.get_wildcards_dir(), queue_id, wildcard_lines)

        sample_prompt, negative_prompt = build_full_prompt(
            eligible[0],
            prompt_level=prompt_level,
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
        negative_prompt = str(queue_payload.get("negative_prompt") or "")
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
            prompt, _ = build_full_prompt(character, prompt_level=prompt_level)
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
        image = Image(
            character_id=character.id,
            generation_job_id=generation_job.id,
            image_path=rel_path,
            auto_status="pending_review",
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
