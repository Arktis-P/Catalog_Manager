"""Hugging Face-hosted WD tagger integration."""
from __future__ import annotations

import base64
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

DEFAULT_HF_WD_MODEL = "SmilingWolf/wd-eva02-large-tagger-v3"
_HF_ROUTER_BASE = "https://router.huggingface.co/hf-inference/models"
_HF_WHOAMI_URL = "https://huggingface.co/api/whoami-v2"
_TOP_K = 512
_MODEL_LOAD_WAIT = 20.0
_MAX_RETRIES = 3
_TIMEOUT_SECONDS = 90.0
_PREFLIGHT_TIMEOUT_SECONDS = 15.0
logger = logging.getLogger(__name__)

TAGGER_AUTH_ERROR = "tagger_auth_error"
TAGGER_TOKEN_PERMISSION = "tagger_token_permission"
TAGGER_MODEL_NOT_FOUND = "tagger_model_not_found"
TAGGER_MODEL_UNAVAILABLE = "tagger_model_unavailable"
TAGGER_RATE_LIMITED = "tagger_rate_limited"
TAGGER_TIMEOUT = "tagger_timeout"
TAGGER_INVALID_RESPONSE = "tagger_invalid_response"
TAGGER_SERVICE_UNAVAILABLE = "tagger_service_unavailable"
TAGGER_ERROR = "tagger_error"

_RETRYABLE_REASON_CODES = {
    TAGGER_RATE_LIMITED,
    TAGGER_TIMEOUT,
    TAGGER_SERVICE_UNAVAILABLE,
}


@dataclass(frozen=True)
class TagPrediction:
    tag: str
    confidence: float


@dataclass(frozen=True)
class HFTaggerConfigIssue:
    reason_code: str
    message: str
    fatal: bool = True


class HFWdTaggerError(Exception):
    def __init__(self, message: str, reason_code: str = TAGGER_ERROR) -> None:
        super().__init__(message)
        self.reason_code = reason_code


class HFWdTaggerErrorMessage(str):
    """String-compatible error with a stable machine-readable reason code."""

    reason_code: str

    def __new__(cls, value: str, reason_code: str = TAGGER_ERROR):
        obj = str.__new__(cls, value)
        obj.reason_code = reason_code
        return obj


def diagnose_hf_tagger_config(
    *,
    hf_token: str | None,
    model: str | None = None,
    include_model: bool = True,
) -> HFTaggerConfigIssue | None:
    cleaned_token = (hf_token or "").strip()
    cleaned_model = (model or DEFAULT_HF_WD_MODEL).strip() or DEFAULT_HF_WD_MODEL
    if not cleaned_token:
        return HFTaggerConfigIssue(
            TAGGER_AUTH_ERROR,
            "HF token is not configured.",
        )
    if not cleaned_token.startswith("hf_"):
        return HFTaggerConfigIssue(
            TAGGER_AUTH_ERROR,
            "HF token format is invalid; expected a token beginning with hf_.",
        )
    if include_model and cleaned_model == DEFAULT_HF_WD_MODEL:
        return HFTaggerConfigIssue(
            TAGGER_MODEL_UNAVAILABLE,
            (
                "The default WD model is not currently available through the HF "
                "serverless router. Configure a dedicated Hugging Face Inference "
                "Endpoint URL for WD tagging."
            ),
        )
    return None


def _fine_grained_permissions(data: Any) -> tuple[list[Any], list[Any], str | None]:
    if not isinstance(data, dict):
        return [], [], None
    auth = data.get("auth")
    if isinstance(auth, dict):
        access_token = auth.get("accessToken")
        if isinstance(access_token, dict):
            fine_grained = access_token.get("fineGrained")
            role = access_token.get("role")
            if isinstance(fine_grained, dict):
                global_permissions = fine_grained.get("global")
                scoped_permissions = fine_grained.get("scoped")
                scoped_effective_permissions = []
                if isinstance(scoped_permissions, list):
                    for scoped in scoped_permissions:
                        if isinstance(scoped, dict) and isinstance(scoped.get("permissions"), list):
                            scoped_effective_permissions.extend(scoped["permissions"])
                        else:
                            scoped_effective_permissions.append(scoped)
                return (
                    global_permissions if isinstance(global_permissions, list) else [],
                    scoped_effective_permissions,
                    str(role) if role else None,
                )
    fine_grained = data.get("fineGrained")
    if isinstance(fine_grained, dict):
        global_permissions = fine_grained.get("global")
        scoped_permissions = fine_grained.get("scoped")
        return (
            global_permissions if isinstance(global_permissions, list) else [],
            scoped_permissions if isinstance(scoped_permissions, list) else [],
            None,
        )
    return [], [], None


def preflight_hf_tagger_config(
    *,
    hf_token: str | None,
    model: str | None = None,
    session: requests.Session | None = None,
) -> HFTaggerConfigIssue | None:
    issue = diagnose_hf_tagger_config(hf_token=hf_token, model=model, include_model=False)
    if issue is not None:
        return issue

    cleaned_token = (hf_token or "").strip()
    http = session or requests.Session()
    try:
        resp = http.get(
            _HF_WHOAMI_URL,
            headers={"Authorization": f"Bearer {cleaned_token}"},
            timeout=_PREFLIGHT_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        logger.warning("HF token preflight failed before identity recheck: %s", exc)
        return HFTaggerConfigIssue(
            TAGGER_SERVICE_UNAVAILABLE,
            "HF token preflight could not reach Hugging Face.",
            fatal=False,
        )

    if resp.status_code == 401:
        return HFTaggerConfigIssue(
            TAGGER_AUTH_ERROR,
            "HF token is invalid or expired.",
        )
    if resp.status_code == 403:
        return HFTaggerConfigIssue(
            TAGGER_TOKEN_PERMISSION,
            "HF token cannot access Hugging Face account metadata.",
        )
    if resp.status_code != 200:
        return HFTaggerConfigIssue(
            TAGGER_SERVICE_UNAVAILABLE,
            f"HF token preflight failed with HTTP {resp.status_code}.",
            fatal=False,
        )

    try:
        data = resp.json()
    except ValueError:
        return HFTaggerConfigIssue(
            TAGGER_INVALID_RESPONSE,
            "HF token preflight returned invalid JSON.",
            fatal=False,
        )
    global_permissions, scoped_permissions, token_role = _fine_grained_permissions(data)
    if token_role == "fineGrained":
        if not global_permissions and not scoped_permissions:
            return HFTaggerConfigIssue(
                TAGGER_TOKEN_PERMISSION,
                (
                    "HF token is valid but has no fine-grained permissions. "
                    "Grant Inference Providers access or use a token with the required scope."
                ),
            )
    model_issue = diagnose_hf_tagger_config(hf_token=hf_token, model=model, include_model=True)
    if model_issue is not None:
        return model_issue
    return None


def classify_tagger_error(error: str | None) -> str | None:
    if error is None:
        return None
    reason_code = getattr(error, "reason_code", None)
    if isinstance(reason_code, str) and reason_code:
        return reason_code
    prefix = str(error).split(":", 1)[0]
    if prefix in {
        TAGGER_AUTH_ERROR,
        TAGGER_TOKEN_PERMISSION,
        TAGGER_MODEL_NOT_FOUND,
        TAGGER_MODEL_UNAVAILABLE,
        TAGGER_RATE_LIMITED,
        TAGGER_TIMEOUT,
        TAGGER_INVALID_RESPONSE,
        TAGGER_SERVICE_UNAVAILABLE,
        TAGGER_ERROR,
    }:
        return prefix
    return TAGGER_ERROR


class HFWdTagger:
    """Hugging Face router or dedicated endpoint client.

    The old api-inference.huggingface.co/models endpoint is gone. This client
    targets the current HF router by default and also accepts a full HTTPS URL
    in `model` for user-deployed/dedicated inference endpoints.
    """

    def __init__(self, hf_token: str, *, model: str = DEFAULT_HF_WD_MODEL) -> None:
        self.hf_token = hf_token
        self.model = model.strip() or DEFAULT_HF_WD_MODEL
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {hf_token}",
                "Accept": "application/json",
            }
        )

    def _url(self) -> str:
        if self.model.startswith("https://"):
            hostname = (urlparse(self.model).hostname or "").lower()
            if not hostname.endswith(".endpoints.huggingface.cloud"):
                raise HFWdTaggerError(
                    "Dedicated WD endpoint must use the Hugging Face "
                    "*.endpoints.huggingface.cloud domain.",
                    TAGGER_ERROR,
                )
            return self.model
        return f"{_HF_ROUTER_BASE}/{self.model}"

    def _payload(self, image_path: Path) -> dict[str, Any]:
        image_b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
        return {
            "inputs": image_b64,
            "parameters": {"top_k": _TOP_K},
        }

    def _post(self, url: str, image_path: Path) -> requests.Response:
        return self._session.post(
            url,
            json=self._payload(image_path),
            headers={"Content-Type": "application/json"},
            timeout=_TIMEOUT_SECONDS,
        )

    def _log_failure(
        self,
        *,
        url: str,
        error: HFWdTaggerError,
        response: requests.Response | None = None,
    ) -> None:
        body = self._response_message(response) if response is not None else ""
        if self.hf_token:
            body = body.replace(self.hf_token, "[REDACTED]")
        message = str(error)
        if self.hf_token:
            message = message.replace(self.hf_token, "[REDACTED]")
        logger.warning(
            "HF WD inference failed: model=%s url=%s auth_configured=%s "
            "status=%s content_type=%s reason=%s body=%s error=%s",
            self.model,
            url,
            bool(self.hf_token),
            response.status_code if response is not None else None,
            response.headers.get("content-type") if response is not None else None,
            error.reason_code,
            body[:300],
            message,
        )

    @staticmethod
    def _response_message(resp: requests.Response) -> str:
        try:
            data = resp.json()
        except ValueError:
            return resp.text[:300]
        if isinstance(data, dict):
            message = data.get("error") or data.get("message") or data.get("detail")
            if message:
                return str(message)[:300]
        return str(data)[:300]

    @staticmethod
    def _retry_after(resp: requests.Response) -> float:
        header = resp.headers.get("retry-after")
        if header:
            try:
                return max(0.0, min(float(header), _MODEL_LOAD_WAIT))
            except ValueError:
                pass
        try:
            data = resp.json()
        except ValueError:
            data = {}
        if isinstance(data, dict):
            try:
                return max(0.0, min(float(data.get("estimated_time")), _MODEL_LOAD_WAIT))
            except (TypeError, ValueError):
                pass
        return 5.0

    @staticmethod
    def _http_error(resp: requests.Response) -> HFWdTaggerError:
        message = HFWdTagger._response_message(resp)
        if resp.status_code == 401:
            return HFWdTaggerError(
                "HF authentication failed. Check the configured HF token.",
                TAGGER_AUTH_ERROR,
            )
        if resp.status_code == 403:
            return HFWdTaggerError(
                "HF token is valid but does not have permission to use this model or endpoint.",
                TAGGER_TOKEN_PERMISSION,
            )
        if resp.status_code == 404:
            return HFWdTaggerError(
                f"HF model or endpoint is unavailable through the configured route: {message}",
                TAGGER_MODEL_UNAVAILABLE,
            )
        if resp.status_code == 410:
            return HFWdTaggerError(
                "HF legacy inference endpoint is gone; use the HF router or a dedicated endpoint.",
                TAGGER_SERVICE_UNAVAILABLE,
            )
        if resp.status_code == 429:
            return HFWdTaggerError(
                "HF rate limit reached. Retry later or use a dedicated endpoint.",
                TAGGER_RATE_LIMITED,
            )
        if resp.status_code in {502, 503, 504} or resp.status_code >= 500:
            return HFWdTaggerError(
                f"HF inference service unavailable: HTTP {resp.status_code}: {message}",
                TAGGER_SERVICE_UNAVAILABLE,
            )
        return HFWdTaggerError(
            f"HF inference error HTTP {resp.status_code}: {message}",
            TAGGER_ERROR,
        )

    @staticmethod
    def _parse_predictions(data: Any, threshold: float) -> list[TagPrediction]:
        if isinstance(data, list) and len(data) == 1 and isinstance(data[0], list):
            data = data[0]
        if isinstance(data, dict) and isinstance(data.get("predictions"), list):
            data = data["predictions"]
        if not isinstance(data, list):
            raise HFWdTaggerError(
                f"HF response format error: expected list, got {type(data).__name__}",
                TAGGER_INVALID_RESPONSE,
            )

        results: list[TagPrediction] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            label = str(item.get("label") or item.get("tag") or "").strip()
            try:
                score = float(item.get("score", item.get("confidence", 0.0)) or 0.0)
            except (TypeError, ValueError):
                continue
            if not label or score < threshold:
                continue
            results.append(TagPrediction(tag=label.replace(" ", "_"), confidence=score))
        results.sort(key=lambda x: x.confidence, reverse=True)
        return results

    def predict(
        self,
        image_path: Path,
        *,
        threshold: float = 0.35,
    ) -> list[TagPrediction]:
        if not image_path.is_file():
            raise HFWdTaggerError(f"Image file not found: {image_path}", TAGGER_ERROR)

        url = self._url()
        last_error: HFWdTaggerError | None = None
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                resp = self._post(url, image_path)
            except requests.Timeout as exc:
                last_error = HFWdTaggerError(
                    f"HF inference timed out after {_TIMEOUT_SECONDS:.0f}s",
                    TAGGER_TIMEOUT,
                )
                if attempt < _MAX_RETRIES:
                    time.sleep(2.0 * attempt)
                    continue
                self._log_failure(url=url, error=last_error)
                raise last_error from exc
            except requests.RequestException as exc:
                error = HFWdTaggerError(
                    f"HF inference network error: {exc}",
                    TAGGER_SERVICE_UNAVAILABLE,
                )
                self._log_failure(url=url, error=error)
                raise error from exc

            if resp.status_code != 200:
                error = self._http_error(resp)
                last_error = error
                if error.reason_code in _RETRYABLE_REASON_CODES and attempt < _MAX_RETRIES:
                    time.sleep(self._retry_after(resp))
                    continue
                self._log_failure(url=url, error=error, response=resp)
                raise error

            try:
                data = resp.json()
            except ValueError as exc:
                error = HFWdTaggerError(
                    f"HF response JSON parse failed: {exc}",
                    TAGGER_INVALID_RESPONSE,
                )
                self._log_failure(url=url, error=error, response=resp)
                raise error from exc
            try:
                return self._parse_predictions(data, threshold)
            except HFWdTaggerError as error:
                self._log_failure(url=url, error=error, response=resp)
                raise

        raise last_error or HFWdTaggerError("HF WD tagger prediction failed", TAGGER_ERROR)


def predict_tags_via_hf(
    image_path: Path,
    *,
    hf_token: str,
    model: str = DEFAULT_HF_WD_MODEL,
    threshold: float = 0.35,
) -> tuple[list[TagPrediction], str | None]:
    """Predict tags through Hugging Face.

    Returns:
        (predictions, error_message). The error is a string subclass carrying
        `reason_code` for callers that need stable classification.
    """
    tagger = HFWdTagger(hf_token, model=model)
    try:
        return tagger.predict(image_path, threshold=threshold), None
    except HFWdTaggerError as exc:
        return [], HFWdTaggerErrorMessage(str(exc), exc.reason_code)
    except Exception as exc:
        return [], HFWdTaggerErrorMessage(f"Unexpected tagger error: {exc}", TAGGER_ERROR)
