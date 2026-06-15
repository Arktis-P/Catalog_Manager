from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from app.config import settings


@dataclass(frozen=True)
class TagPrediction:
    tag: str
    confidence: float


class Wd14Tagger:
    """Optional WD14 ONNX tagger. Model files are not bundled — place them under input/models/wd14/."""

    def __init__(self, model_dir: Path | None = None) -> None:
        self.model_dir = model_dir or (settings.input_dir / "models" / "wd14")
        self._session = None
        self._tag_names: list[str] = []

    @property
    def available(self) -> bool:
        return self._model_path().exists() and self._tags_path().exists()

    def _model_path(self) -> Path:
        candidates = [
            self.model_dir / "model.onnx",
            self.model_dir / "wd14-convnextv2.onnx",
            self.model_dir / "wd14-vit-v2.onnx",
        ]
        for path in candidates:
            if path.exists():
                return path
        return candidates[0]

    def _tags_path(self) -> Path:
        candidates = [
            self.model_dir / "selected_tags.csv",
            self.model_dir / "tags.csv",
        ]
        for path in candidates:
            if path.exists():
                return path
        return candidates[0]

    def _load(self) -> None:
        if self._session is not None:
            return
        if not self.available:
            raise FileNotFoundError(f"WD14 model not found in {self.model_dir}")

        import numpy as np
        import onnxruntime as ort
        from PIL import Image

        self._numpy = np
        self._Image = Image
        self._session = ort.InferenceSession(
            str(self._model_path()),
            providers=["CPUExecutionProvider"],
        )
        with self._tags_path().open(encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            field = "name" if reader.fieldnames and "name" in reader.fieldnames else reader.fieldnames[0]
            self._tag_names = [row[field].strip() for row in reader if row.get(field)]

    def predict(self, image_path: Path, *, threshold: float = 0.35, limit: int = 64) -> list[TagPrediction]:
        self._load()
        image = self._Image.open(image_path).convert("RGB")
        image = image.resize((448, 448))
        array = self._numpy.asarray(image, dtype=self._numpy.float32) / 255.0
        array = array[:, :, ::-1]  # RGB -> BGR
        array = array.transpose(2, 0, 1)[None, ...]

        input_name = self._session.get_inputs()[0].name
        output_name = self._session.get_outputs()[0].name
        probs = self._session.run([output_name], {input_name: array})[0][0]

        pairs = sorted(
            (
                TagPrediction(tag=self._tag_names[index], confidence=float(score))
                for index, score in enumerate(probs)
                if index < len(self._tag_names) and float(score) >= threshold
            ),
            key=lambda item: item.confidence,
            reverse=True,
        )
        return pairs[:limit]


_tagger: Wd14Tagger | None = None


def predict_danbooru_tags(image_path: Path, *, threshold: float = 0.35) -> tuple[list[TagPrediction], bool]:
    global _tagger
    if _tagger is None:
        _tagger = Wd14Tagger()
    if not _tagger.available:
        return [], False
    try:
        return _tagger.predict(image_path, threshold=threshold), True
    except Exception:
        return [], False
