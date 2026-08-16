"""WD tagger: HF Inference Providers (router) with local ONNX fallback.

The legacy host api-inference.huggingface.co is decommissioned. The current WD models
(SmilingWolf/*-tagger-v3) are also not served by hf-inference providers, so a working
local ONNX checkout under data/models/wd-tagger/ is the supported path today.
"""
from __future__ import annotations

import base64
import time
from dataclasses import dataclass
from pathlib import Path

import requests

from app.integrations.image_tagger.wd14_tagger import (
    TagPrediction as LocalTagPrediction,
    find_local_model_dir,
    predict_tags_via_local,
)

DEFAULT_HF_WD_MODEL = "SmilingWolf/wd-eva02-large-tagger-v3"
# Legacy api-inference.huggingface.co is gone; router is the only public HF entrypoint.
_HF_API_BASE = "https://router.huggingface.co/hf-inference/models"
_TOP_K = 512
_MODEL_LOAD_WAIT = 20.0
_MAX_RETRIES = 3


@dataclass(frozen=True)
class TagPrediction:
    tag: str
    confidence: float


class HFWdTaggerError(Exception):
    pass


def local_wd_available() -> bool:
    return find_local_model_dir() is not None


class HFWdTagger:
    """Hugging Face Inference Providers client for WD-style image tagging."""

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

            if resp.status_code == 400 and "not supported" in resp.text.lower():
                raise HFWdTaggerError(
                    f"HF Inference Provider가 이 WD 모델을 지원하지 않습니다: {self.model}. "
                    "로컬 ONNX(data/models/wd-tagger) 폴백을 사용하거나, "
                    "Inference Provider에 배포된 다른 이미지 태거를 지정하세요."
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
                # Reject opaque class indices — WD needs real Danbooru tag names.
                if label.upper().startswith("LABEL_"):
                    continue
                tag = label.replace(" ", "_")
                results.append(TagPrediction(tag=tag, confidence=score))

            if not results:
                raise HFWdTaggerError(
                    "HF 응답에 Danbooru 태그 label이 없습니다 "
                    "(LABEL_N index만 반환되었거나 점수가 모두 threshold 미만)."
                )

            results.sort(key=lambda x: x.confidence, reverse=True)
            return results

        raise HFWdTaggerError(f"HF WD 태거 예측 실패: {last_error}")


def predict_tags_via_hf(
    image_path: Path,
    *,
    hf_token: str | None = None,
    model: str = DEFAULT_HF_WD_MODEL,
    threshold: float = 0.35,
    allow_local_fallback: bool = True,
) -> tuple[list[TagPrediction], str | None]:
    """Predict WD tags via HF router, falling back to a local ONNX model when needed.

    Returns:
        (predictions, error_message) — 실패 시 predictions=[], error_message=str
    """
    remote_error: str | None = None
    if hf_token:
        tagger = HFWdTagger(hf_token, model=model)
        try:
            return tagger.predict(image_path, threshold=threshold), None
        except HFWdTaggerError as exc:
            remote_error = str(exc)
        except Exception as exc:
            remote_error = f"예기치 않은 HF 오류: {exc}"
    else:
        remote_error = "hf_token_missing"

    if allow_local_fallback and local_wd_available():
        preds, local_error = predict_tags_via_local(image_path, threshold=threshold)
        if local_error is None:
            return [
                TagPrediction(tag=item.tag, confidence=item.confidence)
                for item in preds
            ], None
        return [], (
            f"remote_failed=({remote_error}); local_failed=({local_error})"
        )

    if allow_local_fallback:
        return [], (
            f"{remote_error}; local_wd_unavailable "
            "(data/models/wd-tagger/<repo>/model.onnx + selected_tags.csv 필요). "
            "SmilingWolf WD 모델은 현재 HF Inference Provider에서 제공되지 않습니다."
        )
    return [], remote_error or "tagger_unavailable"


def assert_wd_tagger_ready(*, hf_token: str | None = None, model: str = DEFAULT_HF_WD_MODEL) -> str:
    """Return the backend that will be used, or raise a clear setup error."""
    if local_wd_available():
        directory = find_local_model_dir()
        return f"local:{directory}"
    if hf_token:
        # Probe is intentionally not a full image call: provider support is enough.
        # A later image call may still fail; callers also handle tagger_error without
        # stamping a permanent checker version.
        url = f"{_HF_API_BASE}/{model}"
        try:
            resp = requests.post(
                url,
                headers={"Authorization": f"Bearer {hf_token}"},
                json={"inputs": ""},
                timeout=20,
            )
        except requests.RequestException as exc:
            raise HFWdTaggerError(f"HF WD 태거 연결 실패: {exc}") from exc
        if resp.status_code == 400 and "not supported" in resp.text.lower():
            raise HFWdTaggerError(
                f"HF Provider가 {model} 을(를) 지원하지 않고 로컬 ONNX도 없습니다. "
                "data/models/wd-tagger 에 WD ONNX를 두거나 Provider 지원 모델로 바꾸세요."
            )
        if resp.status_code in {401, 403}:
            raise HFWdTaggerError("HF Token이 Inference Provider 호출에 실패했습니다.")
        return f"remote:{model}"
    raise HFWdTaggerError(
        "WD 태거를 사용할 수 없습니다. 로컬 ONNX(data/models/wd-tagger)가 없고 "
        "HF Token도 없습니다."
    )


# Re-export local prediction type for type checkers that import from this module.
LocalTagPrediction = LocalTagPrediction
