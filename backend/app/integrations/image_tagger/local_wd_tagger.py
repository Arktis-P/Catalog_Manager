"""Local ONNX WD tagger integration."""
from __future__ import annotations

import csv
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

import numpy as np
import onnxruntime as ort
import requests
from PIL import Image

from app.config import settings
from app.integrations.image_tagger.hf_wd_tagger import (
    HFWdTaggerErrorMessage,
    TAGGER_ERROR,
    TAGGER_INVALID_RESPONSE,
    TAGGER_MODEL_UNAVAILABLE,
    TAGGER_SERVICE_UNAVAILABLE,
    TAGGER_TIMEOUT,
    TagPrediction,
)

DEFAULT_LOCAL_WD_MODEL = "SmilingWolf/wd-swinv2-tagger-v3"
MODEL_FILENAME = "model.onnx"
TAGS_FILENAME = "selected_tags.csv"
_DOWNLOAD_TIMEOUT = (15.0, 300.0)
_CHUNK_SIZE = 1024 * 1024


class LocalWdTaggerError(Exception):
    def __init__(self, message: str, reason_code: str = TAGGER_ERROR) -> None:
        super().__init__(message)
        self.reason_code = reason_code


@dataclass(frozen=True)
class LocalWdModelPaths:
    repo_id: str
    cache_dir: Path
    model_path: Path
    tags_path: Path


@dataclass
class LocalWdModelStatus:
    repo_id: str = DEFAULT_LOCAL_WD_MODEL
    cache_dir: str = ""
    installed: bool = False
    downloading: bool = False
    bytes_downloaded: int = 0
    total_bytes: int | None = None
    current_file: str | None = None
    error: str | None = None
    updated_at: float = field(default_factory=time.time)


def _safe_repo_id(repo_id: str) -> str:
    return repo_id.strip().replace("/", "__")


def local_wd_model_paths(repo_id: str = DEFAULT_LOCAL_WD_MODEL) -> LocalWdModelPaths:
    cache_dir = settings.project_root / "data" / "models" / "wd-tagger" / _safe_repo_id(repo_id)
    return LocalWdModelPaths(
        repo_id=repo_id,
        cache_dir=cache_dir,
        model_path=cache_dir / MODEL_FILENAME,
        tags_path=cache_dir / TAGS_FILENAME,
    )


def is_local_wd_model_installed(repo_id: str = DEFAULT_LOCAL_WD_MODEL) -> bool:
    paths = local_wd_model_paths(repo_id)
    return paths.model_path.is_file() and paths.tags_path.is_file()


def local_wd_model_status(repo_id: str = DEFAULT_LOCAL_WD_MODEL) -> LocalWdModelStatus:
    return local_wd_model_manager.status(repo_id)


class LocalWdModelManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._statuses: dict[str, LocalWdModelStatus] = {}
        self._active: set[str] = set()
        self._cancel_events: dict[str, threading.Event] = {}

    def status(self, repo_id: str = DEFAULT_LOCAL_WD_MODEL) -> LocalWdModelStatus:
        paths = local_wd_model_paths(repo_id)
        with self._lock:
            status = self._statuses.get(repo_id)
            if status is None:
                status = LocalWdModelStatus(repo_id=repo_id, cache_dir=str(paths.cache_dir))
                self._statuses[repo_id] = status
            status.cache_dir = str(paths.cache_dir)
            status.installed = is_local_wd_model_installed(repo_id)
            status.downloading = repo_id in self._active
            status.updated_at = time.time()
            return LocalWdModelStatus(**status.__dict__)

    def download(
        self,
        repo_id: str = DEFAULT_LOCAL_WD_MODEL,
        *,
        session: requests.Session | None = None,
        cancel_event: threading.Event | None = None,
    ) -> LocalWdModelStatus:
        paths = local_wd_model_paths(repo_id)
        with self._lock:
            if repo_id in self._active:
                if cancel_event is None or self._cancel_events.get(repo_id) is not cancel_event:
                    raise LocalWdTaggerError(
                        "WD model download is already in progress.",
                        TAGGER_SERVICE_UNAVAILABLE,
                    )
            else:
                self._active.add(repo_id)
            status = self._statuses.setdefault(repo_id, LocalWdModelStatus(repo_id=repo_id))
            status.cache_dir = str(paths.cache_dir)
            status.downloading = True
            status.error = None
            status.bytes_downloaded = 0
            status.total_bytes = None
            status.updated_at = time.time()
        try:
            paths.cache_dir.mkdir(parents=True, exist_ok=True)
            http = session or requests.Session()
            self._download_file(http, repo_id, MODEL_FILENAME, paths.model_path, cancel_event)
            self._download_file(http, repo_id, TAGS_FILENAME, paths.tags_path, cancel_event)
            return self.status(repo_id)
        except Exception as exc:
            reason = getattr(exc, "reason_code", TAGGER_ERROR)
            with self._lock:
                status.error = str(exc)
                status.downloading = False
                status.updated_at = time.time()
            if isinstance(exc, LocalWdTaggerError):
                raise
            raise LocalWdTaggerError(f"WD model download failed: {exc}", reason) from exc
        finally:
            with self._lock:
                self._active.discard(repo_id)
                self._cancel_events.pop(repo_id, None)
                status = self._statuses.setdefault(repo_id, LocalWdModelStatus(repo_id=repo_id))
                status.downloading = False
                status.installed = is_local_wd_model_installed(repo_id)
                status.updated_at = time.time()

    def start_download(
        self,
        repo_id: str = DEFAULT_LOCAL_WD_MODEL,
        *,
        session: requests.Session | None = None,
    ) -> LocalWdModelStatus:
        with self._lock:
            if repo_id in self._active:
                cancel_event = None
            else:
                cancel_event = threading.Event()
                self._active.add(repo_id)
                self._cancel_events[repo_id] = cancel_event
                status = self._statuses.setdefault(repo_id, LocalWdModelStatus(repo_id=repo_id))
                status.cache_dir = str(local_wd_model_paths(repo_id).cache_dir)
                status.downloading = True
                status.error = None
                status.updated_at = time.time()
        if cancel_event is None:
            return self.status(repo_id)

        def run() -> None:
            try:
                self.download(repo_id, session=session, cancel_event=cancel_event)
            except LocalWdTaggerError:
                pass

        thread = threading.Thread(
            target=run,
            daemon=True,
            name=f"wd-model-download-{_safe_repo_id(repo_id)[:24]}",
        )
        thread.start()
        return self.status(repo_id)

    def cancel_download(self, repo_id: str = DEFAULT_LOCAL_WD_MODEL) -> bool:
        with self._lock:
            event = self._cancel_events.get(repo_id)
            if event is None:
                return False
            event.set()
            status = self._statuses.setdefault(repo_id, LocalWdModelStatus(repo_id=repo_id))
            status.error = "WD model download cancellation requested."
            status.updated_at = time.time()
            return True

    def _download_file(
        self,
        http: requests.Session,
        repo_id: str,
        filename: str,
        destination: Path,
        cancel_event: threading.Event | None,
    ) -> None:
        if destination.is_file() and destination.stat().st_size > 0:
            return
        url = f"https://huggingface.co/{repo_id}/resolve/main/{filename}"
        tmp_path: Path | None = None
        try:
            with http.get(url, stream=True, timeout=_DOWNLOAD_TIMEOUT) as resp:
                if resp.status_code != 200:
                    raise LocalWdTaggerError(
                        f"WD model download failed for {filename}: HTTP {resp.status_code}",
                        TAGGER_SERVICE_UNAVAILABLE,
                    )
                total = _content_length(resp)
                with self._lock:
                    status = self._statuses.setdefault(repo_id, LocalWdModelStatus(repo_id=repo_id))
                    status.current_file = filename
                    status.total_bytes = total
                    status.bytes_downloaded = 0
                    status.updated_at = time.time()
                with NamedTemporaryFile(
                    mode="wb",
                    suffix=f".{filename}.part",
                    dir=destination.parent,
                    delete=False,
                ) as tmp:
                    tmp_path = Path(tmp.name)
                    for chunk in resp.iter_content(chunk_size=_CHUNK_SIZE):
                        if cancel_event is not None and cancel_event.is_set():
                            raise LocalWdTaggerError("WD model download cancelled.", TAGGER_ERROR)
                        if not chunk:
                            continue
                        tmp.write(chunk)
                        with self._lock:
                            status.bytes_downloaded += len(chunk)
                            status.updated_at = time.time()
                if total is not None and tmp_path.stat().st_size != total:
                    raise LocalWdTaggerError(
                        f"WD model download was incomplete for {filename}.",
                        TAGGER_SERVICE_UNAVAILABLE,
                    )
                os.replace(tmp_path, destination)
                tmp_path = None
        except requests.Timeout as exc:
            raise LocalWdTaggerError("WD model download timed out.", TAGGER_TIMEOUT) from exc
        except requests.RequestException as exc:
            raise LocalWdTaggerError(f"WD model download network error: {exc}", TAGGER_SERVICE_UNAVAILABLE) from exc
        finally:
            if tmp_path is not None:
                try:
                    tmp_path.unlink(missing_ok=True)
                except OSError:
                    pass


def _content_length(resp: requests.Response) -> int | None:
    value = resp.headers.get("content-length")
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _load_tag_names(tags_path: Path) -> list[str]:
    with tags_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or "name" not in reader.fieldnames:
            raise LocalWdTaggerError("WD selected_tags.csv is missing a name column.", TAGGER_INVALID_RESPONSE)
        names: list[str] = []
        for row in reader:
            name = (row.get("name") or "").strip()
            if not name:
                continue
            try:
                int(row.get("category") or 0)
            except ValueError:
                raise LocalWdTaggerError(
                    "WD selected_tags.csv has an invalid category value.",
                    TAGGER_INVALID_RESPONSE,
                ) from None
            names.append(name.replace(" ", "_"))
    if not names:
        raise LocalWdTaggerError("WD selected_tags.csv has no tags.", TAGGER_INVALID_RESPONSE)
    return names


class LocalWdTagger:
    def __init__(self, repo_id: str = DEFAULT_LOCAL_WD_MODEL) -> None:
        paths = local_wd_model_paths(repo_id)
        if not paths.model_path.is_file() or not paths.tags_path.is_file():
            raise LocalWdTaggerError(
                f"Local WD model is not installed at {paths.cache_dir}.",
                TAGGER_MODEL_UNAVAILABLE,
            )
        self.repo_id = repo_id
        self.paths = paths
        self._session = ort.InferenceSession(str(paths.model_path), providers=["CPUExecutionProvider"])
        self._input = self._session.get_inputs()[0]
        self._output_name = self._session.get_outputs()[0].name
        self._tag_names = _load_tag_names(paths.tags_path)
        self._run_lock = threading.Lock()

    @property
    def input_size(self) -> int:
        shape = list(self._input.shape)
        for value in shape[1:3]:
            if isinstance(value, int) and value > 0:
                return value
        return 448

    def predict(self, image_path: Path, *, threshold: float = 0.35) -> list[TagPrediction]:
        if not image_path.is_file():
            raise LocalWdTaggerError(f"Image file not found: {image_path}", TAGGER_ERROR)
        tensor = self._preprocess(image_path)
        with self._run_lock:
            output = self._session.run([self._output_name], {self._input.name: tensor})[0]
        scores = np.asarray(output, dtype=np.float32).reshape(-1)
        limit = min(len(scores), len(self._tag_names))
        predictions = [
            TagPrediction(tag=self._tag_names[index], confidence=float(scores[index]))
            for index in range(limit)
            if float(scores[index]) >= threshold
        ]
        predictions.sort(key=lambda item: item.confidence, reverse=True)
        return predictions

    def _preprocess(self, image_path: Path) -> np.ndarray:
        size = self.input_size
        with Image.open(image_path) as image:
            rgba = image.convert("RGBA")
            background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
            background.alpha_composite(rgba)
            rgb = background.convert("RGB")
        side = max(rgb.width, rgb.height)
        canvas = Image.new("RGB", (side, side), (255, 255, 255))
        canvas.paste(rgb, ((side - rgb.width) // 2, (side - rgb.height) // 2))
        resized = canvas.resize((size, size), Image.Resampling.BICUBIC)
        array = np.asarray(resized, dtype=np.float32)
        bgr = array[:, :, ::-1]
        return np.expand_dims(bgr, axis=0)


_tagger_lock = threading.Lock()
_tagger_cache: dict[str, LocalWdTagger] = {}
local_wd_model_manager = LocalWdModelManager()


def get_local_wd_tagger(repo_id: str = DEFAULT_LOCAL_WD_MODEL) -> LocalWdTagger:
    with _tagger_lock:
        tagger = _tagger_cache.get(repo_id)
        if tagger is None:
            tagger = LocalWdTagger(repo_id)
            _tagger_cache[repo_id] = tagger
        return tagger


def clear_local_wd_tagger_cache() -> None:
    with _tagger_lock:
        _tagger_cache.clear()


def predict_tags_locally(
    image_path: Path,
    *,
    repo_id: str = DEFAULT_LOCAL_WD_MODEL,
    threshold: float = 0.35,
) -> tuple[list[TagPrediction], str | None]:
    try:
        return get_local_wd_tagger(repo_id).predict(image_path, threshold=threshold), None
    except LocalWdTaggerError as exc:
        return [], HFWdTaggerErrorMessage(str(exc), exc.reason_code)
    except Exception as exc:
        return [], HFWdTaggerErrorMessage(f"Unexpected local tagger error: {exc}", TAGGER_ERROR)
