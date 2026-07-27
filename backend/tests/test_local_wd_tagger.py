from __future__ import annotations

from io import BytesIO
from pathlib import Path

import numpy as np
from PIL import Image

from app.integrations.image_tagger import local_wd_tagger
from app.integrations.image_tagger.local_wd_tagger import (
    DEFAULT_LOCAL_WD_MODEL,
    LocalWdModelManager,
    clear_local_wd_tagger_cache,
    get_local_wd_tagger,
    is_local_wd_model_installed,
    local_wd_model_paths,
)


class FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self.status_code = 200
        self.headers = {"content-length": str(len(payload))}
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def iter_content(self, chunk_size: int):
        yield self._payload


class FakeSession:
    def __init__(self) -> None:
        self.urls: list[str] = []

    def get(self, url: str, **kwargs):
        self.urls.append(url)
        if url.endswith("model.onnx"):
            return FakeResponse(b"onnx-bytes")
        return FakeResponse(b"tag_id,name,category,count\n0,hakurei_reimu,4,1\n")


class FakeInput:
    name = "input"
    shape = [None, 4, 4, 3]


class FakeOutput:
    name = "output"


class FakeOrtSession:
    created = 0
    tensors: list[np.ndarray] = []

    def __init__(self, path: str, providers=None) -> None:
        FakeOrtSession.created += 1
        self.path = path

    def get_inputs(self):
        return [FakeInput()]

    def get_outputs(self):
        return [FakeOutput()]

    def run(self, output_names, feeds):
        FakeOrtSession.tensors.append(feeds["input"])
        return [np.array([[0.91, 0.2, 0.7]], dtype=np.float32)]


def _write_installed_model(tmp_path: Path, monkeypatch) -> Path:
    from app import config

    monkeypatch.setattr(config.settings, "project_root", tmp_path)
    monkeypatch.setattr(local_wd_tagger.settings, "project_root", tmp_path)
    paths = local_wd_model_paths(DEFAULT_LOCAL_WD_MODEL)
    paths.cache_dir.mkdir(parents=True)
    paths.model_path.write_bytes(b"placeholder")
    paths.tags_path.write_text(
        "tag_id,name,category,count\n"
        "0,hakurei_reimu,4,100\n"
        "1,low_tag,0,20\n"
        "2,black_hair,0,50\n",
        encoding="utf-8",
    )
    return paths.cache_dir


def test_model_manager_downloads_files_atomically_and_reports_status(tmp_path: Path, monkeypatch) -> None:
    from app import config

    monkeypatch.setattr(config.settings, "project_root", tmp_path)
    monkeypatch.setattr(local_wd_tagger.settings, "project_root", tmp_path)
    manager = LocalWdModelManager()
    fake_session = FakeSession()

    status = manager.download(session=fake_session)

    paths = local_wd_model_paths(DEFAULT_LOCAL_WD_MODEL)
    assert status.installed is True
    assert paths.model_path.read_bytes() == b"onnx-bytes"
    assert "hakurei_reimu" in paths.tags_path.read_text(encoding="utf-8")
    assert not list(paths.cache_dir.glob("*.part"))
    assert len(fake_session.urls) == 2


def test_local_tagger_preprocesses_bgr_nhwc_and_reuses_session(tmp_path: Path, monkeypatch) -> None:
    _write_installed_model(tmp_path, monkeypatch)
    image_path = tmp_path / "transparent.png"
    image = Image.new("RGBA", (2, 1), (255, 0, 0, 128))
    output = BytesIO()
    image.save(output, format="PNG")
    image_path.write_bytes(output.getvalue())
    FakeOrtSession.created = 0
    FakeOrtSession.tensors = []
    monkeypatch.setattr(local_wd_tagger.ort, "InferenceSession", FakeOrtSession)
    clear_local_wd_tagger_cache()

    first = get_local_wd_tagger().predict(image_path, threshold=0.35)
    second = get_local_wd_tagger().predict(image_path, threshold=0.35)

    assert FakeOrtSession.created == 1
    assert [item.tag for item in first] == ["hakurei_reimu", "black_hair"]
    assert [item.tag for item in second] == ["hakurei_reimu", "black_hair"]
    tensor = FakeOrtSession.tensors[0]
    assert tensor.shape == (1, 4, 4, 3)
    assert tensor.dtype == np.float32


def test_is_local_model_installed_uses_project_cache(tmp_path: Path, monkeypatch) -> None:
    from app import config

    monkeypatch.setattr(config.settings, "project_root", tmp_path)
    monkeypatch.setattr(local_wd_tagger.settings, "project_root", tmp_path)
    assert is_local_wd_model_installed() is False
    _write_installed_model(tmp_path, monkeypatch)
    assert is_local_wd_model_installed() is True
