from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from app.models.character import Character
from app.models.series import Series
from app.services.quality_checker import (
    eye_local_contrast as _eye_local_contrast,
    face_symmetry_score as _face_symmetry_score,
    finger_periodicity as _finger_periodicity,
    region_mean as _region_mean,
    region_sharpness as _region_sharpness,
)


@dataclass
class DetailCheckResult:
    hand_check_skipped: bool
    hand_ok: bool | None
    eye_ok: bool | None
    hand_score: float | None
    eye_score: float | None
    full_score: float
    # 이목구비 균일성
    eye_symmetry: float | None = None       # 눈 영역 좌우 대칭성 (0~1)
    eye_local_contrast: float | None = None # 눈 영역 로컬 고대비 수준 (0~255)
    # 손가락 주기성
    finger_periodicity: float | None = None # FFT 기반 손가락 패턴 점수 (0~1)
    finger_count_est: int | None = None     # 추정 손가락 개수


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


def _parse_appearance_tags(value: str | None) -> list[str]:
    """콤마로 구분된 태그 문자열을 정규화된 태그 리스트로 변환합니다."""
    if not value:
        return []
    return [_normalize_tag(t) for t in value.split(",") if t.strip()]


def check_detail_quality(image_path: Path) -> DetailCheckResult:
    """이미지 품질을 검사합니다.

    - 눈/이목구비: 영역 선명도 + 좌우 대칭성 + 로컬 고대비 확인
    - 손가락: 선명도 + FFT 주기성 분석으로 손가락 수·분리 상태 추정
    """
    with Image.open(image_path) as image:
        rgb = image.convert("RGB")
        width, height = rgb.size

        full_box = (0, 0, width, height)
        # 눈·이목구비 영역: 상단 8%~40%, 좌우 10% 여백
        eye_box = (
            int(width * 0.10), int(height * 0.08),
            int(width * 0.90), int(height * 0.40),
        )
        # 손·손가락 영역: 하단 52%~96%
        hand_box = (
            int(width * 0.08), int(height * 0.52),
            int(width * 0.92), int(height * 0.96),
        )

        full_score = _region_sharpness(rgb, full_box)
        eye_score = _region_sharpness(rgb, eye_box)
        hand_score = _region_sharpness(rgb, hand_box)
        hand_mean = _region_mean(rgb, hand_box)

        # ── 눈/이목구비 품질 ──────────────────────────────────────────
        eye_symmetry = _face_symmetry_score(rgb, eye_box)
        eye_local_contrast = _eye_local_contrast(rgb, eye_box)

        # 기준 (AND 조건 — 세 가지 모두 통과해야 eye_ok):
        #  1. 선명도: 눈 영역이 전체 대비 18% 이상 선명
        #  2. 좌우 대칭성: 55% 이상 (헤어·액세서리 비대칭 감안해 느슨하게)
        #  3. 로컬 고대비: 최대값 30 이상 (눈·동공·하이라이트 명암차 존재)
        eye_ok = (
            eye_score >= full_score * 0.18
            and eye_symmetry >= 0.55
            and eye_local_contrast >= 30.0
        )

        # ── 손/손가락 품질 ────────────────────────────────────────────
        # 손 영역이 어둡고 엣지가 거의 없으면 손이 프레임에 없는 것으로 판단 → skip
        hand_check_skipped = hand_score < full_score * 0.08 and hand_mean < 48

        finger_periodicity: float | None = None
        finger_count_est: int | None = None
        hand_ok: bool | None = None

        if not hand_check_skipped:
            sharpness_ok = hand_score >= full_score * 0.22
            finger_periodicity, finger_count_est = _finger_periodicity(rgb, hand_box)

            # 손가락 OK 판정:
            #   - 주기성이 명확히 낮고(< 0.12) 추정 개수도 비정상(< 3 또는 > 8)이면 경고
            #   - 나머지는 선명도 기준만 적용 (분석 불확실한 경우 보수적으로 패스)
            clearly_bad_fingers = (
                finger_periodicity < 0.12
                and finger_count_est is not None
                and not (3 <= finger_count_est <= 8)
            )
            hand_ok = sharpness_ok and not clearly_bad_fingers

        return DetailCheckResult(
            hand_check_skipped=hand_check_skipped,
            hand_ok=hand_ok,
            eye_ok=eye_ok,
            hand_score=hand_score,
            eye_score=eye_score,
            full_score=full_score,
            eye_symmetry=eye_symmetry,
            eye_local_contrast=eye_local_contrast,
            finger_periodicity=finger_periodicity,
            finger_count_est=finger_count_est,
        )


def _gender_from_predictions(tag_scores: dict[str, float]) -> str | None:
    for tag in ("1girl", "1boy", "no_humans"):
        if tag in tag_scores:
            return tag
    return None


def _check_hair_match(
    tag_scores: dict[str, float],
    character: Character,
    *,
    threshold: float,
) -> bool | None:
    """머리색/머리 스타일 태그가 예측에 포함되는지 확인합니다."""
    hair_tags = _parse_appearance_tags(character.hair_color)
    if character.multi_color_hair:
        # multi_color_hair는 "streaked_hair, white_hair" 등 기본 태그도 포함
        hair_tags += _parse_appearance_tags(character.multi_color_hair)

    if not hair_tags:
        return None  # 비교 불가

    return any(
        tag_scores.get(t, 0.0) >= threshold
        for t in hair_tags
    )


def _check_eye_match(
    tag_scores: dict[str, float],
    character: Character,
    *,
    threshold: float,
) -> bool | None:
    """눈색 태그가 예측에 포함되는지 확인합니다."""
    eye_tags = _parse_appearance_tags(character.eye_color)
    if not eye_tags:
        return None

    # 이색동공의 경우 둘 중 하나가 있으면 매칭
    return any(
        tag_scores.get(t, 0.0) >= threshold
        for t in eye_tags
    )


def _check_character_tag(
    tag_scores: dict[str, float],
    character: Character,
    *,
    threshold: float,
) -> float | None:
    """캐릭터 태그의 confidence를 반환합니다. 없으면 None."""
    char_tag = _normalize_tag(character.character_tag)
    score = tag_scores.get(char_tag)
    if score is not None and score >= threshold:
        return score
    return None


def _determine_auto_status(
    *,
    character_confidence: float | None,
    hair_match: bool | None,
    eye_match: bool | None,
    gender_match: bool | None,
    detail: DetailCheckResult,
    tagger_active: bool,
) -> str:
    """auto_status를 결정합니다.

    Returns:
        "pass" / "warning" / "reject_candidate"
    """
    if not tagger_active:
        # WD 태거 없음: 품질 지표만 사용 (기존 동작)
        if detail.eye_ok is False or detail.hand_ok is False:
            return "reject_candidate"
        return "pass"

    # 캐릭터 태그 직접 감지됨 → pass (품질이 심각하게 나쁘지 않으면)
    if character_confidence is not None:
        if detail.eye_ok is False:
            return "warning"
        return "pass"

    # 캐릭터 태그 미감지 → 외형 태그로 판단
    match_count = sum(1 for v in (hair_match, eye_match, gender_match) if v is True)
    none_count = sum(1 for v in (hair_match, eye_match, gender_match) if v is None)
    # 비교 불가 태그가 많으면 판단 보류 → warning
    if none_count >= 2:
        return "warning"

    if match_count >= 2:
        return "pass" if detail.eye_ok is not False else "warning"
    if match_count == 1:
        return "warning"
    return "reject_candidate"


def _calculate_cover_score(
    *,
    character_confidence: float | None,
    hair_match: bool | None,
    eye_match: bool | None,
    gender_match: bool | None,
    detail: DetailCheckResult,
    tagger_active: bool,
) -> float:
    """커버 이미지 자동 선택에 사용할 점수 (0~1)를 계산합니다."""
    if not tagger_active:
        # 태거 없음: 품질 기반 점수
        score = 0.5
        if detail.eye_ok:
            score += 0.15
        if detail.hand_ok:
            score += 0.15
        elif detail.hand_check_skipped:
            score += 0.05
        return round(min(score, 1.0), 4)

    # 태거 활성: 캐릭터 인식 + 외형 매칭 + 품질
    score = 0.0

    # 캐릭터 태그 인식 (0~0.5)
    if character_confidence is not None:
        score += character_confidence * 0.5
    else:
        score += 0.15  # 미감지 기본값

    # 외형 매칭 (0~0.3)
    if hair_match is True:
        score += 0.15
    elif hair_match is None:
        score += 0.07

    if eye_match is True:
        score += 0.15
    elif eye_match is None:
        score += 0.07

    # 성별 (0~0.1)
    if gender_match is True:
        score += 0.10
    elif gender_match is None:
        score += 0.05

    # 이미지 품질 (0~0.10)
    if detail.eye_ok:
        score += 0.05
    if detail.hand_ok:
        score += 0.05
    elif detail.hand_check_skipped:
        score += 0.02

    return round(min(score, 1.0), 4)


def check_generated_image(
    image_path: Path,
    *,
    character: Character,
    series: Series | None = None,
    character_confidence_threshold: float = 0.35,
    appearance_threshold: float = 0.30,
    hf_token: str | None = None,
    hf_wd_model: str | None = None,
) -> ImageAutoCheckResult:
    """생성된 이미지를 자동 검사합니다.

    HF Token이 설정되어 있으면 WD 태거로 캐릭터 태그·외형·성별을 확인합니다.
    없으면 이미지 품질(선명도) 기반 검사만 수행합니다.
    """
    from app.integrations.image_tagger.hf_wd_tagger import (
        DEFAULT_HF_WD_MODEL,
        predict_tags_via_hf,
    )

    detail = check_detail_quality(image_path)

    tagger_active = False
    tag_scores: dict[str, float] = {}
    predictions_summary: list[dict[str, object]] = []
    tagger_error: str | None = None

    character_confidence: float | None = None
    hair_match: bool | None = None
    eye_match: bool | None = None
    gender_pred: str | None = None
    gender_match: bool | None = None

    if hf_token:
        model = hf_wd_model or DEFAULT_HF_WD_MODEL
        preds, tagger_error = predict_tags_via_hf(
            image_path,
            hf_token=hf_token,
            model=model,
            threshold=min(appearance_threshold, character_confidence_threshold),
        )

        if preds:
            tagger_active = True
            tag_scores = {p.tag: p.confidence for p in preds}
            predictions_summary = [
                {"tag": p.tag, "confidence": round(p.confidence, 4)}
                for p in preds[:32]
            ]

            character_confidence = _check_character_tag(
                tag_scores, character, threshold=character_confidence_threshold
            )
            hair_match = _check_hair_match(
                tag_scores, character, threshold=appearance_threshold
            )
            eye_match = _check_eye_match(
                tag_scores, character, threshold=appearance_threshold
            )
            gender_pred = _gender_from_predictions(tag_scores)
            expected_gender = _normalize_tag(character.gender) if character.gender else None
            if expected_gender and gender_pred:
                gender_match = gender_pred == expected_gender

    auto_status = _determine_auto_status(
        character_confidence=character_confidence,
        hair_match=hair_match,
        eye_match=eye_match,
        gender_match=gender_match,
        detail=detail,
        tagger_active=tagger_active,
    )

    cover_score = _calculate_cover_score(
        character_confidence=character_confidence,
        hair_match=hair_match,
        eye_match=eye_match,
        gender_match=gender_match,
        detail=detail,
        tagger_active=tagger_active,
    )

    payload = {
        "tagger_active": tagger_active,
        "tagger_error": tagger_error,
        "character_tag": character.character_tag,
        "character_confidence": round(character_confidence, 4) if character_confidence else None,
        "hair_match": hair_match,
        "eye_match": eye_match,
        "gender_pred": gender_pred,
        "gender_match": gender_match,
        "detail": {
            "hand_check_skipped": detail.hand_check_skipped,
            "hand_ok": detail.hand_ok,
            "eye_ok": detail.eye_ok,
            "hand_score": round(detail.hand_score, 2) if detail.hand_score is not None else None,
            "eye_score": round(detail.eye_score, 2) if detail.eye_score is not None else None,
            "full_score": round(detail.full_score, 2),
            "eye_symmetry": round(detail.eye_symmetry, 3) if detail.eye_symmetry is not None else None,
            "eye_local_contrast": round(detail.eye_local_contrast, 1) if detail.eye_local_contrast is not None else None,
            "finger_periodicity": round(detail.finger_periodicity, 3) if detail.finger_periodicity is not None else None,
            "finger_count_est": detail.finger_count_est,
        },
        "predicted_tags": predictions_summary,
        "auto_status": auto_status,
    }

    return ImageAutoCheckResult(
        auto_status=auto_status,
        auto_tags=json.dumps(payload, ensure_ascii=False),
        hair_match=hair_match,
        eye_match=eye_match,
        gender_pred=gender_pred,
        cover_score=cover_score,
    )
