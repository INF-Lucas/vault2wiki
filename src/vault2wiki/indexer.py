from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

_FM_RE = re.compile(r"^\s*---\s*\n(.*?)\n---\s*\n", re.DOTALL)


@dataclass
class IndexItem:
    rel_path: str
    title: str
    updated: str
    source: str
    tags: list[str]

    @property
    def folder(self) -> str:
        parts = self.rel_path.split("/")
        if len(parts) >= 3 and parts[0] == "wiki":
            return parts[1]
        if len(parts) >= 2 and parts[0] == "wiki":
            return "(root)"
        return parts[-2] if len(parts) >= 2 else "(root)"


def _parse_frontmatter(md_text: str) -> dict[str, Any]:
    match = _FM_RE.match(md_text or "")
    if not match:
        return {}
    raw = match.group(1)
    try:
        data = yaml.safe_load(raw) or {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def build_index_items(vault_root: Path, wiki_dir: Path) -> list[IndexItem]:
    items: list[IndexItem] = []
    for path in wiki_dir.rglob("*.md"):
        if path.name.lower().startswith("_index"):
            continue
        rel_path = path.relative_to(vault_root).as_posix()
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        fm = _parse_frontmatter(text)
        tags_val = fm.get("tags") or []
        if isinstance(tags_val, str):
            tags = [tags_val]
        elif isinstance(tags_val, list):
            tags = [str(tag) for tag in tags_val]
        else:
            tags = []
        items.append(
            IndexItem(
                rel_path=rel_path,
                title=str(fm.get("title") or path.stem),
                updated=str(fm.get("updated") or ""),
                source=str(fm.get("source") or ""),
                tags=tags,
            )
        )
    items.sort(key=lambda item: (item.updated == "", item.updated), reverse=True)
    return items


def render_index_markdown(
    *,
    items: list[IndexItem],
    recent_limit: int,
    group_by_folder: bool,
) -> str:
    lines = [
        "---",
        'title: "Wiki Index"',
        'tags: ["index"]',
        "---",
        "",
        "# Wiki Index",
        "",
        "## Recently Updated",
        "",
    ]

    for item in items[: max(0, recent_limit)]:
        lines.append(f"- [[{Path(item.rel_path).stem}]] - `{item.updated}` - `{item.folder}`")

    if not group_by_folder:
        return "\n".join(lines) + "\n"

    lines.extend(["", "## By Folder", ""])
    by_folder: dict[str, list[IndexItem]] = {}
    for item in items:
        by_folder.setdefault(item.folder, []).append(item)

    for folder in sorted(by_folder.keys()):
        lines.extend([f"### {folder}", ""])
        for item in by_folder[folder]:
            tag_str = ""
            if item.tags:
                tag_str = " " + " ".join(f"#{tag}" for tag in item.tags if tag)
            updated = f"`{item.updated}`" if item.updated else ""
            lines.append(f"- [[{Path(item.rel_path).stem}]] {updated}{tag_str}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def update_index_file(
    *,
    vault_root: Path,
    wiki_dir: Path,
    index_path: Path,
    recent_limit: int,
    group_by_folder: bool,
) -> None:
    items = build_index_items(vault_root, wiki_dir)
    markdown = render_index_markdown(
        items=items,
        recent_limit=recent_limit,
        group_by_folder=group_by_folder,
    )
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(markdown, encoding="utf-8")
