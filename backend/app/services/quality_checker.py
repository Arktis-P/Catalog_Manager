from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageChops, ImageFilter, ImageStat, UnidentifiedImageError

from app.integrations.vision.gemini_anatomy import analyze_anatomy

QUALITY_CHECKER_VERSION = "v2.1"

# ── 임계값 (조정 가능) ──────────────────────────────────────────────
# 1단계: 기본 유효성
MIN_WIDTH = 512
MIN_HEIGHT = 512
BLANK_STD_THRESHOLD = 3.0
BLANK_MEAN_LOW = 8.0
BLANK_MEAN_HIGH = 247.0
SEVERE_BLUR_THRESHOLD = 200.0

# 2단계: 얼굴 (보조 지표 — 미검출만으로 reject 금지)
FACE_LOW_CONTRAST_THRESHOLD = 20.0
FACE_LOW_SYMMETRY_THRESHOLD = 0.55
FACE_BLUR_RATIO_THRESHOLD = 0.10

# 3단계: 신체 (보조 지표 — 픽셀 휴리스틱으로 reject 금지)
HAND_SKIP_SHARPNESS_RATIO = 0.08
HAND_SKIP_MEAN_THRESHOLD = 48.0
HAND_BAD_FINGER_PERIODICITY = 0.12
HAND_MIN_FINGER_COUNT = 3
HAND_MAX_FINGER_COUNT = 8


@dataclass(frozen=True)
class QualityCheckResult:
    status: str  # "pass" | "warning" | "reject"
    score: float
    reasons: list[str] = field(default_factory=list)


# ── 공용 픽셀 유틸 (V1 image_auto_checker.py와 V2 모두 이 구현을 사용한다) ──


def region_sharpness(image: Image.Image, box: tuple[int, int, int, int]) -> float:
    crop = image.crop(box).convert("L")
    edges = crop.filter(ImageFilter.FIND_EDGES)
    return float(ImageStat.Stat(edges).var[0])


def region_mean(image: Image.Image, box: tuple[int, int, int, int]) -> float:
    crop = image.crop(box).convert("L")
    return float(ImageStat.Stat(crop).mean[0])


def face_symmetry_score(image: Image.Image, box: tuple[int, int, int, int]) -> float:
    """눈 영역 좌우 대칭성 점수 (0~1).

    두 눈이 비슷한 형태로 생성되었을수록 1에 가깝습니다.
    기울어진 얼굴·머리·액세서리로 인한 자연스러운 비대칭을 고려해 임계값은 느슨하게 설정합니다.
    """
    crop = image.crop(box).convert("L")
    w, h = crop.size
    if w < 8:
        return 1.0

    mid = w // 2
    left = crop.crop((0, 0, mid, h))
    right = crop.crop((w - mid, 0, w, h)).transpose(Image.FLIP_LEFT_RIGHT)

    if left.size != right.size:
        right = right.resize(left.size, Image.LANCZOS)

    diff = ImageChops.difference(left, right)
    mean_diff = ImageStat.Stat(diff).mean[0]
    return max(0.0, 1.0 - mean_diff / 255.0)


def eye_local_contrast(image: Image.Image, box: tuple[int, int, int, int], patch: int = 21) -> float:
    """눈 영역 내 최대 로컬 대비 (0~255).

    MaxFilter - MinFilter 차이의 최대값을 반환합니다.
    눈·홍채·동공·하이라이트처럼 고대비 특성이 영역 내 어딘가에 존재하는지 확인합니다.
    균일한 배경이 넓어도 눈이 제대로 그려졌다면 최대값이 충분히 높게 나옵니다.
    """
    size = patch if patch % 2 == 1 else patch + 1
    crop = image.crop(box).convert("L")

    local_max = crop.filter(ImageFilter.MaxFilter(size=size))
    local_min = crop.filter(ImageFilter.MinFilter(size=size))
    contrast_img = ImageChops.difference(local_max, local_min)

    return float(contrast_img.getextrema()[1])


def finger_periodicity(image: Image.Image, box: tuple[int, int, int, int]) -> tuple[float, int]:
    """PIL 기반 손가락 주기성 분석.

    손가락이 규칙적으로 배열되면 엣지 밀도의 가로 프로파일에 주기적 피크가 나타납니다.
    이미지를 1픽셀 높이로 리사이즈(BOX = 박스 평균)하면 각 열의 평균 엣지 강도를 얻을 수 있고,
    그 프로파일에서 피크 개수를 세어 손가락 개수를 추정합니다.

    Returns:
        (periodicity_score 0~1, estimated_finger_count)
    """
    crop = image.crop(box).convert("L")
    w, h = crop.size
    if w < 20 or h < 20:
        return 0.0, 0

    tip_h = max(h * 45 // 100, 10)
    tip = crop.crop((0, 0, w, tip_h))
    edges = tip.filter(ImageFilter.FIND_EDGES)

    col_profile_img = edges.resize((w, 1), Image.BOX)
    col_profile: list[int] = list(col_profile_img.getdata())

    if max(col_profile) < 1:
        return 0.0, 0

    window = max(w // 20, 3)
    smoothed: list[float] = []
    for i in range(w):
        lo = max(0, i - window // 2)
        hi = min(w, i + window // 2 + 1)
        smoothed.append(sum(col_profile[lo:hi]) / (hi - lo))

    mean_val = sum(smoothed) / len(smoothed)
    peak_threshold = mean_val * 1.2

    min_gap = max(w // 9, 5)

    peaks = 0
    in_peak = False
    last_peak_pos = -min_gap

    for i, val in enumerate(smoothed):
        if val >= peak_threshold and not in_peak:
            if i - last_peak_pos >= min_gap:
                in_peak = True
                peaks += 1
                last_peak_pos = i
        elif val < peak_threshold:
            in_peak = False

    if 4 <= peaks <= 6:
        score = 0.75
    elif 3 <= peaks <= 8:
        score = 0.55
    elif peaks == 2 or peaks == 9:
        score = 0.30
    elif peaks == 0:
        score = 0.0
    else:
        score = 0.10

    return score, peaks


def _quality_score(
    *,
    full_score: float,
    eye_symmetry: float,
    eye_contrast: float,
    reasons: list[str],
) -> float:
    value = 0.55
    value += min(eye_symmetry, 1.0) * 0.2
    value += min(eye_contrast / 100.0, 1.0) * 0.15
    value += min(full_score / 300.0, 1.0) * 0.10
    value -= 0.08 * len(reasons)
    return round(max(0.0, min(1.0, value)), 4)


def _anatomy_settings() -> tuple[bool, str, float]:
    """DB 설정을 읽되, 설정 저장소 문제는 기본 비활성으로 처리한다."""
    try:
        from app.database import SessionLocal
        from app.services.settings_service import (
            DEFAULT_V2_ANATOMY_CHECK_MODEL,
            DEFAULT_V2_ANATOMY_REJECT_CONFIDENCE,
            SettingsService,
        )

        with SessionLocal() as db:
            values = SettingsService(db).get_public_settings()
        return (
            bool(values["v2_anatomy_check_enabled"]),
            str(values["v2_anatomy_check_model"]),
            float(values["v2_anatomy_reject_confidence"]),
        )
    except Exception:
        return False, "gemini-2.5-flash", 0.8


def _apply_anatomy_check(image_path: Path, result: QualityCheckResult) -> QualityCheckResult:
    if result.status == "reject":
        return result

    enabled, model, reject_confidence = _anatomy_settings()
    if not enabled:
        return result

    analysis = analyze_anatomy(image_path, model=model)
    if analysis is None or analysis.verdict == "ok":
        return result

    reasons = list(result.reasons)
    if analysis.verdict == "anomaly" and analysis.confidence >= reject_confidence:
        reasons.extend(reason for reason in analysis.reasons if reason not in reasons)
        return QualityCheckResult(status="reject", score=result.score, reasons=reasons)

    return QualityCheckResult(status="warning", score=result.score, reasons=reasons)


def check_quality(image_path: Path) -> QualityCheckResult:
    """4단계 자동 품질 검사 (기본 유효성 → 얼굴 → 신체 → anatomy).

    1단계에서 명확한 실패만 reject한다. 2·3단계는 보조 지표로만 사용하며,
    단독으로 reject를 발생시키지 않고 warning 사유를 누적한다.
    """
    # ── 1단계: 기본 유효성 ──────────────────────────────────────────
    try:
        with Image.open(image_path) as raw:
            raw.load()
            rgb = raw.convert("RGB")
    except (UnidentifiedImageError, OSError):
        return QualityCheckResult(status="reject", score=0.0, reasons=["decode_failed"])

    width, height = rgb.size
    if width < MIN_WIDTH or height < MIN_HEIGHT:
        return QualityCheckResult(status="reject", score=0.05, reasons=["low_resolution"])

    gray_stat = ImageStat.Stat(rgb.convert("L"))
    mean = gray_stat.mean[0]
    std = gray_stat.stddev[0]
    if std < BLANK_STD_THRESHOLD and (mean <= BLANK_MEAN_LOW or mean >= BLANK_MEAN_HIGH):
        return QualityCheckResult(status="reject", score=0.0, reasons=["blank_image"])

    full_box = (0, 0, width, height)
    full_score = region_sharpness(rgb, full_box)
    if full_score < SEVERE_BLUR_THRESHOLD:
        return QualityCheckResult(status="reject", score=0.1, reasons=["severe_blur"])

    reasons: list[str] = []

    # ── 2단계: 얼굴 검사 (경고만) ────────────────────────────────────
    eye_box = (
        int(width * 0.10), int(height * 0.08),
        int(width * 0.90), int(height * 0.40),
    )
    eye_score = region_sharpness(rgb, eye_box)
    eye_symmetry = face_symmetry_score(rgb, eye_box)
    eye_contrast = eye_local_contrast(rgb, eye_box)

    if eye_contrast < FACE_LOW_CONTRAST_THRESHOLD:
        reasons.append("face_not_detected")
    if eye_symmetry < FACE_LOW_SYMMETRY_THRESHOLD:
        reasons.append("eye_asymmetry")
    if full_score > 0 and eye_score < full_score * FACE_BLUR_RATIO_THRESHOLD:
        reasons.append("face_blur")

    # ── 3단계: 신체 검사 (보조 지표, 경고만) ───────────────────────────
    hand_box = (
        int(width * 0.08), int(height * 0.52),
        int(width * 0.92), int(height * 0.96),
    )
    hand_score = region_sharpness(rgb, hand_box)
    hand_mean = region_mean(rgb, hand_box)
    hand_skipped = hand_score < full_score * HAND_SKIP_SHARPNESS_RATIO and hand_mean < HAND_SKIP_MEAN_THRESHOLD

    if not hand_skipped:
        periodicity, finger_count = finger_periodicity(rgb, hand_box)
        clearly_bad_fingers = (
            periodicity < HAND_BAD_FINGER_PERIODICITY
            and finger_count is not None
            and not (HAND_MIN_FINGER_COUNT <= finger_count <= HAND_MAX_FINGER_COUNT)
        )
        if clearly_bad_fingers:
            reasons.append("hand_anomaly")

    status = "warning" if reasons else "pass"
    score = _quality_score(
        full_score=full_score,
        eye_symmetry=eye_symmetry,
        eye_contrast=eye_contrast,
        reasons=reasons,
    )
    result = QualityCheckResult(status=status, score=score, reasons=reasons)
    return _apply_anatomy_check(image_path, result)
