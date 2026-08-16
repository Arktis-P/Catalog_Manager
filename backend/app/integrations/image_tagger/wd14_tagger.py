"""Local ONNX WaifuDiffusion tagger using an already-downloaded model tree.

Prefers an existing checkout under data/models/wd-tagger/. Never downloads models.
The singleton session and serialized inference keep long pending-review runs from
loading duplicate 400MB-class sessions or multiplying CPU pressure across checker threads.
"""

from __future__ import annotations

import csv
import threading
from dataclasses import dataclass
from pathlib import Path

from app.config import settings

# Same shape as the HF wrapper so callers can share TagPrediction.
@dataclass(frozen=True)
class TagPrediction:
    tag: str
    confidence: float


class LocalWdTaggerError(Exception):
    pass


def candidate_local_model_dirs(project_root: Path | None = None) -> list[Path]:
    root = project_root or settings.project_root
    preferred = root / "data" / "models" / "wd-tagger"
    dirs: list[Path] = []
    if preferred.is_dir():
        # Newest/most complete model directory first.
        for child in sorted(preferred.iterdir(), reverse=True):
            if child.is_dir():
                dirs.append(child)
    dirs.append(root / "input" / "models" / "wd14")
    return dirs


def find_local_model_dir(project_root: Path | None = None) -> Path | None:
    for directory in candidate_local_model_dirs(project_root):
        model = directory / "model.onnx"
        tags = directory / "selected_tags.csv"
        if not tags.exists():
            tags = directory / "tags.csv"
        if model.exists() and tags.exists():
            return directory
    return None


class LocalWdTagger:
    """CPU ONNX tagger compatible with SmilingWolf WD v3 preprocessing."""

    def __init__(self, model_dir: Path | None = None) -> None:
        self.model_dir = model_dir or find_local_model_dir()
        self._session = None
        self._tag_names: list[str] = []
        self._target_size = 448

    @property
    def available(self) -> bool:
        return self.model_dir is not None and self._model_path().exists() and self._tags_path().exists()

    def _model_path(self) -> Path:
        assert self.model_dir is not None
        return self.model_dir / "model.onnx"

    def _tags_path(self) -> Path:
        assert self.model_dir is not None
        csv_path = self.model_dir / "selected_tags.csv"
        return csv_path if csv_path.exists() else self.model_dir / "tags.csv"

    def _load(self) -> None:
        if self._session is not None:
            return
        if not self.available:
            raise LocalWdTaggerError(
                "로컬 WD ONNX 모델이 없습니다. "
                "data/models/wd-tagger/<repo>/model.onnx + selected_tags.csv 가 필요합니다."
            )

        import numpy as np
        import onnxruntime as ort
        from PIL import Image

        self._numpy = np
        self._Image = Image
        self._session = ort.InferenceSession(
            str(self._model_path()),
            providers=["CPUExecutionProvider"],
        )
        input_shape = self._session.get_inputs()[0].shape
        # Expected: [batch, height, width, 3]
        if len(input_shape) >= 3 and isinstance(input_shape[1], int):
            self._target_size = int(input_shape[1])

        with self._tags_path().open(encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            field = "name" if reader.fieldnames and "name" in reader.fieldnames else (reader.fieldnames or ["name"])[0]
            self._tag_names = [row[field].strip() for row in reader if row.get(field)]

    def _prepare(self, image_path: Path):
        image = self._Image.open(image_path).convert("RGBA")
        canvas = self._Image.new("RGBA", image.size, (255, 255, 255))
        canvas.alpha_composite(image)
        image = canvas.convert("RGB")

        max_dim = max(image.size)
        padded = self._Image.new("RGB", (max_dim, max_dim), (255, 255, 255))
        padded.paste(
            image,
            ((max_dim - image.size[0]) // 2, (max_dim - image.size[1]) // 2),
        )
        if max_dim != self._target_size:
            padded = padded.resize((self._target_size, self._target_size), self._Image.BICUBIC)

        array = self._numpy.asarray(padded, dtype=self._numpy.float32)
        array = array[:, :, ::-1]  # RGB -> BGR, keep NHWC
        return self._numpy.expand_dims(array, axis=0)

    def predict(self, image_path: Path, *, threshold: float = 0.35) -> list[TagPrediction]:
        self._load()
        assert self._session is not None
        batch = self._prepare(image_path)
        input_name = self._session.get_inputs()[0].name
        output_name = self._session.get_outputs()[0].name
        probs = self._session.run([output_name], {input_name: batch})[0][0]

        results: list[TagPrediction] = []
        limit = min(len(self._tag_names), len(probs))
        for index in range(limit):
            score = float(probs[index])
            if score < threshold:
                continue
            tag = self._tag_names[index]
            if not tag:
                continue
            results.append(TagPrediction(tag=tag.replace(" ", "_"), confidence=score))
        results.sort(key=lambda item: item.confidence, reverse=True)
        return results


_tagger: LocalWdTagger | None = None
_tagger_init_lock = threading.Lock()
_inference_lock = threading.Lock()


def _shared_tagger() -> LocalWdTagger:
    global _tagger
    if _tagger is None:
        with _tagger_init_lock:
            if _tagger is None:
                _tagger = LocalWdTagger()
    return _tagger


def predict_tags_via_local(
    image_path: Path,
    *,
    threshold: float = 0.35,
    model_dir: Path | None = None,
) -> tuple[list[TagPrediction], str | None]:
    try:
        tagger = LocalWdTagger(model_dir) if model_dir is not None else _shared_tagger()
        if not tagger.available:
            return [], "local_wd_unavailable"
        # Normal V2 generation can submit several checker workers at once. Sharing one
        # large ONNX session is intentional; serialize run/load to avoid duplicate model
        # loads and CPU spikes on a laptop. Pending backfill is already sequential.
        with _inference_lock:
            return tagger.predict(image_path, threshold=threshold), None
    except LocalWdTaggerError as exc:
        return [], str(exc)
    except Exception as exc:
        return [], f"local_wd_error: {exc}"


# Backward-compatible helpers used by older call sites.
class Wd14Tagger(LocalWdTagger):
    """Alias kept for existing imports."""


def predict_danbooru_tags(image_path: Path, *, threshold: float = 0.35) -> tuple[list[TagPrediction], bool]:
    preds, error = predict_tags_via_local(image_path, threshold=threshold)
    return preds, error is None
