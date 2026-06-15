from __future__ import annotations

import re

WIKI_LINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
LIST_OF_CHARACTERS_RE = re.compile(r"list_of_.*characters", re.IGNORECASE)


def normalize_wiki_title(value: str) -> str:
    return value.strip().lower().replace(" ", "_")


def extract_wiki_links(body: str) -> list[str]:
    if not body:
        return []

    links: list[str] = []
    seen: set[str] = set()
    for match in WIKI_LINK_RE.finditer(body):
        raw = match.group(1).strip()
        if not raw or raw.startswith("!") or raw.startswith("#"):
            continue

        tag = _resolve_link_target(raw)
        if not tag:
            continue

        normalized = normalize_wiki_title(tag)
        if normalized in seen:
            continue
        seen.add(normalized)
        links.append(normalized)
    return links


def _resolve_link_target(raw: str) -> str | None:
    content = raw.split("#", 1)[0].strip()
    if not content:
        return None

    if "|" not in content:
        return content

    left, right = content.split("|", 1)
    left = left.strip()
    right = right.strip()
    if right:
        return right
    if left:
        return left
    return None


def is_list_of_characters_page(title: str) -> bool:
    return bool(LIST_OF_CHARACTERS_RE.search(normalize_wiki_title(title)))
