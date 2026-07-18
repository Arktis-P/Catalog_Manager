"""Gemini Vision 기반 애니메이션 일러스트 신체 구조 검사."""
from __future__ import annotations

import base64
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

import requests

from app.config import settings

DEFAULT_GEMINI_ANATOMY_MODEL = "gemini-2.5-flash"
GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
GEMINI_TIMEOUT_SECONDS = 30.0
GEMINI_MAX_ATTEMPTS = 2

ANATOMY_REASONS = frozenset(
    {
        "body_proportion_anomaly",
        "extra_limb",
        "missing_limb",
        "joint_anomaly",
        "hand_anomaly",
        "finger_count_anomaly",
        "body_fusion",
    }
)

ANATOMY_PROMPT = """\
Analyze this anime-style illustration only for clear anatomical generation errors.
Check body proportions; the number and connection of arms and legs; collapsed or
impossible neck, shoulder, waist, and joint structure; hand structure, finger count,
and fused fingers; and accidental fusion between people. Do not treat intentional
stylization, chibi/cartoon proportions, perspective, foreshortening, or partially
occluded limbs as errors. When the image is ambiguous, return uncertain rather than
anomaly. Return only JSON matching the supplied schema.
"""

_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "verdict": {"type": "STRING", "enum": ["ok", "uncertain", "anomaly"]},
        "reasons": {
            "type": "ARRAY",
            "items": {"type": "STRING", "enum": sorted(ANATOMY_REASONS)},
        },
        "confidence": {"type": "NUMBER", "minimum": 0.0, "maximum": 1.0},
    },
    "required": ["verdict", "reasons", "confidence"],
}


@dataclass(frozen=True)
class AnatomyAnalysis:
    verdict: str
    reasons: list[str]
    confidence: float


def _key_from_env_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeError):
        return None
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip().upper() == "GEMINI_API_KEY":
            cleaned = value.strip().strip('"').strip("'")
            if cleaned and not cleaned.lower().startswith("your_"):
                return cleaned
    return None


def _gemini_api_key() -> str | None:
    env_value = os.getenv("GEMINI_API_KEY", "").strip()
    if env_value:
        return env_value

    input_dir = settings.input_dir
    for filename in ("gemini.env", "danbooru.env"):
        value = _key_from_env_file(input_dir / filename)
        if value:
            return value

    key_file = input_dir / "gemini_api_key.txt"
    try:
        value = key_file.read_text(encoding="utf-8-sig").strip()
    except (OSError, UnicodeError):
        return None
    return value or None


def _image_mime_type(image_path: Path) -> str:
    suffix = image_path.suffix.lower()
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }.get(suffix, "image/png")


def _parse_response(response: requests.Response) -> AnatomyAnalysis | None:
    try:
        payload = response.json()
        text = payload["candidates"][0]["content"]["parts"][0]["text"]
        data = json.loads(text)
        verdict = data["verdict"]
        reasons = data["reasons"]
        confidence = float(data["confidence"])
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError):
        return None

    if verdict not in {"ok", "uncertain", "anomaly"}:
        return None
    if not isinstance(reasons, list) or any(
        not isinstance(reason, str) or reason not in ANATOMY_REASONS for reason in reasons
    ):
        return None
    if not 0.0 <= confidence <= 1.0:
        return None
    return AnatomyAnalysis(verdict=verdict, reasons=list(dict.fromkeys(reasons)), confidence=confidence)


def analyze_anatomy(
    image_path: Path,
    *,
    model: str = DEFAULT_GEMINI_ANATOMY_MODEL,
) -> AnatomyAnalysis | None:
    """이미지를 Gemini로 검사한다. 키 누락 또는 모든 실패는 조용히 ``None``을 반환한다."""
    api_key = _gemini_api_key()
    if not api_key:
        return None

    try:
        image_data = base64.b64encode(image_path.read_bytes()).decode("ascii")
    except OSError:
        return None

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": ANATOMY_PROMPT},
                    {
                        "inline_data": {
                            "mime_type": _image_mime_type(image_path),
                            "data": image_data,
                        }
                    },
                ]
            }
        ],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": _RESPONSE_SCHEMA,
        },
    }
    url = f"{GEMINI_API_BASE}/{model}:generateContent"

    for attempt in range(GEMINI_MAX_ATTEMPTS):
        try:
            response = requests.post(
                url,
                params={"key": api_key},
                json=payload,
                timeout=GEMINI_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            parsed = _parse_response(response)
            if parsed is not None:
                return parsed
        except (requests.RequestException, ValueError):
            pass

        if attempt + 1 < GEMINI_MAX_ATTEMPTS:
            time.sleep(0.25)

    return None
