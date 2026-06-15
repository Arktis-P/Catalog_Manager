from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageFilter, ImageStat

from app.models.character import Character
from app.models.series import Series

# WD14 캐릭터 태그 confidence 검사는 모델 별도 설치 후 활성화 예정.
CHARACTER_TAG_CHECK_ENABLED = False


@dataclass
class DetailCheckResult:
    hand_check_skipped: bool
    hand_ok: bool | None
    eye_ok: bool | None
    hand_score: float | None
    eye_score: float | None
    full_score: float


@dataclass
class ImageAutoCheckResult:
    auto_status: str
    auto_tags: str
    hair_match: bool | None
    eye_match: bool | None
    gender_pred: str | None
    cover_score: float | None


def _normalize_tag(value: str) -> str:
    return re.sub(r"\s+", "_", value.strip().lower())


def _region_sharpness(image: Image.Image, box: tuple[int, int, int, int]) -> float:
    crop = image.crop(box).convert("L")
    edges = crop.filter(ImageFilter.FIND_EDGES)
    return float(ImageStat.Stat(edges).var[0])


def _region_mean(image: Image.Image, box: tuple[int, int, int, int]) -> float:
    crop = image.crop(box).convert("L")
    return float(ImageStat.Stat(crop).mean[0])


def check_detail_quality(image_path: Path) -> DetailCheckResult:
    with Image.open(image_path) as image:
        rgb = image.convert("RGB")
        width, height = rgb.size
        full_box = (0, 0, width, height)
        eye_box = (int(width * 0.2), int(height * 0.05), int(width * 0.8), int(height * 0.42))
        hand_box = (int(width * 0.12), int(height * 0.52), int(width * 0.88), int(height * 0.96))

        full_score = _region_sharpness(rgb, full_box)
        eye_score = _region_sharpness(rgb, eye_box)
        hand_score = _region_sharpness(rgb, hand_box)
        hand_mean = _region_mean(rgb, hand_box)

        hand_check_skipped = hand_score < full_score * 0.08 and hand_mean < 48
        hand_ok = None if hand_check_skipped else hand_score >= full_score * 0.22
        eye_ok = eye_score >= full_score * 0.18

        return DetailCheckResult(
            hand_check_skipped=hand_check_skipped,
            hand_ok=hand_ok,
            eye_ok=eye_ok,
            hand_score=hand_score,
            eye_score=eye_score,
            full_score=full_score,
        )


def _character_tag_confidence(
    predictions: list,
    character: Character,
    series: Series | None,
) -> tuple[float | None, str | None]:
    if not predictions:
        return None, None

    targets = {_normalize_tag(character.character_tag)}
    if series and series.series_tag:
        targets.add(_normalize_tag(series.series_tag))

    best = 0.0
    best_tag = None
    for item in predictions:
        normalized = _normalize_tag(item.tag)
        if normalized in targets and item.confidence > best:
            best = item.confidence
            best_tag = normalized
    return (best if best > 0 else None), best_tag


def _gender_from_predictions(predictions: list) -> str | None:
    scores = {_normalize_tag(item.tag): item.confidence for item in predictions}
    for tag in ("1girl", "1boy", "no_humans"):
        if tag in scores:
            return tag
    return None


def check_generated_image(
    image_path: Path,
    *,
    character: Character,
    series: Series | None = None,
    character_confidence_threshold: float = 0.35,
) -> ImageAutoCheckResult:
    detail = check_detail_quality(image_path)

    predictions: list = []
    tagger_available = False
    confidence = None
    matched_tag = None

    if CHARACTER_TAG_CHECK_ENABLED:
        from app.integrations.image_tagger.wd14_tagger import TagPrediction, predict_danbooru_tags

        predictions, tagger_available = predict_danbooru_tags(image_path)
        confidence, matched_tag = _character_tag_confidence(predictions, character, series)

    issues: list[str] = []
    if CHARACTER_TAG_CHECK_ENABLED and tagger_available:
        if confidence is None or confidence < character_confidence_threshold:
            issues.append("character_tag_low_confidence")

    if detail.eye_ok is False:
        issues.append("eye_detail_weak")
    if detail.hand_ok is False:
        issues.append("hand_detail_weak")

    if any(issue in issues for issue in ("eye_detail_weak", "hand_detail_weak", "character_tag_low_confidence")):
        auto_status = "reject_candidate"
    else:
        auto_status = "pass"

    payload = {
        "character_tag_check_enabled": CHARACTER_TAG_CHECK_ENABLED,
        "tagger_available": tagger_available,
        "character_tag": character.character_tag,
        "matched_tag": matched_tag,
        "character_confidence": confidence,
        "detail": {
            "hand_check_skipped": detail.hand_check_skipped,
            "hand_ok": detail.hand_ok,
            "eye_ok": detail.eye_ok,
            "hand_score": detail.hand_score,
            "eye_score": detail.eye_score,
            "full_score": detail.full_score,
        },
        "predicted_tags": [
            {"tag": item.tag, "confidence": round(item.confidence, 4)} for item in predictions[:24]
        ],
        "issues": issues,
    }

    cover_score = 0.5
    if detail.eye_ok:
        cover_score += 0.15
    if detail.hand_ok:
        cover_score += 0.15
    elif detail.hand_check_skipped:
        cover_score += 0.05
    if confidence is not None:
        cover_score = confidence
        if detail.eye_ok:
            cover_score += 0.05
        if detail.hand_ok:
            cover_score += 0.05
        elif detail.hand_check_skipped:
            cover_score += 0.02

    gender_pred = None
    if CHARACTER_TAG_CHECK_ENABLED and predictions:
        gender_pred = _gender_from_predictions(predictions)

    return ImageAutoCheckResult(
        auto_status=auto_status,
        auto_tags=json.dumps(payload, ensure_ascii=False),
        hair_match=None,
        eye_match=detail.eye_ok,
        gender_pred=gender_pred,
        cover_score=round(cover_score, 4),
    )
