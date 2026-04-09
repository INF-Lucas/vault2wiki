from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Iterable

from .config import read_prompt
from .fts import update_index_for_paths
from .gate import promote_or_reject
from .glossary import build_glossary
from .health import write_health_report
from .indexer import update_index_file
from .llm import LLMClient
from .moc import generate_moc
from .state import load_state, save_state
from .tags import apply_tag_cleanup_to_markdown
from .util import ensure_dir, md_frontmatter, now_iso, read_text_file, safe_stem
from .verify import write_verify_report

SUPPORTED_TEXT_EXT = {".md", ".txt"}
SUPPORTED_PDF_EXT = {".pdf"}
SUPPORTED_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp"}

_WIKILINK_FULL_RE = re.compile(r"\[\[([^\]\|#]+)(?:#([^\]\|]+))?(?:\|([^\]]+))?\]\]")
_FENCED_BLOCK_RE = re.compile(r"^\s*```(?:markdown|md)?\s*\n(?P<body>.*)\n```\s*$", re.DOTALL | re.IGNORECASE)


def _norm_for_match(value: str) -> str:
    value = (value or "").strip().lower()
    value = value.replace(" ", "").replace("_", "").replace("-", "")
    value = re.sub(r"[^\w\u4e00-\u9fff]+", "", value)
    return value


def _filter_related_links_by_source(md_text: str, *, source_text: str) -> str:
    if not md_text or not source_text:
        return md_text

    normalized_source = _norm_for_match(source_text)
    if not normalized_source:
        return md_text

    lines = md_text.splitlines()
    output: list[str] = []
    in_related_links = False

    def allowed(target: str) -> bool:
        normalized_target = _norm_for_match(target)
        return bool(normalized_target) and normalized_target in normalized_source

    def repl(match: re.Match) -> str:
        target = (match.group(1) or "").strip()
        alias = (match.group(3) or "").strip()
        if allowed(target):
            return match.group(0)
        return alias or target

    for line in lines:
        if line.strip().startswith("## "):
            title = line.strip()[3:].strip()
            if title == "Related Links":
                in_related_links = True
            elif in_related_links:
                in_related_links = False

        output.append(_WIKILINK_FULL_RE.sub(repl, line) if in_related_links else line)

    return "\n".join(output) + ("\n" if md_text.endswith("\n") else "")


def _collect_existing_titles(wiki_dir: Path, limit: int) -> list[str]:
    titles: list[str] = []
    for path in sorted(wiki_dir.rglob("*.md")):
        titles.append(path.stem)
        if len(titles) >= limit:
            break
    return titles


def _normalize_llm_markdown(markdown: str) -> str:
    text = (markdown or "").strip()
    while True:
        match = _FENCED_BLOCK_RE.match(text)
        if not match:
            break
        text = (match.group("body") or "").strip()
    return text + ("\n" if text else "")


def compile_paths(
    *,
    vault_root: Path,
    cfg: dict[str, Any],
    llm: LLMClient,
    changed_paths: Iterable[Path] | None = None,
) -> list[Path]:
    paths_cfg = cfg["paths"]
    raw_dir = (vault_root / paths_cfg["raw_dir"]).resolve()
    wiki_dir = (vault_root / paths_cfg["wiki_dir"]).resolve()
    state_file = (vault_root / paths_cfg["state_file"]).resolve()
    fts_db = (vault_root / (paths_cfg.get("fts_db") or ".vault2wiki/fts.sqlite3")).resolve()

    ensure_dir(wiki_dir)
    state = load_state(state_file)
    compile_cfg = cfg.get("compile", {})

    max_chars = int(compile_cfg.get("max_source_chars", 50000))
    title_limit = int(compile_cfg.get("include_existing_titles_max", 200))
    overwrite = bool(compile_cfg.get("overwrite_existing", True))
    gate_cfg = compile_cfg.get("gate", {}) or {}
    gate_enabled = bool(gate_cfg.get("enabled", False))
    gate_mode = str(gate_cfg.get("mode", "auto_merge"))
    staging_dir_rel = str(gate_cfg.get("staging_dir", "outbox/_staging"))
    rejected_dir_rel = str(gate_cfg.get("rejected_dir", "outbox/_rejected"))
    min_body_chars = int(gate_cfg.get("min_body_chars", 400))
    pdf_cfg = compile_cfg.get("pdf", {}) or {}
    pdf_enabled = bool(pdf_cfg.get("enabled", True))
    pdf_max_pages = int(pdf_cfg.get("max_pages", 30))

    system_prompt = read_prompt("compile_system.md")
    existing_titles_block = "\n".join(f"- {title}" for title in _collect_existing_titles(wiki_dir, title_limit))

    if changed_paths is None:
        candidates = [path for path in raw_dir.rglob("*") if path.is_file()]
    else:
        candidates = []
        for path in changed_paths:
            try:
                resolved = path.resolve()
            except Exception:
                continue
            if resolved.is_file() and raw_dir in resolved.parents:
                candidates.append(resolved)

    written: list[Path] = []
    for src in candidates:
        try:
            if not src.exists():
                continue
        except Exception:
            continue

        rel_src = src.relative_to(vault_root).as_posix()
        ext = src.suffix.lower()
        if ext not in SUPPORTED_TEXT_EXT and ext not in SUPPORTED_PDF_EXT and ext not in SUPPORTED_IMAGE_EXT:
            continue

        try:
            mtime = src.stat().st_mtime
        except FileNotFoundError:
            continue

        prev = state.get(rel_src, {})
        if prev.get("mtime") == mtime:
            continue

        out_rel = _map_source_to_wiki(rel_src)
        out_path = (vault_root / out_rel).resolve()
        ensure_dir(out_path.parent)

        staging_path = out_path
        rejected_dir = (vault_root / rejected_dir_rel).resolve()
        if gate_enabled and gate_mode == "auto_merge":
            staging_path = (vault_root / staging_dir_rel / Path(out_rel).name).resolve()
            ensure_dir(staging_path.parent)

        if out_path.exists() and not overwrite:
            continue

        title = _title_from_source(src)
        updated = now_iso()

        if ext in SUPPORTED_TEXT_EXT:
            content = read_text_file(src, max_chars=max_chars)
            user_prompt = _build_compile_user_prompt(
                rel_src=rel_src,
                title=title,
                content=content,
                existing_titles_block=existing_titles_block,
            )
            markdown = llm.generate_markdown(system_prompt=system_prompt, user_prompt=user_prompt)
        elif ext in SUPPORTED_PDF_EXT and pdf_enabled:
            content = _extract_pdf_text(src, max_pages=pdf_max_pages, max_chars=max_chars)
            if _looks_like_empty_pdf_text(content):
                markdown = _stub_note_markdown(title=title, rel_src=rel_src, updated=updated)
            else:
                user_prompt = _build_compile_user_prompt(
                    rel_src=rel_src,
                    title=title,
                    content=content,
                    existing_titles_block=existing_titles_block,
                )
                markdown = llm.generate_markdown(system_prompt=system_prompt, user_prompt=user_prompt)
        else:
            content = ""
            markdown = _stub_note_markdown(title=title, rel_src=rel_src, updated=updated)

        markdown = _normalize_llm_markdown(markdown)

        if not markdown.lstrip().startswith("---"):
            markdown = md_frontmatter(title=title, source=rel_src, updated=updated, tags=["compiled"]) + markdown

        try:
            if ext in SUPPORTED_TEXT_EXT or (ext in SUPPORTED_PDF_EXT and pdf_enabled):
                markdown = _filter_related_links_by_source(markdown, source_text=content)
        except Exception:
            pass

        try:
            markdown = apply_tag_cleanup_to_markdown(markdown, cfg=cfg)
        except Exception:
            pass

        staging_path.write_text(markdown, encoding="utf-8")
        final_path = staging_path
        if gate_enabled and gate_mode == "auto_merge":
            promote_or_reject(
                vault_root=vault_root,
                staging_path=staging_path,
                wiki_target_path=out_path,
                rejected_dir=rejected_dir,
                min_body_chars=min_body_chars,
                llm=llm,
                llm_enabled=bool((gate_cfg.get("llm", {}) or {}).get("enabled", False)),
                llm_min_score=int((gate_cfg.get("llm", {}) or {}).get("min_score", 70)),
                llm_on_error=str((gate_cfg.get("llm", {}) or {}).get("on_error", "approve_with_needs_review")),
            )
            final_path = out_path if out_path.exists() else rejected_dir / staging_path.name

        written.append(final_path)
        state[rel_src] = {"mtime": mtime, "wiki_rel": out_rel}

    save_state(state_file, state)

    try:
        index_cfg = compile_cfg.get("index", {}) or {}
        if bool(index_cfg.get("enabled", False)):
            update_index_file(
                vault_root=vault_root,
                wiki_dir=wiki_dir,
                index_path=vault_root / str(index_cfg.get("path", "wiki/_index.md")),
                recent_limit=int(index_cfg.get("recent_limit", 50)),
                group_by_folder=bool(index_cfg.get("group_by_folder", True)),
            )
    except Exception:
        pass

    try:
        wiki_written = [path for path in written if wiki_dir in path.parents]
        if wiki_written:
            update_index_for_paths(vault_root=vault_root, db_path=fts_db, wiki_paths=wiki_written)
    except Exception:
        pass

    try:
        health_cfg = compile_cfg.get("health", {}) or {}
        if bool(health_cfg.get("enabled", False)):
            write_health_report(
                vault_root=vault_root,
                wiki_dir=wiki_dir,
                out_path=vault_root / str(health_cfg.get("path", "wiki/_health.md")),
                max_items_per_section=int(health_cfg.get("max_items_per_section", 200)),
            )
    except Exception:
        pass

    try:
        moc_cfg = compile_cfg.get("moc", {}) or {}
        if bool(moc_cfg.get("enabled", False)):
            generate_moc(
                vault_root=vault_root,
                wiki_dir=wiki_dir,
                moc_dir=vault_root / str(moc_cfg.get("dir", "wiki/moc")),
                top_tag_limit=int(moc_cfg.get("top_tag_limit", 30)),
            )
    except Exception:
        pass

    try:
        glossary_cfg = compile_cfg.get("glossary", {}) or {}
        if bool(glossary_cfg.get("enabled", False)):
            build_glossary(
                vault_root=vault_root,
                wiki_dir=wiki_dir,
                out_dir=vault_root / str(glossary_cfg.get("dir", "wiki/glossary")),
                min_refs=int(glossary_cfg.get("min_refs", 2)),
                max_links_per_term=int(glossary_cfg.get("max_links_per_term", 200)),
                term_tag=str(glossary_cfg.get("term_tag", "term")),
                ignore_terms=[str(item) for item in (glossary_cfg.get("ignore_terms") or [])],
                max_term_len=int(glossary_cfg.get("max_term_len", 40)),
            )
    except Exception:
        pass

    try:
        verify_cfg = compile_cfg.get("verify", {}) or {}
        if bool(verify_cfg.get("enabled", True)):
            write_verify_report(
                vault_root=vault_root,
                cfg=cfg,
                wiki_dir=wiki_dir,
                written_paths=written,
                out_path=vault_root / str(verify_cfg.get("path", "wiki/_verify.md")),
            )
    except Exception:
        pass

    return written


def _map_source_to_wiki(rel_src: str) -> str:
    parts = rel_src.split("/")
    if parts and parts[0] == "raw":
        parts[0] = "wiki"
    else:
        parts = ["wiki"] + parts
    stem, _ = os.path.splitext(parts[-1])
    parts[-1] = safe_stem(stem) + ".md"
    return "/".join(parts)


def _title_from_source(src: Path) -> str:
    return src.stem.replace("_", " ").strip() or "Untitled"


def _build_compile_user_prompt(*, rel_src: str, title: str, content: str, existing_titles_block: str) -> str:
    return (
        f"File path (relative to vault): {rel_src}\n"
        f"Suggested title: {title}\n\n"
        "Existing note titles for possible wikilinks:\n"
        f"{existing_titles_block or '- none yet'}\n\n"
        "Compile the following raw material into one wiki note.\n\n"
        "==== Raw Material Start ====\n"
        f"{content}\n"
        "==== Raw Material End ====\n"
    )


def _extract_pdf_text(src: Path, *, max_pages: int, max_chars: int) -> str:
    try:
        import fitz
    except Exception:
        return "PyMuPDF is not installed, so PDF parsing is unavailable."

    try:
        doc = fitz.open(str(src))
    except Exception as exc:
        return f"Failed to open PDF: {exc}"

    parts: list[str] = []
    limit = doc.page_count if max_pages <= 0 else min(max_pages, doc.page_count)
    for index in range(limit):
        try:
            page = doc.load_page(index)
            text = (page.get_text("text") or "").strip()
        except Exception:
            text = ""
        if text:
            parts.append(f"\n\n---\n\n# Page {index + 1}\n\n{text}")
        if max_chars and sum(len(part) for part in parts) > max_chars:
            break

    doc.close()
    output = "".join(parts).strip()
    if not output:
        return "Text extraction was empty or too weak to trust."
    if max_chars and len(output) > max_chars:
        output = output[:max_chars] + "\n\n[...truncated...]"
    return output


def _looks_like_empty_pdf_text(text: str) -> bool:
    stripped = (text or "").strip()
    return not stripped or "Text extraction was empty" in stripped or len(stripped) < 80


def _stub_note_markdown(*, title: str, rel_src: str, updated: str) -> str:
    return (
        md_frontmatter(title=title, source=rel_src, updated=updated, tags=["stub"])
        + "# Stub Note\n\n"
        + "This source could not be compiled into a trustworthy note yet.\n\n"
        + "## Why\n\n"
        + "- The source was an image, or PDF text extraction was too weak.\n"
        + "- The system created a placeholder instead of hallucinating content.\n\n"
        + "## Source\n\n"
        + f"- `{rel_src}`\n"
    )
