from __future__ import annotations

import re
from pathlib import Path


def sanitize_wildcard_slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_\-]+", "_", value.strip().lower())
    slug = re.sub(r"_+", "_", slug).strip("_")
    return slug or "series"


def wildcard_relative_path(queue_id: str) -> str:
    return f"catalogue_manager/{sanitize_wildcard_slug(queue_id)}_characters.txt"


def wildcard_token_name(queue_id: str) -> str:
    return f"catalogue_manager/{sanitize_wildcard_slug(queue_id)}_characters"


def write_character_wildcard(
    wildcards_dir: Path,
    queue_id: str,
    lines: list[str],
) -> Path:
    rel = wildcard_relative_path(queue_id)
    target = wildcards_dir / rel.replace("/", "\\") if "\\" in str(wildcards_dir) else wildcards_dir / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(line.strip() for line in lines if line and line.strip())
    target.write_text(content + ("\n" if content else ""), encoding="utf-8")
    return target
