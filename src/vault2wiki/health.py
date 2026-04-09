from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .util import now_iso

_FM_RE = re.compile(r"^\s*---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_WIKILINK_RE = re.compile(r"\[\[([^\]|\#]+?)(?:#[^\]\|]+)?(?:\|[^\]]+)?\]\]")


@dataclass
class NoteInfo:
    rel_path: str
    stem: str
    title: str
    updated: str
    source: str
    tags: list[str]
    aliases: list[str]
    has_frontmatter: bool
    missing_fields: list[str]
    out_links: list[str]


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


def _extract_wikilinks(md_text: str) -> list[str]:
    return [match.group(1).strip() for match in _WIKILINK_RE.finditer(md_text or "") if match.group(1).strip()]


def scan_wiki(vault_root: Path, wiki_dir: Path) -> list[NoteInfo]:
    notes: list[NoteInfo] = []
    for path in wiki_dir.rglob("*.md"):
        if path.name.lower() in {"_index.md", "_health.md", "_verify.md"}:
            continue
        rel_path = path.relative_to(vault_root).as_posix()
        text = path.read_text(encoding="utf-8", errors="ignore")
        fm = _parse_frontmatter(text)
        tags_val = fm.get("tags") or []
        if isinstance(tags_val, str):
            tags = [tags_val]
        elif isinstance(tags_val, list):
            tags = [str(tag) for tag in tags_val]
        else:
            tags = []
        aliases_val = fm.get("aliases") or fm.get("alias") or []
        if isinstance(aliases_val, str):
            aliases = [aliases_val] if aliases_val.strip() else []
        elif isinstance(aliases_val, list):
            aliases = [str(alias).strip() for alias in aliases_val if str(alias).strip()]
        else:
            aliases = []

        missing_fields: list[str] = []
        for field in ["title", "source", "updated", "tags"]:
            if field == "tags":
                if not tags:
                    missing_fields.append("tags")
            elif not str(fm.get(field) or "").strip():
                missing_fields.append(field)

        notes.append(
            NoteInfo(
                rel_path=rel_path,
                stem=path.stem,
                title=str(fm.get("title") or path.stem).strip(),
                updated=str(fm.get("updated") or "").strip(),
                source=str(fm.get("source") or "").strip(),
                tags=tags,
                aliases=aliases,
                has_frontmatter=bool(fm),
                missing_fields=missing_fields,
                out_links=_extract_wikilinks(text),
            )
        )
    return notes


def _norm(value: str) -> str:
    value = (value or "").strip().lower()
    value = value.replace("_", "-").replace(" ", "-")
    value = re.sub(r"[^0-9a-z\u4e00-\u9fff\-]+", "", value)
    value = re.sub(r"-{2,}", "-", value)
    return value


def _best_match(target: str, candidates: list[str]) -> str | None:
    if not target or not candidates:
        return None
    direct = difflib.get_close_matches(target, candidates, n=1, cutoff=0.86)
    if direct:
        return direct[0]
    normalized_target = _norm(target)
    normalized_map = {_norm(candidate): candidate for candidate in candidates}
    normalized = difflib.get_close_matches(normalized_target, list(normalized_map.keys()), n=1, cutoff=0.86)
    if normalized:
        return normalized_map[normalized[0]]
    return None


def _suggest_for_orphan(note: NoteInfo, notes: list[NoteInfo], top_k: int = 5) -> list[str]:
    scored: list[tuple[int, str]] = []
    note_tags = {tag for tag in note.tags if tag}
    for other in notes:
        if other.rel_path == note.rel_path:
            continue
        score = 0
        if note_tags:
            score += len(note_tags.intersection({tag for tag in other.tags if tag})) * 3
        if other.rel_path.split("/")[1:2] == note.rel_path.split("/")[1:2]:
            score += 1
        if score > 0:
            scored.append((score, other.stem))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [f"Add a link from [[{stem}]] to [[{note.stem}]]" for _, stem in scored[:top_k]]


def build_health_report(*, vault_root: Path, wiki_dir: Path, max_items_per_section: int = 200) -> str:
    notes = scan_wiki(vault_root, wiki_dir)

    key_to_note: dict[str, NoteInfo] = {}
    all_keys: list[str] = []
    for note in notes:
        for key in [note.stem, note.title, *note.aliases]:
            if not key:
                continue
            key_to_note.setdefault(key, note)
            all_keys.append(key)

    inbound = {note.rel_path: 0 for note in notes}
    broken_links: list[tuple[NoteInfo, str]] = []
    for note in notes:
        for target in note.out_links:
            hit = key_to_note.get(target)
            if hit is None:
                broken_links.append((note, target))
            else:
                inbound[hit.rel_path] = inbound.get(hit.rel_path, 0) + 1

    orphans = [note for note in notes if inbound.get(note.rel_path, 0) == 0]
    missing_frontmatter = [note for note in notes if not note.has_frontmatter]
    missing_fields = [note for note in notes if note.missing_fields]
    missing_sources = [note for note in notes if note.source and not (vault_root / note.source).resolve().exists()]

    title_map: dict[str, list[NoteInfo]] = {}
    for note in notes:
        if note.title:
            title_map.setdefault(note.title, []).append(note)
    duplicate_titles = {title: grouped for title, grouped in title_map.items() if len(grouped) >= 2}

    def cap(items: list[Any]) -> list[Any]:
        return items[: max_items_per_section]

    lines = [
        "---",
        'title: "Health Report"',
        f'updated: "{now_iso()}"',
        'tags: ["health"]',
        "---",
        "",
        "# Health Report",
        "",
        "## Summary",
        "",
        f"- Total notes: {len(notes)}",
        f"- Missing front matter: {len(missing_frontmatter)}",
        f"- Missing required fields: {len(missing_fields)}",
        f"- Broken wikilinks: {len(broken_links)}",
        f"- Orphan notes: {len(orphans)}",
        f"- Missing source files: {len(missing_sources)}",
        f"- Duplicate titles: {len(duplicate_titles)}",
        "",
        "## Missing Front Matter",
        "",
    ]

    if not missing_frontmatter:
        lines.append("- None")
    else:
        for note in cap(missing_frontmatter):
            lines.append(f"- [[{note.stem}]] (`{note.rel_path}`)")

    lines.extend(["", "## Missing Required Fields", ""])
    if not missing_fields:
        lines.append("- None")
    else:
        for note in cap(missing_fields):
            lines.append(f"- [[{note.stem}]] missing `{', '.join(note.missing_fields)}`")

    lines.extend(["", "## Broken Links", ""])
    if not broken_links:
        lines.append("- None")
    else:
        for note, target in cap(broken_links):
            lines.append(f"- [[{note.stem}]] links to `[[{target}]]`, but no target note exists")

    lines.extend(["", "## Suggested Fixes", "", "> Suggestions only. No files were modified automatically.", ""])
    if broken_links:
        lines.extend(["### Broken Link Suggestions", ""])
        for note, target in cap(broken_links):
            match = _best_match(target, all_keys)
            if match:
                lines.append(f"- In [[{note.stem}]], consider replacing `[[{target}]]` with `[[{match}]]`")
            else:
                lines.append(f"- In [[{note.stem}]], create a new note for `[[{target}]]` or remove the link")
        lines.append("")

    lines.extend(["### Orphan Suggestions", ""])
    if not orphans:
        lines.append("- None")
    else:
        for note in cap(orphans):
            suggestions = _suggest_for_orphan(note, notes)
            if suggestions:
                for suggestion in suggestions:
                    lines.append(f"- {suggestion}")
            else:
                lines.append(f"- [[{note.stem}]] has no obvious inbound-link candidates")

    lines.extend(["", "## Missing Source Files", ""])
    if not missing_sources:
        lines.append("- None")
    else:
        for note in cap(missing_sources):
            lines.append(f"- [[{note.stem}]] points to missing source `{note.source}`")

    lines.extend(["", "## Duplicate Titles", ""])
    if not duplicate_titles:
        lines.append("- None")
    else:
        for title, grouped in sorted(duplicate_titles.items()):
            refs = ", ".join(f"`{note.rel_path}`" for note in grouped[:5])
            lines.append(f"- `{title}` appears in {len(grouped)} notes: {refs}")

    return "\n".join(lines).rstrip() + "\n"


def write_health_report(
    *,
    vault_root: Path,
    wiki_dir: Path,
    out_path: Path,
    max_items_per_section: int = 200,
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        build_health_report(
            vault_root=vault_root,
            wiki_dir=wiki_dir,
            max_items_per_section=max_items_per_section,
        ),
        encoding="utf-8",
    )
