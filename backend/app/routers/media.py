from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from PIL import Image

from app.config import settings

router = APIRouter(tags=["media"])

_FILENAME_RE = re.compile(r"^[a-zA-Z0-9_\-]+\.png$", re.IGNORECASE)
_SOURCE_DIRS = {"pending_review", "catalog_selected"}


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
    cached = cache_dir / filename

    if not cached.exists() or cached.stat().st_mtime < source.stat().st_mtime:
        with Image.open(source) as image:
            rgb = image.convert("RGB")
            rgb.thumbnail((size, size), Image.Resampling.LANCZOS)
            # optimize=True는 PNG를 여러 압축 전략으로 다시 시도해 최적 크기를 찾기
            # 때문에 원본이 큰 NAI 이미지(800x1200+)에서 첫 캐시 생성이 눈에 띄게
            # 느려진다. 캐시는 디스크에 영구 저장되므로 압축률보다 생성 속도를 우선한다.
            rgb.save(cached, format="PNG", optimize=False, compress_level=1)

    return FileResponse(cached, media_type="image/png")
