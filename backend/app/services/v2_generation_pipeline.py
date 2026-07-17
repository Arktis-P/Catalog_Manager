from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import settings
from app.integrations.danbooru.client import DanbooruClient
from app.integrations.naia.client import NaiaClient
from app.integrations.naia.generation_runner import (
    generate_and_fetch_image,
    wait_between_naia_generations,
)
from app.models.appearance_tag_relevance import CharacterAppearanceTagRelevance
from app.models.global_character import GlobalCharacter
from app.models.global_character_generation_job import GlobalCharacterGenerationJob
from app.models.global_character_image import GlobalCharacterImage
from app.services.character_image_service import apply_provisional_status
from app.services.db_write_queue import commit_db_session
from app.services.generation_prompt_builder import build_full_prompt_v2
from app.services.generation_service import GenerationService
from app.services.identity_checker import (
    IDENTITY_CHECKER_VERSION,
    IdentityCheckResult,
    check_identity,
)
from app.services.prompt_service import refresh_global_character_base_prompt, v2_multicolor_prompt_candidates
from app.services.quality_checker import QUALITY_CHECKER_VERSION, check_quality
from app.services.settings_service import SettingsService

logger = logging.getLogger(__name__)

ImageBytesGenerator = Callable[[str, str], bytes]
CancelCheck = Callable[[], bool]


class V2PipelineCancelled(RuntimeError):
    pass


@dataclass(frozen=True)
class PromptVariant:
    base_prompt: str
    primary_hair_color: str | None
    multicolor_tags: tuple[str, ...]
    revision_level: int | None = None
    revision_reason: str | None = None


@dataclass(frozen=True)
class V2PipelineResult:
    character_id: int
    generation_status: str
    generation_attempts: int
    image_id: int | None


def _tag_key(value: str) -> str:
    return value.strip().lower().replace("_", " ")


def _split_prompt(base_prompt: str) -> tuple[str, list[str]]:
    head, separator, tail = base_prompt.partition(",")
    tags = [part.strip() for part in tail.split(",") if part.strip()] if separator else []
    return head.strip(), tags


def _replace_prompt_tags(
    base_prompt: str,
    *,
    remove: tuple[str, ...] = (),
    add: tuple[str, ...] = (),
) -> str:
    head, tags = _split_prompt(base_prompt)
    remove_keys = {_tag_key(tag) for tag in remove}
    remaining = [tag for tag in tags if _tag_key(tag) not in remove_keys]
    known = {_tag_key(tag) for tag in remaining}
    for tag in add:
        prompt_tag = tag.strip().replace("_", " ")
        if prompt_tag and _tag_key(prompt_tag) not in known:
            remaining.append(prompt_tag)
            known.add(_tag_key(prompt_tag))
    return f"{head}, {', '.join(remaining)}" if remaining else head


class V2GenerationPipeline:
    """GlobalCharacter 한 명의 V2 생성·검사·보정 상태 머신."""

    def __init__(
        self,
        db: Session,
        *,
        image_bytes_generator: ImageBytesGenerator | None = None,
        quality_checker: Callable[[Path], object] = check_quality,
        identity_checker: Callable[..., IdentityCheckResult] = check_identity,
        wiki_client: DanbooruClient | None = None,
        wait_between_generations: Callable[[], float] = wait_between_naia_generations,
    ) -> None:
        self.db = db
        self.service = GenerationService(db)
        self.settings_service = SettingsService(db)
        self._image_bytes_generator = image_bytes_generator
        self._quality_checker = quality_checker
        self._identity_checker = identity_checker
        self._wiki_client = wiki_client
        self._wait_between_generations = wait_between_generations
        self._client: NaiaClient | None = None
        self._known_history_ids: set[str] = set()
        self._generated_count = 0

    def _public_settings(self) -> dict[str, int | float | str]:
        return self.settings_service.get_public_settings()

    def _default_generate_bytes(self, prompt: str, negative_prompt: str) -> bytes:
        if self._client is None:
            self._client = NaiaClient(self.service.get_naia_base_url())
            history = self._client.list_history(page=0, per_page=20).get("images", [])
            self._known_history_ids = {
                str(item.get("history_id") or "")
                for item in history
                if isinstance(item, dict) and item.get("history_id")
            }
        image_bytes, _ = generate_and_fetch_image(
            self._client,
            prompt=prompt,
            negative_prompt=negative_prompt,
            known_history_ids=self._known_history_ids,
        )
        return image_bytes

    def _generate_and_store(
        self,
        character: GlobalCharacter,
        variant: PromptVariant,
        *,
        should_cancel: CancelCheck,
    ) -> GlobalCharacterImage:
        if should_cancel():
            raise V2PipelineCancelled()
        if self._generated_count:
            self._wait_between_generations()

        prompt_character = type(
            "V2PromptCharacter",
            (),
            {
                "character_tag": character.character_tag,
                "gender": character.gender,
                "base_prompt": variant.base_prompt,
            },
        )()
        prompt, negative_prompt = build_full_prompt_v2(
            prompt_character,
            prompt_config=self.service.get_prompt_config(),
        )
        generation_job = GlobalCharacterGenerationJob(
            global_character_id=character.id,
            prompt_level=variant.revision_level or 1,
            prompt=prompt,
            negative_prompt=negative_prompt,
            count=1,
            status="pending",
        )
        character.generation_attempts = (character.generation_attempts or 0) + 1
        self.db.add(generation_job)
        commit_db_session(self.db)
        self.db.refresh(generation_job)

        try:
            generator = self._image_bytes_generator or self._default_generate_bytes
            image_bytes = generator(prompt, negative_prompt)
            self._generated_count += 1
            return self.service.import_generated_image_global(
                character=character,
                generation_job=generation_job,
                image_bytes=image_bytes,
                skip_checks=True,
            )
        except Exception:
            generation_job.status = "failed"
            commit_db_session(self.db)
            raise

    def _check_image(
        self,
        image: GlobalCharacterImage,
        character: GlobalCharacter,
        variant: PromptVariant,
    ) -> tuple[GlobalCharacterImage, IdentityCheckResult | None]:
        image_path = settings.project_root / image.image_path
        quality = self._quality_checker(image_path)
        now = datetime.now()
        image.quality_status = quality.status
        image.quality_score = quality.score
        image.quality_reasons = json.dumps(quality.reasons, ensure_ascii=False)
        image.quality_checked_at = now
        image.quality_checker_version = QUALITY_CHECKER_VERSION

        identity: IdentityCheckResult | None = None
        if quality.status != "reject":
            known_character_tags = [
                row[0]
                for row in self.db.query(GlobalCharacter.character_tag)
                .filter(GlobalCharacter.id != character.id)
                .all()
            ]
            identity = self._identity_checker(
                image_path,
                character_tag=character.character_tag,
                primary_hair_color=variant.primary_hair_color,
                expected_multicolor_tags=variant.multicolor_tags,
                gender=character.gender,
                known_character_tags=known_character_tags,
                hf_token=self.settings_service.get_hf_token() or None,
                hf_wd_model=self.settings_service.get_hf_wd_model() or None,
            )
            image.identity_status = identity.status
            image.character_confidence = identity.character_confidence
            image.hair_color_confidence = identity.hair_color_confidence
            image.conflicting_character_tag = identity.conflicting_character_tag
            image.conflicting_character_confidence = identity.conflicting_character_confidence
            image.identity_reasons = json.dumps(identity.reasons, ensure_ascii=False)
            image.suggested_multicolor_tags = json.dumps(
                identity.suggested_multicolor_tags, ensure_ascii=False
            )
            image.identity_checked_at = now
            image.identity_checker_version = IDENTITY_CHECKER_VERSION

        apply_provisional_status(self.db, image, character)
        commit_db_session(self.db)
        self.db.refresh(image)
        return image, identity

    def _relevance_rows(
        self, character_id: int, category: str
    ) -> list[CharacterAppearanceTagRelevance]:
        return (
            self.db.query(CharacterAppearanceTagRelevance)
            .filter(
                CharacterAppearanceTagRelevance.global_character_id == character_id,
                CharacterAppearanceTagRelevance.tag_category == category,
            )
            .order_by(
                CharacterAppearanceTagRelevance.relevance_score.desc(),
                CharacterAppearanceTagRelevance.cooccurrence_count.desc(),
                CharacterAppearanceTagRelevance.tag.asc(),
            )
            .all()
        )

    def _revision_variants(
        self,
        character: GlobalCharacter,
        initial: PromptVariant,
        rejected_identity: IdentityCheckResult,
    ) -> list[PromptVariant]:
        variants: list[PromptVariant] = []
        current = initial

        hair_rows = self._relevance_rows(character.id, "hair_color")
        alternate_hair = next(
            (row.tag for row in hair_rows if _tag_key(row.tag) != _tag_key(initial.primary_hair_color or "")),
            None,
        )
        if alternate_hair:
            current = PromptVariant(
                base_prompt=_replace_prompt_tags(
                    current.base_prompt,
                    remove=(current.primary_hair_color or "",),
                    add=(alternate_hair,),
                ),
                primary_hair_color=alternate_hair,
                multicolor_tags=current.multicolor_tags,
                revision_level=1,
                revision_reason=f"primary_hair_color:{initial.primary_hair_color}->{alternate_hair}",
            )
            variants.append(current)

        if current.multicolor_tags:
            level2_multicolor: tuple[str, ...] = ()
            level2_prompt = _replace_prompt_tags(current.base_prompt, remove=current.multicolor_tags)
            level2_reason = "remove_multicolor"
        else:
            suggested = list(rejected_identity.suggested_multicolor_tags)
            if not suggested:
                suggested = [
                    row.tag
                    for row in self._relevance_rows(character.id, "multicolor")
                    if not row.is_prompt_candidate
                ][:1]
            level2_multicolor = tuple(suggested[:1])
            level2_prompt = _replace_prompt_tags(current.base_prompt, add=level2_multicolor)
            level2_reason = f"add_multicolor:{','.join(level2_multicolor)}"
        if level2_prompt != current.base_prompt:
            current = PromptVariant(
                base_prompt=level2_prompt,
                primary_hair_color=current.primary_hair_color,
                multicolor_tags=level2_multicolor,
                revision_level=2,
                revision_reason=level2_reason,
            )
            variants.append(current)

        eye_rows = self._relevance_rows(character.id, "eye_color")
        if eye_rows:
            current = PromptVariant(
                base_prompt=_replace_prompt_tags(current.base_prompt, add=(eye_rows[0].tag,)),
                primary_hair_color=current.primary_hair_color,
                multicolor_tags=current.multicolor_tags,
                revision_level=3,
                revision_reason=f"add_eye_color:{eye_rows[0].tag}",
            )
            variants.append(current)

        features = tuple(
            row.tag for row in self._relevance_rows(character.id, "feature") if row.is_prompt_candidate
        )
        if features:
            current = PromptVariant(
                base_prompt=_replace_prompt_tags(current.base_prompt, add=features),
                primary_hair_color=current.primary_hair_color,
                multicolor_tags=current.multicolor_tags,
                revision_level=4,
                revision_reason=f"add_features:{','.join(features)}",
            )
            variants.append(current)
        return variants

    def _collect_wiki_reference(self, character_tag: str) -> None:
        try:
            client = self._wiki_client or DanbooruClient()
            page = client.get_wiki_page(character_tag)
            body = str(page.get("body") or "") if page else ""
            logger.info(
                "V2 identity 보정 위키 참고: character=%s found=%s body_length=%d",
                character_tag,
                bool(page),
                len(body),
            )
        except Exception as exc:
            logger.warning("V2 identity 보정 위키 조회 실패: character=%s error=%s", character_tag, exc)

    @staticmethod
    def _is_recent(character: GlobalCharacter, cutoff: str) -> bool:
        if character.first_post_at is None:
            return False
        return character.first_post_at.date() >= date.fromisoformat(cutoff)

    def run_character(
        self,
        character_id: int,
        *,
        should_cancel: CancelCheck | None = None,
    ) -> V2PipelineResult:
        cancel = should_cancel or (lambda: False)
        character = self.db.query(GlobalCharacter).filter(GlobalCharacter.id == character_id).first()
        if character is None:
            raise ValueError("Character not found")

        previous_status = character.generation_status
        character.generation_status = "generating"
        if not character.base_prompt:
            refresh_global_character_base_prompt(self.db, character)
        commit_db_session(self.db)

        try:
            multicolor = tuple(v2_multicolor_prompt_candidates(self.db, character.id))
            initial = PromptVariant(
                base_prompt=character.base_prompt or "",
                primary_hair_color=character.primary_hair_color,
                multicolor_tags=multicolor,
            )
            retry_max = max(1, int(self._public_settings()["v2_quality_retry_max"]))
            image: GlobalCharacterImage | None = None
            identity: IdentityCheckResult | None = None
            for _ in range(retry_max):
                image = self._generate_and_store(character, initial, should_cancel=cancel)
                image, identity = self._check_image(image, character, initial)
                if image.quality_status != "reject":
                    break
            else:
                character.generation_status = "generation_failed"
                commit_db_session(self.db)
                return V2PipelineResult(character.id, character.generation_status, character.generation_attempts, image.id)

            if identity is not None and identity.status != "reject":
                character.generation_status = "generated"
                commit_db_session(self.db)
                return V2PipelineResult(character.id, character.generation_status, character.generation_attempts, image.id)

            cutoff = str(self._public_settings()["v2_recent_character_cutoff"])
            if self._is_recent(character, cutoff):
                character.generation_status = "likely_untrained"
                commit_db_session(self.db)
                return V2PipelineResult(character.id, character.generation_status, character.generation_attempts, image.id)

            if identity is None:
                raise RuntimeError("quality 통과 이미지에 identity 검사 결과가 없습니다.")
            self._collect_wiki_reference(character.character_tag)
            for variant in self._revision_variants(character, initial, identity):
                revised_image = self._generate_and_store(character, variant, should_cancel=cancel)
                revised_image, revised_identity = self._check_image(revised_image, character, variant)
                image = revised_image
                if revised_image.quality_status == "reject":
                    continue
                if revised_identity is not None and revised_identity.status != "reject":
                    character.previous_base_prompt = character.base_prompt
                    character.base_prompt = variant.base_prompt
                    character.primary_hair_color = variant.primary_hair_color
                    character.prompt_revision_reason = variant.revision_reason
                    character.prompt_revision_level = variant.revision_level
                    character.generation_status = "generated"
                    commit_db_session(self.db)
                    return V2PipelineResult(
                        character.id, character.generation_status, character.generation_attempts, image.id
                    )

            character.generation_status = "generation_failed"
            commit_db_session(self.db)
            return V2PipelineResult(character.id, character.generation_status, character.generation_attempts, image.id)
        except V2PipelineCancelled:
            character.generation_status = previous_status
            commit_db_session(self.db)
            raise
        except Exception:
            character.generation_status = "generation_failed"
            commit_db_session(self.db)
            raise
