from __future__ import annotations

import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from app.services.quality_checker import check_quality

WIDTH = 560
HEIGHT = 760


def _hand_box(width: int, height: int) -> tuple[int, int, int, int]:
    return (
        int(width * 0.08), int(height * 0.52),
        int(width * 0.92), int(height * 0.96),
    )


def _save(image: Image.Image, path: Path) -> Path:
    image.save(path)
    return path


def _black_image(tmp_path: Path) -> Path:
    return _save(Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0)), tmp_path / "black.png")


def _white_image(tmp_path: Path) -> Path:
    return _save(Image.new("RGB", (WIDTH, HEIGHT), (255, 255, 255)), tmp_path / "white.png")


def _noise_image(tmp_path: Path) -> Path:
    rng = random.Random(42)
    data = bytes(rng.randbytes(WIDTH * HEIGHT * 3))
    image = Image.frombytes("RGB", (WIDTH, HEIGHT), data)
    return _save(image, tmp_path / "noise.png")


def _normal_pattern_image(tmp_path: Path) -> Path:
    """눈처럼 대칭·고대비인 형태를 얼굴 영역에 그리고, 손 영역은 어둡게 채워
    (손 미검출로 skip 되도록) 만든 '정상' 합성 이미지."""
    image = Image.new("RGB", (WIDTH, HEIGHT), (200, 200, 200))
    draw = ImageDraw.Draw(image)
    draw.ellipse((165, 145, 235, 215), fill=(30, 30, 30))
    draw.ellipse((325, 145, 395, 215), fill=(30, 30, 30))
    draw.rectangle(_hand_box(WIDTH, HEIGHT), fill=(10, 10, 10))
    return _save(image, tmp_path / "normal.png")


def _severely_blurred_image(tmp_path: Path) -> Path:
    """굵은 체크무늬를 강하게 GaussianBlur해 고주파 엣지를 제거한 이미지 —
    전체적인 명암 기복은 남아 blank로 분류되지 않으면서 심각한 흐림으로 판정돼야 한다."""
    image = Image.new("RGB", (WIDTH, HEIGHT), (150, 150, 150))
    draw = ImageDraw.Draw(image)
    draw.ellipse((200, 300, 360, 460), fill=(90, 90, 90))
    blurred = image.filter(ImageFilter.GaussianBlur(radius=60))
    return _save(blurred, tmp_path / "blurred.png")


def test_black_image_is_rejected_as_blank(tmp_path: Path) -> None:
    result = check_quality(_black_image(tmp_path))
    assert result.status == "reject"
    assert "blank_image" in result.reasons


def test_white_image_is_rejected_as_blank(tmp_path: Path) -> None:
    result = check_quality(_white_image(tmp_path))
    assert result.status == "reject"
    assert "blank_image" in result.reasons


def test_noise_image_is_never_rejected_for_missing_face_alone(tmp_path: Path) -> None:
    """얼굴 미검출/이목구비 이상만으로는 reject하지 않는다 (WP4 §1 얼굴 검사 규칙)."""
    result = check_quality(_noise_image(tmp_path))
    assert result.status != "reject"
    assert 0.0 <= result.score <= 1.0


def test_normal_pattern_image_passes(tmp_path: Path) -> None:
    result = check_quality(_normal_pattern_image(tmp_path))
    assert result.status == "pass"
    assert result.reasons == []
    assert result.score > 0.5


def test_severely_blurred_image_is_rejected(tmp_path: Path) -> None:
    result = check_quality(_severely_blurred_image(tmp_path))
    assert result.status == "reject"
    assert "severe_blur" in result.reasons


def test_low_resolution_image_is_rejected(tmp_path: Path) -> None:
    path = _save(Image.new("RGB", (200, 200), (120, 120, 120)), tmp_path / "small.png")
    result = check_quality(path)
    assert result.status == "reject"
    assert "low_resolution" in result.reasons


def test_undecodable_file_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "broken.png"
    path.write_bytes(b"not a real image" * 10)
    result = check_quality(path)
    assert result.status == "reject"
    assert "decode_failed" in result.reasons
