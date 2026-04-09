from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import yaml

from .util import now_iso, safe_stem

_WIKILINK_RE = re.compile(r"\[\[([^\]\|#]+)(?:[|#][^\]]*)?\]\]")
_FM_RE = re.compile(r"^\s*---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_BAD_TERM_RE = re.compile(r"[\n\r\t]|https?://|[。！？；：，、…]|\\|`")


def _parse_frontmatter(md_text: str) -> tuple[dict[str, Any] | None, str]:
    match = _FM_RE.match(md_text or "")
    if not match:
        return None, md_text or ""
    raw = match.group(1)
    body = md_text[match.end() :]
    try:
        data = yaml.safe_load(raw) or {}
        if not isinstance(data, dict):
            data = {}
    except Exception:
        data = {}
    return data, body


def _dump_frontmatter(fm: dict[str, Any]) -> str:
    return yaml.safe_dump(fm, allow_unicode=True, sort_keys=False).strip()


def _extract_wikilinks(md_text: str) -> list[str]:
    return [(match.group(1) or "").strip() for match in _WIKILINK_RE.finditer(md_text or "") if match.group(1).strip()]


def _strip_h2_section(md_text: str, *, title: str) -> str:
    if not md_text:
        return md_text
    lines = md_text.splitlines()
    output: list[str] = []
    dropping = False
    for line in lines:
        if line.strip().startswith("## "):
            heading = line.strip()[3:].strip()
            if heading == title:
                dropping = True
                continue
            if dropping:
                dropping = False
        if not dropping:
            output.append(line)
    return "\n".join(output) + ("\n" if md_text.endswith("\n") else "")


def _norm_term(value: str) -> str:
    value = (value or "").strip()
    if re.search(r"[A-Za-z]", value) and not re.search(r"[\u4e00-\u9fff]", value):
        value = value.lower()
    return value


def _norm_key(value: str) -> str:
    value = _norm_term(value)
    value = re.sub(r"[\s\-_·—–]+", "", value)
    value = re.sub(r"[^\w\u4e00-\u9fff]+", "", value, flags=re.UNICODE)
    return value


def _is_valid_term(value: str, *, max_term_len: int) -> bool:
    value = (value or "").strip()
    if not value:
        return False
    if len(value) > max_term_len:
        return False
    if _BAD_TERM_RE.search(value):
        return False
    return True


def build_glossary(
    *,
    vault_root: Path,
    wiki_dir: Path,
    out_dir: Path,
    min_refs: int = 2,
    max_links_per_term: int = 200,
    term_tag: str = "term",
    ignore_terms: list[str] | None = None,
    max_term_len: int = 40,
) -> dict[str, int]:
    out_dir.mkdir(parents=True, exist_ok=True)

    existing_keys: set[str] = set()
    for path in wiki_dir.rglob("*.md"):
        existing_keys.add(path.stem)
        try:
            fm, _ = _parse_frontmatter(path.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            fm = None
        if fm:
            aliases = fm.get("aliases") or []
            if isinstance(aliases, str):
                aliases = [aliases]
            if isinstance(aliases, list):
                for alias in aliases:
                    if alias:
                        existing_keys.add(str(alias).strip())

    refs: dict[str, set[str]] = defaultdict(set)
    counter: Counter[str] = Counter()
    variants: dict[str, Counter[str]] = defaultdict(Counter)
    ignore = {_norm_key(item) for item in (ignore_terms or []) if str(item).strip()}

    for path in wiki_dir.rglob("*.md"):
        if (wiki_dir / "moc") in path.parents:
            continue
        if out_dir in path.parents:
            continue
        if path.name.lower() in {"_index.md", "_health.md", "_verify.md"}:
            continue

        text = path.read_text(encoding="utf-8", errors="ignore")
        text_for_count = _strip_h2_section(text, title="Related Links")
        for term in _extract_wikilinks(text_for_count):
            if not _is_valid_term(term, max_term_len=max_term_len):
                continue
            key = _norm_key(term)
            if not key or key in ignore:
                continue
            if term in existing_keys:
                continue
            counter[key] += 1
            refs[key].add(path.stem)
            variants[key][term] += 1

    targets = [(key, count) for key, count in counter.items() if count >= min_refs]
    targets.sort(key=lambda item: (-item[1], item[0]))

    stats = {"generated": 0, "updated": 0, "skipped": 0}
    used_filenames: set[str] = set()

    for key, count in targets:
        term = variants[key].most_common(1)[0][0] if variants.get(key) else key
        base = safe_stem(term)
        filename = base + ".md"
        if filename in used_filenames:
            suffix = hashlib.md5(key.encode("utf-8")).hexdigest()[:6]
            filename = f"{base}-{suffix}.md"
        used_filenames.add(filename)
        out_path = out_dir / filename

        aliases = sorted(set(list(variants[key].keys()) if variants.get(key) else [term]))
        fm = {
            "title": term,
            "aliases": aliases,
            "source": out_path.relative_to(vault_root).as_posix(),
            "updated": now_iso(),
            "tags": [term_tag],
        }

        lines = [
            "---",
            _dump_frontmatter(fm),
            "---",
            "",
            f"# {term}",
            "",
            f"## References ({len(refs[key])} notes, {count} links)",
            "",
        ]
        for stem in sorted(refs[key])[:max_links_per_term]:
            lines.append(f"- [[{stem}]]")
        if len(refs[key]) > max_links_per_term:
            lines.append(f"- ... {len(refs[key]) - max_links_per_term} more omitted")
        lines.append("")

        new_text = "\n".join(lines).rstrip() + "\n"
        if out_path.exists():
            old = out_path.read_text(encoding="utf-8", errors="ignore")
            if old != new_text:
                out_path.write_text(new_text, encoding="utf-8")
                stats["updated"] += 1
            else:
                stats["skipped"] += 1
        else:
            out_path.write_text(new_text, encoding="utf-8")
            stats["generated"] += 1

        existing_keys.add(term)
        existing_keys.add(out_path.stem)

    return stats
