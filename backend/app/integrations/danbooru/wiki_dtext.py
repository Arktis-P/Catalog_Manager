from __future__ import annotations

import re

WIKI_LINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
LIST_OF_CHARACTERS_RE = re.compile(r"list_of_.*characters", re.IGNORECASE)


def normalize_wiki_title(value: str) -> str:
    return value.strip().lower().replace(" ", "_")


def resolve_wiki_tag_candidates(raw: str) -> list[str]:
    """Return normalized tag name candidates from one [[...]] link, most specific first."""
    content = raw.split("#", 1)[0].strip()
    if not content:
        return []

    candidates: list[str] = []
    if "|" not in content:
        candidates.append(normalize_wiki_title(content))
    else:
        left, right = content.split("|", 1)
        left = left.strip()
        right = right.strip()
        # List pages often use [[Yuudachi (kancolle)|Yuudachi]] — disambiguated name is on the left.
        if left:
            candidates.append(normalize_wiki_title(left))
        if right:
            candidates.append(normalize_wiki_title(right))

    seen: set[str] = set()
    ordered: list[str] = []
    for name in candidates:
        if name and name not in seen:
            seen.add(name)
            ordered.append(name)
    return ordered


def _resolve_link_target(raw: str) -> str | None:
    candidates = resolve_wiki_tag_candidates(raw)
    return candidates[0] if candidates else None


def extract_wiki_links(body: str) -> list[str]:
    if not body:
        return []

    links: list[str] = []
    seen: set[str] = set()
    for match in WIKI_LINK_RE.finditer(body):
        raw = match.group(1).strip()
        if not raw or raw.startswith("!") or raw.startswith("#"):
            continue

        for tag in resolve_wiki_tag_candidates(raw):
            if tag in seen:
                continue
            seen.add(tag)
            links.append(tag)
            break
    return links


def is_list_of_characters_page(title: str) -> bool:
    return bool(LIST_OF_CHARACTERS_RE.search(normalize_wiki_title(title)))
