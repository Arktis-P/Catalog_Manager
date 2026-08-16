from __future__ import annotations

from pathlib import Path

from app.integrations.image_tagger import hf_wd_tagger
from app.integrations.image_tagger.wd14_tagger import TagPrediction as LocalTagPrediction
from app.services.identity_checker import check_identity


def test_predict_prefers_existing_local_wd_without_remote_request(
    monkeypatch,
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "image.png"
    image_path.write_bytes(b"placeholder")
    calls = {"local": 0, "remote": 0}

    monkeypatch.setattr(hf_wd_tagger, "local_wd_available", lambda: True)

    def fake_local(*args, **kwargs):
        calls["local"] += 1
        return [LocalTagPrediction(tag="1girl", confidence=0.93)], None

    class RemoteMustNotRun:
        def __init__(self, *args, **kwargs):
            calls["remote"] += 1
            raise AssertionError("remote WD request must not run when local ONNX is available")

    monkeypatch.setattr(hf_wd_tagger, "predict_tags_via_local", fake_local)
    monkeypatch.setattr(hf_wd_tagger, "HFWdTagger", RemoteMustNotRun)

    predictions, error = hf_wd_tagger.predict_tags_via_hf(
        image_path,
        hf_token="configured-but-unneeded",
        threshold=0.15,
    )

    assert error is None
    assert [item.tag for item in predictions] == ["1girl"]
    assert calls == {"local": 1, "remote": 0}


def test_check_identity_allows_local_wd_without_hf_token(
    monkeypatch,
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "image.png"
    image_path.write_bytes(b"placeholder")

    monkeypatch.setattr(hf_wd_tagger, "local_wd_available", lambda: True)

    def fake_predict(*args, **kwargs):
        assert kwargs.get("hf_token") is None
        return (
            [
                hf_wd_tagger.TagPrediction(tag="hakurei_reimu", confidence=0.91),
                hf_wd_tagger.TagPrediction(tag="black_hair", confidence=0.76),
            ],
            None,
        )

    monkeypatch.setattr(hf_wd_tagger, "predict_tags_via_hf", fake_predict)

    result = check_identity(
        image_path,
        character_tag="hakurei_reimu",
        primary_hair_color="black_hair",
        hf_token=None,
    )

    assert result.status == "pass"
    assert result.character_confidence == 0.91
    assert "tagger_unavailable" not in result.reasons
