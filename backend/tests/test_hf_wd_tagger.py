from __future__ import annotations

from pathlib import Path

import pytest
import requests

from app.integrations.image_tagger.hf_wd_tagger import (
    DEFAULT_HF_WD_MODEL,
    HFWdTagger,
    TAGGER_AUTH_ERROR,
    TAGGER_INVALID_RESPONSE,
    TAGGER_MODEL_UNAVAILABLE,
    TAGGER_RATE_LIMITED,
    TAGGER_SERVICE_UNAVAILABLE,
    TAGGER_TOKEN_PERMISSION,
    TAGGER_TIMEOUT,
    classify_tagger_error,
    preflight_hf_tagger_config,
    predict_tags_via_hf,
)


class FakeResponse:
    def __init__(self, status_code: int, payload, headers: dict[str, str] | None = None) -> None:
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}
        self.text = str(payload)

    def json(self):
        if isinstance(self._payload, BaseException):
            raise self._payload
        return self._payload


def test_hf_tagger_uses_current_router_and_base64_json(monkeypatch, tmp_path: Path) -> None:
    image_path = tmp_path / "image.png"
    image_path.write_bytes(b"image-bytes")
    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse(
            200,
            [
                {"label": "hakurei reimu", "score": 0.92},
                {"label": "low", "score": 0.1},
            ],
        )

    tagger = HFWdTagger("secret-token", model=DEFAULT_HF_WD_MODEL)
    monkeypatch.setattr(tagger._session, "post", fake_post)

    predictions = tagger.predict(image_path, threshold=0.35)

    assert calls[0][0] == (
        "https://router.huggingface.co/hf-inference/models/"
        "SmilingWolf/wd-eva02-large-tagger-v3"
    )
    assert "secret-token" not in str(calls[0][1]["json"])
    assert calls[0][1]["json"]["inputs"]
    assert calls[0][1]["json"]["parameters"]["top_k"] == 512
    assert predictions[0].tag == "hakurei_reimu"
    assert predictions[0].confidence == 0.92


def test_hf_tagger_accepts_dedicated_https_endpoint(monkeypatch, tmp_path: Path) -> None:
    image_path = tmp_path / "image.png"
    image_path.write_bytes(b"image-bytes")
    calls = []

    def fake_post(url, **kwargs):
        calls.append(url)
        return FakeResponse(200, [{"label": "black hair", "score": 0.8}])

    tagger = HFWdTagger(
        "secret-token",
        model="https://catalogue.endpoints.huggingface.cloud",
    )
    monkeypatch.setattr(tagger._session, "post", fake_post)

    predictions = tagger.predict(image_path)

    assert calls == ["https://catalogue.endpoints.huggingface.cloud"]
    assert predictions[0].tag == "black_hair"


def test_hf_tagger_rejects_untrusted_dedicated_endpoint(tmp_path: Path) -> None:
    image_path = tmp_path / "image.png"
    image_path.write_bytes(b"image-bytes")

    predictions, error = predict_tags_via_hf(
        image_path,
        hf_token="secret-token",
        model="https://example.invalid/collect-token",
    )

    assert predictions == []
    assert classify_tagger_error(error) == "tagger_error"
    assert "secret-token" not in str(error)


@pytest.mark.parametrize(
    ("status_code", "expected_reason"),
    [
        (401, TAGGER_AUTH_ERROR),
        (403, TAGGER_TOKEN_PERMISSION),
        (404, TAGGER_MODEL_UNAVAILABLE),
        (410, TAGGER_SERVICE_UNAVAILABLE),
        (429, TAGGER_RATE_LIMITED),
        (503, TAGGER_SERVICE_UNAVAILABLE),
    ],
)
def test_predict_tags_via_hf_classifies_http_errors(
    monkeypatch, tmp_path: Path, status_code: int, expected_reason: str
) -> None:
    image_path = tmp_path / "image.png"
    image_path.write_bytes(b"image-bytes")

    def fake_post(self, url, **kwargs):
        return FakeResponse(status_code, {"error": "not available"})

    monkeypatch.setattr(requests.Session, "post", fake_post)
    monkeypatch.setattr("app.integrations.image_tagger.hf_wd_tagger.time.sleep", lambda _: None)

    predictions, error = predict_tags_via_hf(
        image_path,
        hf_token="secret-token",
        model="test/model",
    )

    assert predictions == []
    assert classify_tagger_error(error) == expected_reason
    assert "secret-token" not in str(error)


def test_predict_tags_via_hf_classifies_timeout(monkeypatch, tmp_path: Path) -> None:
    image_path = tmp_path / "image.png"
    image_path.write_bytes(b"image-bytes")

    def fake_post(self, url, **kwargs):
        raise requests.Timeout("slow")

    monkeypatch.setattr(requests.Session, "post", fake_post)
    monkeypatch.setattr("app.integrations.image_tagger.hf_wd_tagger.time.sleep", lambda _: None)

    predictions, error = predict_tags_via_hf(image_path, hf_token="secret-token")

    assert predictions == []
    assert classify_tagger_error(error) == TAGGER_TIMEOUT


def test_predict_tags_via_hf_classifies_invalid_response(monkeypatch, tmp_path: Path) -> None:
    image_path = tmp_path / "image.png"
    image_path.write_bytes(b"image-bytes")

    def fake_post(self, url, **kwargs):
        return FakeResponse(200, {"unexpected": "shape"})

    monkeypatch.setattr(requests.Session, "post", fake_post)

    predictions, error = predict_tags_via_hf(image_path, hf_token="secret-token")

    assert predictions == []
    assert classify_tagger_error(error) == TAGGER_INVALID_RESPONSE


def test_preflight_distinguishes_permissionless_fine_grained_token() -> None:
    class FakeSession:
        def get(self, url, **kwargs):
            return FakeResponse(
                200,
                {
                    "auth": {
                        "accessToken": {
                            "role": "fineGrained",
                            "fineGrained": {"global": [], "scoped": []},
                        }
                    }
                },
            )

    issue = preflight_hf_tagger_config(
        hf_token="hf_secret",
        model="https://catalogue.endpoints.huggingface.cloud",
        session=FakeSession(),
    )

    assert issue is not None
    assert issue.reason_code == TAGGER_TOKEN_PERMISSION
    assert "hf_secret" not in issue.message


def test_preflight_rejects_default_router_model_without_image_request() -> None:
    class FakeSession:
        def get(self, url, **kwargs):
            return FakeResponse(200, {"auth": {"accessToken": {"role": "write"}}})

    issue = preflight_hf_tagger_config(
        hf_token="hf_secret",
        model=DEFAULT_HF_WD_MODEL,
        session=FakeSession(),
    )

    assert issue is not None
    assert issue.reason_code == TAGGER_MODEL_UNAVAILABLE
