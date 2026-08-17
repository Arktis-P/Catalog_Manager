"""Stage-ordered repair decisions for pending inspection / V2 regeneration.

Identity repairs always precede semantic repairs. Persistent *actionable* appearance
failure skips semantic stages and ends in an automatic 0-star decision. A missing WD
character tag alone is intentionally non-actionable because many catalogue characters
are outside the tagger vocabulary; treating that warning as identity failure would
regenerate and auto-zero large parts of the pending queue for no visual reason.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from app.integrations.danbooru.appearance_extractor import normalize_gender

STAGE_IDENTITY_HAIR = "identity_hair"
STAGE_IDENTITY_MULTICOLOR = "identity_multicolor"
STAGE_IDENTITY_EYE = "identity_eye"
STAGE_SEMANTIC_OUTFIT = "semantic_outfit"
STAGE_SEMANTIC_GALLERY = "semantic_gallery"
STAGE_QUALITY = "quality"
STAGE_AUTO_ZERO = "auto_zero"
STAGE_DONE = "done"

# Only signals that carry actual appearance evidence may spend regeneration budget.
# `*_character_tag_undetected` is excluded: the local WD model simply does not know a
# large fraction of the 100k+ catalogue character tags, so absence is not evidence that
# the generated person is wrong.
IDENTITY_INSUFFICIENT_REASONS = frozenset(
    {
        "character_tag_low_confidence",
        "hair_color_mismatch",
    }
)
IDENTITY_NONACTIONABLE_REASONS = frozenset(
    {
        "character_tag_undetected",
        "boy_character_tag_undetected",
    }
)
IDENTITY_HAIR_REASONS = frozenset({"hair_color_mismatch"})
IDENTITY_MULTICOLOR_REASONS = frozenset({"unexpected_multicolor_tag", "character_tag_low_confidence"})

SEMANTIC_OUTFIT_PREFIXES = (
    "atypical_swimwear:",
    "atypical_underwear:",
)
SEMANTIC_GALLERY_PREFIXES = (
    "embedded_gallery:",
    "printed_character_gallery",
    "goods_or_screen_character_gallery",
    "poster_or_collage_with_text",
    "weak_print_gallery",
    "unexpected_non_human_output",
    "unexpected_male_output",
)

# Keep in sync with v2_generation_pipeline.SEMANTIC_REGEN_REASON_PREFIXES consumers.
ALL_SEMANTIC_REPAIR_PREFIXES = SEMANTIC_OUTFIT_PREFIXES + SEMANTIC_GALLERY_PREFIXES


@dataclass
class RepairContext:
    """Compact per-character repair ledger stored in-memory for one inspect/regen run."""

    attempted_stages: list[str] = field(default_factory=list)
    identity_ok: bool = False
    final_action: str = "pending"
    reject_reason: str | None = None
    latest_image_id: int | None = None
    image_count: int = 0
    regeneration_requested: int = 0
    regeneration_completed: int = 0
    reinspection_completed: int = 0
    identity_repair_stage: str | None = None
    semantic_repair_stage: str | None = None
    unavailable_stages: list[str] = field(default_factory=list)
    # Compact per-stage prompt/inspection diffs for page-test diagnostics (never secrets).
    stage_events: list[dict[str, object]] = field(default_factory=list)

    def mark(self, stage: str) -> None:
        self.attempted_stages.append(stage)
        if stage.startswith("identity_"):
            self.identity_repair_stage = stage
        if stage.startswith("semantic_"):
            self.semantic_repair_stage = stage

    def mark_unavailable(self, stage: str) -> None:
        """Record a stage that had no actionable collected data (no budget spent)."""
        self.mark(stage)
        if stage not in self.unavailable_stages:
            self.unavailable_stages.append(stage)

    def already(self, stage: str) -> bool:
        return stage in self.attempted_stages

    def record_event(self, event: dict[str, object]) -> None:
        self.stage_events.append(event)

    def as_dict(self) -> dict[str, object]:
        return {
            "attempted_stages": list(self.attempted_stages),
            "identity_ok": self.identity_ok,
            "final_action": self.final_action,
            "reject_reason": self.reject_reason,
            "latest_image_id": self.latest_image_id,
            "image_count_for_character": self.image_count,
            "identity_repair_stage": self.identity_repair_stage,
            "semantic_repair_stage": self.semantic_repair_stage,
            "regeneration_requested": self.regeneration_requested,
            "regeneration_completed": self.regeneration_completed,
            "reinspection_completed": self.reinspection_completed,
            "unavailable_stages": list(self.unavailable_stages),
            "stage_events": list(self.stage_events),
        }


def _has_prefix(reasons: Iterable[str], prefixes: tuple[str, ...]) -> bool:
    for reason in reasons:
        text = str(reason)
        if any(text.startswith(prefix) or text == prefix.rstrip(":") for prefix in prefixes):
            return True
    return False


def identity_insufficient(reasons: Iterable[str] | None) -> bool:
    """Return True only for actionable appearance evidence, never tag absence alone."""
    if not reasons:
        return False
    return any(str(reason) in IDENTITY_INSUFFICIENT_REASONS for reason in reasons)


def needs_identity_hair_repair(reasons: Iterable[str] | None) -> bool:
    if not reasons:
        return False
    return any(str(reason) in IDENTITY_HAIR_REASONS for reason in reasons)


def needs_identity_repair(reasons: Iterable[str] | None) -> bool:
    """True when appearance identity should be repaired before semantic retries."""
    return identity_insufficient(reasons)


def is_semantic_outfit_reject(reasons: Iterable[str] | None) -> bool:
    return bool(reasons) and _has_prefix(reasons, SEMANTIC_OUTFIT_PREFIXES)


def is_semantic_gallery_reject(reasons: Iterable[str] | None) -> bool:
    return bool(reasons) and _has_prefix(reasons, SEMANTIC_GALLERY_PREFIXES)


def is_semantic_repair_reject(reasons: Iterable[str] | None) -> bool:
    return is_semantic_outfit_reject(reasons) or is_semantic_gallery_reject(reasons)


def decide_repair_stage(
    *,
    gender: str | None,
    quality_status: str | None,
    identity_status: str | None,
    reasons: Iterable[str] | None,
    context: RepairContext,
) -> str:
    """Return the next repair stage for the current latest image."""
    reason_list = [str(item) for item in (reasons or [])]

    if quality_status == "reject":
        if context.already(STAGE_QUALITY) and context.attempted_stages.count(STAGE_QUALITY) >= 2:
            return STAGE_AUTO_ZERO
        return STAGE_QUALITY

    gender_key = normalize_gender(gender)
    insufficient = identity_insufficient(reason_list)
    hair_mismatch = needs_identity_hair_repair(reason_list)

    # --- Identity-first ladder -------------------------------------------------
    if hair_mismatch and not context.already(STAGE_IDENTITY_HAIR):
        return STAGE_IDENTITY_HAIR

    if gender_key == "1boy":
        if insufficient:
            # Male policy is intentionally short: only a concrete hair mismatch earns
            # one repair. If hair already matches (or hair repair was already tried),
            # persistent actionable identity evidence ends at 0-star instead of
            # inventing multicolor/eye tags.
            return STAGE_AUTO_ZERO
        # Boy identity acceptable/unknown: continue to semantic if needed.
    else:
        # Female / unknown: hair -> multicolor -> eye, then auto-zero if actionable
        # identity evidence is still bad. Tag-undetected alone never enters this ladder.
        if insufficient and not context.already(STAGE_IDENTITY_MULTICOLOR):
            if context.already(STAGE_IDENTITY_HAIR) or not hair_mismatch:
                return STAGE_IDENTITY_MULTICOLOR
        if insufficient and context.already(STAGE_IDENTITY_MULTICOLOR) and not context.already(
            STAGE_IDENTITY_EYE
        ):
            if gender_key == "1girl":
                return STAGE_IDENTITY_EYE
            return STAGE_AUTO_ZERO
        if insufficient and context.already(STAGE_IDENTITY_EYE):
            return STAGE_AUTO_ZERO

    context.identity_ok = not insufficient

    # --- Semantic only when actionable identity evidence is acceptable ---------
    if insufficient:
        return STAGE_AUTO_ZERO

    if identity_status == "reject" or is_semantic_outfit_reject(reason_list):
        if is_semantic_outfit_reject(reason_list):
            if context.already(STAGE_SEMANTIC_OUTFIT) and context.attempted_stages.count(
                STAGE_SEMANTIC_OUTFIT
            ) >= 2:
                return STAGE_AUTO_ZERO
            return STAGE_SEMANTIC_OUTFIT

    if identity_status == "reject" or is_semantic_gallery_reject(reason_list):
        if is_semantic_gallery_reject(reason_list):
            if context.already(STAGE_SEMANTIC_GALLERY) and context.attempted_stages.count(
                STAGE_SEMANTIC_GALLERY
            ) >= 2:
                return STAGE_AUTO_ZERO
            return STAGE_SEMANTIC_GALLERY

    if identity_status == "reject":
        # Non-classified reject after identity OK — one more semantic-style retry budget
        # is not available; finalize as auto-zero rather than looping forever.
        return STAGE_AUTO_ZERO

    return STAGE_DONE
