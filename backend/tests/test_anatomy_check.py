from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock

import requests
from PIL import Image, ImageDraw

from app.integrations.vision import gemini_anatomy
from app.integrations.vision.gemini_anatomy import AnatomyAnalysis
from app.services import quality_checker

WIDTH = 560
HEIGHT = 760


def _normal_image(tmp_path: Path) -> Path:
    image = Image.new("RGB", (WIDTH, HEIGHT), (200, 200, 200))
    draw = ImageDraw.Draw(image)
    draw.ellipse((165, 145, 235, 215), fill=(30, 30, 30))
    draw.ellipse((325, 145, 395, 215), fill=(30, 30, 30))
    draw.rectangle(
        (int(WIDTH * 0.08), int(HEIGHT * 0.52), int(WIDTH * 0.92), int(HEIGHT * 0.96)),
        fill=(10, 10, 10),
    )
    path = tmp_path / "normal.png"
    image.save(path)
    return path


def _enable_anatomy(monkeypatch, *, threshold: float = 0.8) -> None:
    monkeypatch.setattr(
        quality_checker,
        "_anatomy_settings",
        lambda: (True, "gemini-test-model", threshold),
    )


def test_high_confidence_anomaly_rejects_and_merges_reasons(tmp_path: Path, monkeypatch) -> None:
    _enable_anatomy(monkeypatch)
    monkeypatch.setattr(
        quality_checker,
        "analyze_anatomy",
        lambda *_args, **_kwargs: AnatomyAnalysis(
            verdict="anomaly", reasons=["extra_limb", "joint_anomaly"], confidence=0.91
        ),
    )

    result = quality_checker.check_quality(_normal_image(tmp_path))

    assert result.status == "reject"
    assert result.reasons == ["extra_limb", "joint_anomaly"]


def test_low_confidence_anomaly_warns(tmp_path: Path, monkeypatch) -> None:
    _enable_anatomy(monkeypatch, threshold=0.8)
    monkeypatch.setattr(
        quality_checker,
        "analyze_anatomy",
        lambda *_args, **_kwargs: AnatomyAnalysis(
            verdict="anomaly", reasons=["hand_anomaly"], confidence=0.79
        ),
    )

    result = quality_checker.check_quality(_normal_image(tmp_path))

    assert result.status == "warning"


def test_uncertain_anatomy_warns(tmp_path: Path, monkeypatch) -> None:
    _enable_anatomy(monkeypatch)
    monkeypatch.setattr(
        quality_checker,
        "analyze_anatomy",
        lambda *_args, **_kwargs: AnatomyAnalysis(
            verdict="uncertain", reasons=[], confidence=0.6
        ),
    )

    result = quality_checker.check_quality(_normal_image(tmp_path))

    assert result.status == "warning"


def test_ok_anatomy_preserves_existing_result(tmp_path: Path, monkeypatch) -> None:
    _enable_anatomy(monkeypatch)
    monkeypatch.setattr(
        quality_checker,
        "analyze_anatomy",
        lambda *_args, **_kwargs: AnatomyAnalysis(verdict="ok", reasons=[], confidence=0.97),
    )

    result = quality_checker.check_quality(_normal_image(tmp_path))

    assert result.status == "pass"
    assert result.reasons == []


def test_anatomy_failure_preserves_existing_result(tmp_path: Path, monkeypatch) -> None:
    _enable_anatomy(monkeypatch)
    monkeypatch.setattr(quality_checker, "analyze_anatomy", lambda *_args, **_kwargs: None)

    result = quality_checker.check_quality(_normal_image(tmp_path))

    assert result.status == "pass"
    assert "anatomy_check_skipped" not in result.reasons


def test_disabled_anatomy_does_not_call_gemini(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        quality_checker,
        "_anatomy_settings",
        lambda: (False, "gemini-test-model", 0.8),
    )
    analyzer = Mock(side_effect=AssertionError("Gemini must not be called when disabled"))
    monkeypatch.setattr(quality_checker, "analyze_anatomy", analyzer)

    result = quality_checker.check_quality(_normal_image(tmp_path))

    assert result.status == "pass"
    analyzer.assert_not_called()


def test_gemini_rest_call_uses_json_schema_and_parses_response(tmp_path: Path, monkeypatch) -> None:
    image_path = _normal_image(tmp_path)
    monkeypatch.setattr(gemini_anatomy, "_gemini_api_key", lambda: "mock-api-key")

    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": json.dumps(
                                {
                                    "verdict": "anomaly",
                                    "reasons": ["body_fusion"],
                                    "confidence": 0.88,
                                }
                            )
                        }
                    ]
                }
            }
        ]
    }
    post = Mock(return_value=response)
    monkeypatch.setattr(gemini_anatomy.requests, "post", post)

    result = gemini_anatomy.analyze_anatomy(image_path, model="gemini-test-model")

    assert result == AnatomyAnalysis(verdict="anomaly", reasons=["body_fusion"], confidence=0.88)
    call = post.call_args
    assert call.args[0].endswith("/gemini-test-model:generateContent")
    assert call.kwargs["params"] == {"key": "mock-api-key"}
    assert call.kwargs["json"]["generationConfig"]["responseMimeType"] == "application/json"
    assert call.kwargs["json"]["generationConfig"]["responseSchema"]["required"] == [
        "verdict",
        "reasons",
        "confidence",
    ]


def test_gemini_failure_retries_once_then_returns_none(tmp_path: Path, monkeypatch) -> None:
    image_path = _normal_image(tmp_path)
    monkeypatch.setattr(gemini_anatomy, "_gemini_api_key", lambda: "mock-api-key")
    post = Mock(side_effect=requests.Timeout("mock timeout"))
    monkeypatch.setattr(gemini_anatomy.requests, "post", post)
    monkeypatch.setattr(gemini_anatomy.time, "sleep", lambda _seconds: None)

    result = gemini_anatomy.analyze_anatomy(image_path)

    assert result is None
    assert post.call_count == 2
