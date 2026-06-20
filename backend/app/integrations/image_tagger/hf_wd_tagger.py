"""Hugging Face Inference API 기반 WD 태거 (로컬 모델 없이 사용)."""
from __future__ import annotations

import base64
import time
from dataclasses import dataclass
from pathlib import Path

import requests

DEFAULT_HF_WD_MODEL = "SmilingWolf/wd-eva02-large-tagger-v3"
_HF_API_BASE = "https://api-inference.huggingface.co/models"
_TOP_K = 512
_MODEL_LOAD_WAIT = 20.0
_MAX_RETRIES = 3


@dataclass(frozen=True)
class TagPrediction:
    tag: str
    confidence: float


class HFWdTaggerError(Exception):
    pass


class HFWdTagger:
    """Hugging Face Inference API 기반 WD 태거.

    HF Inference API를 사용해 이미지에서 danbooru 스타일 태그를 예측합니다.
    onnxruntime / 로컬 모델 파일이 필요하지 않습니다.
    """

    def __init__(self, hf_token: str, *, model: str = DEFAULT_HF_WD_MODEL) -> None:
        self.hf_token = hf_token
        self.model = model
        self._session = requests.Session()
        self._session.headers["Authorization"] = f"Bearer {hf_token}"

    def predict(
        self,
        image_path: Path,
        *,
        threshold: float = 0.35,
    ) -> list[TagPrediction]:
        """이미지에서 태그를 예측합니다.

        Args:
            image_path: 예측할 이미지 파일 경로
            threshold: 포함할 최소 confidence (0~1)

        Returns:
            TagPrediction 리스트 (confidence 내림차순)

        Raises:
            HFWdTaggerError: API 오류 또는 인증 실패
        """
        url = f"{_HF_API_BASE}/{self.model}"

        with image_path.open("rb") as f:
            image_b64 = base64.b64encode(f.read()).decode("utf-8")

        payload = {
            "inputs": image_b64,
            "parameters": {"top_k": _TOP_K},
        }

        last_error: Exception | None = None
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                resp = self._session.post(url, json=payload, timeout=90.0)
            except requests.RequestException as exc:
                last_error = exc
                if attempt < _MAX_RETRIES:
                    time.sleep(5.0)
                    continue
                raise HFWdTaggerError(f"HF API 네트워크 오류: {exc}") from exc

            if resp.status_code == 503:
                data: dict = {}
                try:
                    data = resp.json()
                except Exception:
                    pass
                wait = float(data.get("estimated_time") or _MODEL_LOAD_WAIT)
                if attempt < _MAX_RETRIES:
                    time.sleep(min(wait, _MODEL_LOAD_WAIT))
                    continue
                raise HFWdTaggerError(
                    f"HF 모델 로딩 대기 초과 ({attempt}회 시도). "
                    "잠시 후 재시도하거나 Settings에서 HF WD Model을 확인하세요."
                )

            if resp.status_code == 401:
                raise HFWdTaggerError(
                    "HF API 인증 실패. Settings에서 HF Token을 확인하세요."
                )

            if resp.status_code == 404:
                raise HFWdTaggerError(
                    f"HF 모델을 찾을 수 없습니다: {self.model}. "
                    "Settings에서 HF WD Model 이름을 확인하세요."
                )

            if resp.status_code != 200:
                raise HFWdTaggerError(
                    f"HF API 오류 HTTP {resp.status_code}: {resp.text[:300]}"
                )

            try:
                data = resp.json()
            except Exception as exc:
                raise HFWdTaggerError(f"HF API 응답 파싱 실패: {exc}") from exc

            if not isinstance(data, list):
                raise HFWdTaggerError(
                    f"HF API 응답 형식 오류: list가 아닌 {type(data).__name__}"
                )

            results: list[TagPrediction] = []
            for item in data:
                if not isinstance(item, dict):
                    continue
                label = str(item.get("label") or "").strip()
                score = float(item.get("score") or 0.0)
                if not label or score < threshold:
                    continue
                # HF가 공백을 반환하는 경우 danbooru 스타일 언더스코어로 변환
                tag = label.replace(" ", "_")
                results.append(TagPrediction(tag=tag, confidence=score))

            results.sort(key=lambda x: x.confidence, reverse=True)
            return results

        raise HFWdTaggerError(f"HF WD 태거 예측 실패: {last_error}")


def predict_tags_via_hf(
    image_path: Path,
    *,
    hf_token: str,
    model: str = DEFAULT_HF_WD_MODEL,
    threshold: float = 0.35,
) -> tuple[list[TagPrediction], str | None]:
    """HF Inference API로 이미지 태그를 예측합니다.

    Returns:
        (predictions, error_message) — 실패 시 predictions=[], error_message=str
    """
    tagger = HFWdTagger(hf_token, model=model)
    try:
        return tagger.predict(image_path, threshold=threshold), None
    except HFWdTaggerError as exc:
        return [], str(exc)
    except Exception as exc:
        return [], f"예기치 않은 오류: {exc}"
