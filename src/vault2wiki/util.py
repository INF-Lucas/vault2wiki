from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path

import yaml


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def read_text_file(path: Path, max_chars: int) -> str:
    data = path.read_text(encoding="utf-8", errors="ignore")
    if max_chars and len(data) > max_chars:
        return data[:max_chars] + "\n\n[...truncated...]"
    return data


def safe_stem(name: str) -> str:
    name = name.strip().replace(os.sep, "-")
    name = re.sub(r"[^\w\u4e00-\u9fff\- ]+", "-", name, flags=re.UNICODE)
    name = re.sub(r"\s+", " ", name).strip().replace(" ", "-")
    name = re.sub(r"-{2,}", "-", name)
    name = name.strip("-")
    return name or "untitled"


def md_frontmatter(title: str, source: str, updated: str, tags: list[str]) -> str:
    fm = {
        "title": title,
        "source": source,
        "updated": updated,
        "tags": tags,
    }
    fm_text = yaml.safe_dump(fm, allow_unicode=True, sort_keys=False).strip()
    return f"---\n{fm_text}\n---\n\n"
