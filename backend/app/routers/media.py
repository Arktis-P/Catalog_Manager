from __future__ import annotations

import re
import mimetypes
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from PIL import Image

from app.config import settings

router = APIRouter(tags=["media"])

mimetypes.add_type("image/webp", ".webp")

_FILENAME_RE = re.compile(r"^[a-zA-Z0-9_\-]+\.(png|webp)$", re.IGNORECASE)
_SOURCE_DIRS = {"pending_review", "catalog_selected"}
_THUMBNAIL_FORMAT = "WEBP"
_THUMBNAIL_MEDIA_TYPE = "image/webp"


def _source_dir(subdir: str) -> Path:
    return settings.output_dir / "generated_images" / subdir


def _thumb_cache_dir(subdir: str, size: int) -> Path:
    return settings.output_dir / "generated_images" / "thumbs" / subdir / str(size)


@router.get("/media/thumb/{subdir}/{filename}")
def serve_thumbnail(
    subdir: str,
    filename: str,
    size: int = Query(default=384, ge=128, le=1024),
):
    if subdir not in _SOURCE_DIRS:
        raise HTTPException(status_code=400, detail="Invalid subdir")
    if not _FILENAME_RE.match(filename):
        raise HTTPException(status_code=400, detail="Invalid filename")

    source = _source_dir(subdir) / filename
    if not source.is_file():
        raise HTTPException(status_code=404, detail="Image not found")

    cache_dir = _thumb_cache_dir(subdir, size)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = cache_dir / f"{Path(filename).stem}.webp"

    if not cached.exists() or cached.stat().st_mtime < source.stat().st_mtime:
        with Image.open(source) as image:
            thumbnail = image.copy()
            thumbnail.thumbnail((size, size), Image.Resampling.LANCZOS)
            thumbnail.save(cached, format=_THUMBNAIL_FORMAT, quality=92, method=6)

    return FileResponse(cached, media_type=_THUMBNAIL_MEDIA_TYPE)
