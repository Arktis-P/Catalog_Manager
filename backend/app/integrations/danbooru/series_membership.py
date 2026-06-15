from __future__ import annotations

from dataclasses import dataclass

from app.integrations.danbooru.appearance_extractor import RelatedTag, parse_related_tags
from app.integrations.danbooru.client import DanbooruClient

MEMBERSHIP_MISMATCH_PREFIX = "Series membership:"
AUTO_EXCLUDE_FREQUENCY_RATIO = 2.0


@dataclass(frozen=True)
class SeriesMembershipResult:
    expected_series_tag: str
    top_copyright_tag: str | None
    top_copyright_frequency: float
    expected_frequency: float
    is_mismatch: bool
    reason: str | None = None


def _normalize_series_tag(value: str) -> str:
    return value.strip().lower().replace(" ", "_")


def _accepted_series_tags(expected_series_tag: str, extra_series_tags: set[str] | None = None) -> set[str]:
    accepted = {_normalize_series_tag(expected_series_tag)}
    if extra_series_tags:
        accepted.update(_normalize_series_tag(tag) for tag in extra_series_tags)
    return accepted


def evaluate_series_membership(
    copyrights: list[RelatedTag],
    *,
    expected_series_tag: str,
    extra_series_tags: set[str] | None = None,
    frequency_ratio_threshold: float = AUTO_EXCLUDE_FREQUENCY_RATIO,
) -> SeriesMembershipResult:
    accepted = _accepted_series_tags(expected_series_tag, extra_series_tags)
    if not copyrights:
        return SeriesMembershipResult(
            expected_series_tag=expected_series_tag,
            top_copyright_tag=None,
            top_copyright_frequency=0.0,
            expected_frequency=0.0,
            is_mismatch=False,
        )

    sorted_copyrights = sorted(copyrights, key=lambda item: item.frequency, reverse=True)
    top = sorted_copyrights[0]
    expected_frequency = max(
        (item.frequency for item in sorted_copyrights if _normalize_series_tag(item.name) in accepted),
        default=0.0,
    )

    top_normalized = _normalize_series_tag(top.name)
    if top_normalized in accepted:
        return SeriesMembershipResult(
            expected_series_tag=expected_series_tag,
            top_copyright_tag=top.name,
            top_copyright_frequency=top.frequency,
            expected_frequency=expected_frequency or top.frequency,
            is_mismatch=False,
        )

    if expected_frequency <= 0:
        reason = (
            f"{MEMBERSHIP_MISMATCH_PREFIX} expected '{expected_series_tag}' not in related copyrights; "
            f"top='{top.name}' ({top.frequency:.3f})"
        )
        return SeriesMembershipResult(
            expected_series_tag=expected_series_tag,
            top_copyright_tag=top.name,
            top_copyright_frequency=top.frequency,
            expected_frequency=0.0,
            is_mismatch=True,
            reason=reason,
        )

    if top.frequency >= expected_frequency * frequency_ratio_threshold:
        reason = (
            f"{MEMBERSHIP_MISMATCH_PREFIX} '{top.name}' ({top.frequency:.3f}) is more associated than "
            f"'{expected_series_tag}' ({expected_frequency:.3f})"
        )
        return SeriesMembershipResult(
            expected_series_tag=expected_series_tag,
            top_copyright_tag=top.name,
            top_copyright_frequency=top.frequency,
            expected_frequency=expected_frequency,
            is_mismatch=True,
            reason=reason,
        )

    return SeriesMembershipResult(
        expected_series_tag=expected_series_tag,
        top_copyright_tag=top.name,
        top_copyright_frequency=top.frequency,
        expected_frequency=expected_frequency,
        is_mismatch=False,
    )


def extract_copyright_related_tags(payload: object) -> list[RelatedTag]:
    if not isinstance(payload, dict):
        return []

    items = payload.get("related_tags")
    if not isinstance(items, list):
        return []

    copyright_items: list[dict[str, object]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        tag = item.get("tag")
        if not isinstance(tag, dict):
            continue
        if int(tag.get("category") or 0) != DanbooruClient.CATEGORY_COPYRIGHT:
            continue
        copyright_items.append(item)

    return parse_related_tags({"related_tags": copyright_items})


class SeriesMembershipValidator:
    def __init__(self, client: DanbooruClient | None = None):
        self.client = client or DanbooruClient()

    def validate(
        self,
        character_tag: str,
        *,
        expected_series_tag: str,
        extra_series_tags: set[str] | None = None,
    ) -> SeriesMembershipResult:
        payload = self.client.get_related_tags(character_tag, category=0)
        copyrights = extract_copyright_related_tags(payload)
        return evaluate_series_membership(
            copyrights,
            expected_series_tag=expected_series_tag,
            extra_series_tags=extra_series_tags,
        )
