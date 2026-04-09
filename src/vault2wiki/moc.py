from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from .indexer import build_index_items
from .util import now_iso


def generate_moc(
    *,
    vault_root: Path,
    wiki_dir: Path,
    moc_dir: Path,
    top_tag_limit: int = 30,
    per_folder_limit: int = 200,
) -> list[Path]:
    items = build_index_items(vault_root, wiki_dir)
    moc_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    by_folder: dict[str, list] = defaultdict(list)
    for item in items:
        by_folder[item.folder].append(item)
    for folder in by_folder:
        by_folder[folder].sort(key=lambda item: (item.updated == "", item.updated), reverse=True)

    folder_pages: list[str] = []
    for folder in sorted(by_folder.keys()):
        slug = folder.replace("/", "-").strip() or "root"
        page = moc_dir / f"folder-{slug}.md"
        page.write_text(_render_folder_moc(folder, by_folder[folder][:per_folder_limit]), encoding="utf-8")
        written.append(page)
        folder_pages.append(page.stem)

    tag_map: dict[str, list] = defaultdict(list)
    for item in items:
        for tag in item.tags:
            if tag:
                tag_map[tag].append(item)
    for tag in tag_map:
        tag_map[tag].sort(key=lambda item: (item.updated == "", item.updated), reverse=True)

    top_tags = sorted(tag_map.items(), key=lambda pair: len(pair[1]), reverse=True)[:top_tag_limit]
    tags_page = moc_dir / "tags.md"
    tags_page.write_text(_render_tags_moc(top_tags), encoding="utf-8")
    written.append(tags_page)

    home = moc_dir / "_home.md"
    home.write_text(_render_home_moc(folder_pages=folder_pages, tags_page=tags_page.stem), encoding="utf-8")
    written.append(home)

    return written


def _render_home_moc(*, folder_pages: list[str], tags_page: str) -> str:
    lines = [
        "---",
        'title: "MOC Home"',
        'source: "wiki/moc/_home.md"',
        f'updated: "{now_iso()}"',
        'tags: ["moc"]',
        "---",
        "",
        "# MOC Home",
        "",
        "## Folder Maps",
        "",
    ]
    for stem in folder_pages:
        lines.append(f"- [[{stem}]]")
    lines.extend(["", "## Tag Map", "", f"- [[{tags_page}]]", ""])
    return "\n".join(lines)


def _render_folder_moc(folder: str, items: list) -> str:
    slug = folder.replace("/", "-").strip() or "(root)"
    lines = [
        "---",
        f'title: "MOC: {folder}"',
        f'source: "wiki/moc/folder-{slug}.md"',
        f'updated: "{now_iso()}"',
        'tags: ["moc"]',
        "---",
        "",
        f"# MOC: {folder}",
        "",
        "## Notes",
        "",
    ]
    for item in items:
        updated = f"`{item.updated}`" if item.updated else ""
        lines.append(f"- [[{Path(item.rel_path).stem}]] {updated}")
    lines.append("")
    return "\n".join(lines)


def _render_tags_moc(top_tags: list[tuple[str, list]]) -> str:
    lines = [
        "---",
        'title: "MOC: Tags"',
        'source: "wiki/moc/tags.md"',
        f'updated: "{now_iso()}"',
        'tags: ["moc"]',
        "---",
        "",
        "# MOC: Tags",
        "",
    ]
    for tag, items in top_tags:
        lines.extend([f"## #{tag} ({len(items)})", ""])
        for item in items[:50]:
            updated = f"`{item.updated}`" if item.updated else ""
            lines.append(f"- [[{Path(item.rel_path).stem}]] {updated}")
        if len(items) > 50:
            lines.append(f"- ... {len(items) - 50} more omitted")
        lines.append("")
    return "\n".join(lines)
