from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

_FM_RE = re.compile(r"^\s*---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _parse_frontmatter(md_text: str) -> tuple[dict[str, Any] | None, str]:
    match = _FM_RE.match(md_text or "")
    if not match:
        return None, md_text or ""

    fm_raw = match.group(1)
    body = md_text[match.end() :]
    try:
        fm = yaml.safe_load(fm_raw) or {}
        if not isinstance(fm, dict):
            fm = {}
    except Exception:
        fm = {}
    return fm, body


def _dump_frontmatter(fm: dict[str, Any]) -> str:
    return yaml.safe_dump(fm, allow_unicode=True, sort_keys=False).strip()


def _canon(tag: str) -> str:
    value = (tag or "").strip()
    value = re.sub(r"\s+", " ", value)
    if re.search(r"[A-Za-z]", value) and not re.search(r"[\u4e00-\u9fff]", value):
        if not (value == value.upper() and len(value) <= 6):
            value = value.lower()
    return value.replace(" ", "-")


def _source_type_tag(source: str) -> str:
    path = (source or "").strip().lower()
    if path.startswith("raw/web/"):
        return "web"
    if path.startswith("raw/papers/") or path.startswith("raw/paper/"):
        return "paper"
    if path.startswith("raw/books/") or path.startswith("raw/book/"):
        return "book"
    return "note"


def normalize_tags(
    tags: list[str],
    *,
    allowlist: set[str],
    mappings: dict[str, str],
    keep: set[str],
    max_topic_tags: int = 6,
) -> list[str]:
    raw_tags = [str(tag) for tag in tags or [] if tag is not None]

    mapped: list[str] = []
    for tag in raw_tags:
        canonical = _canon(tag)
        replacement = mappings.get(tag) or mappings.get(canonical)
        canonical = _canon(replacement) if replacement else canonical
        if canonical:
            mapped.append(canonical)

    keep_tags: list[str] = []
    topic_tags: list[str] = []
    for tag in mapped:
        if tag in keep:
            keep_tags.append(tag)
        else:
            topic_tags.append(tag)

    def uniq(items: list[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for item in items:
            if item in seen:
                continue
            seen.add(item)
            out.append(item)
        return out

    keep_tags = uniq(keep_tags)
    topic_tags = uniq(topic_tags)

    if allowlist:
        topic_tags = [tag for tag in topic_tags if tag in allowlist]
    if max_topic_tags > 0:
        topic_tags = topic_tags[:max_topic_tags]
    return keep_tags + topic_tags


def apply_tag_cleanup_to_markdown(md_text: str, *, cfg: dict[str, Any]) -> str:
    tags_cfg = cfg.get("compile", {}).get("tags", {}) or {}
    if not bool(tags_cfg.get("enabled", False)):
        return md_text

    fm, body = _parse_frontmatter(md_text)
    if fm is None:
        return md_text

    tags_val = fm.get("tags") or []
    if isinstance(tags_val, str):
        tags_list = [tags_val]
    elif isinstance(tags_val, list):
        tags_list = [str(item) for item in tags_val]
    else:
        tags_list = []

    tags_list.append(_source_type_tag(str(fm.get("source") or "")))

    allowlist = {_canon(item) for item in (tags_cfg.get("allowlist") or [])}
    keep = {_canon(item) for item in (tags_cfg.get("keep") or [])}
    mappings_raw = tags_cfg.get("mappings") or {}
    mappings: dict[str, str] = {}
    if isinstance(mappings_raw, dict):
        for key, value in mappings_raw.items():
            mappings[str(key)] = str(value)

    fm["tags"] = normalize_tags(
        tags_list,
        allowlist=allowlist,
        mappings=mappings,
        keep=keep,
        max_topic_tags=int(tags_cfg.get("max_topic_tags", 6)),
    )
    if not fm.get("tags"):
        fm["tags"] = ["note"]

    fm_text = _dump_frontmatter(fm)
    return f"---\n{fm_text}\n---\n{body.lstrip()}"
