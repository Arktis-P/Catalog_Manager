from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from PIL import Image

from app.config import settings

router = APIRouter(tags=["media"])

_FILENAME_RE = re.compile(r"^[a-zA-Z0-9_\-]+\.png$", re.IGNORECASE)


def _pending_dir() -> Path:
    return settings.output_dir / "generated_images" / "pending_review"


def _thumb_cache_dir(size: int) -> Path:
    return settings.output_dir / "generated_images" / "thumbs" / str(size)


@router.get("/media/thumb/{filename}")
def serve_thumbnail(
    filename: str,
    size: int = Query(default=384, ge=128, le=1024),
):
    if not _FILENAME_RE.match(filename):
        raise HTTPException(status_code=400, detail="Invalid filename")

    source = _pending_dir() / filename
    if not source.is_file():
        raise HTTPException(status_code=404, detail="Image not found")

    cache_dir = _thumb_cache_dir(size)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = cache_dir / filename

    if not cached.exists() or cached.stat().st_mtime < source.stat().st_mtime:
        with Image.open(source) as image:
            rgb = image.convert("RGB")
            rgb.thumbnail((size, size), Image.Resampling.LANCZOS)
            rgb.save(cached, format="PNG", optimize=True)

    return FileResponse(cached, media_type="image/png")
