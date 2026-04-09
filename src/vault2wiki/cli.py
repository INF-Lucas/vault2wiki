from __future__ import annotations

import argparse
import time
from datetime import datetime
from pathlib import Path
from threading import Lock, Timer

from .compiler import compile_paths
from .config import build_llm, load_config, load_environment, read_prompt, resolve_config_path
from .fts import rebuild_index, search as fts_search
from .glossary import build_glossary
from .health import write_health_report
from .indexer import update_index_file
from .moc import generate_moc
from .search import load_notes_for_context, simple_search_markdown
from .util import ensure_dir, safe_stem
from .verify import write_verify_report

APP_CLI_NAME = "vault2wiki"


def _resolve_runtime(vault_arg: str, config_arg: str) -> tuple[Path, dict]:
    vault_root = Path(vault_arg).resolve()
    config_path = resolve_config_path(vault_root, config_arg)
    if not config_path.exists():
        raise FileNotFoundError(f"Missing config file: {config_path}")
    load_environment(vault_root)
    cfg = load_config(vault_root, config_path)
    return vault_root, cfg


def cmd_compile(args: argparse.Namespace) -> int:
    vault_root, cfg = _resolve_runtime(args.vault, args.config)
    llm = build_llm(cfg)
    written = compile_paths(vault_root=vault_root, cfg=cfg, llm=llm, changed_paths=None)
    print(f"[{APP_CLI_NAME}] compiled {len(written)} file(s)")
    return 0


def cmd_query(args: argparse.Namespace) -> int:
    vault_root, cfg = _resolve_runtime(args.vault, args.config)
    llm = build_llm(cfg)
    paths_cfg = cfg["paths"]
    wiki_dir = (vault_root / paths_cfg["wiki_dir"]).resolve()
    outbox_dir = (vault_root / paths_cfg["outbox_dir"]).resolve()
    ensure_dir(outbox_dir)

    query_cfg = cfg.get("query", {}) or {}
    max_context_notes = int(query_cfg.get("max_context_notes", 8))
    max_note_chars = int(query_cfg.get("max_note_chars", 8000))
    search_mode = str((query_cfg.get("search", {}) or {}).get("mode", "simple")).lower()

    if search_mode == "fts":
        db_path = (vault_root / (paths_cfg.get("fts_db") or ".vault2wiki/fts.sqlite3")).resolve()
        try:
            fts_hits = fts_search(db_path=db_path, query=args.question, limit=max_context_notes)
            if fts_hits:
                context_notes = []
                for hit in fts_hits:
                    note_path = (vault_root / hit.rel_path).resolve()
                    content = note_path.read_text(encoding="utf-8", errors="ignore")
                    content = f"(matched snippet: {hit.snippet})\n\n{content}"
                    if len(content) > max_note_chars:
                        content = content[:max_note_chars] + "\n\n[...truncated...]"
                    context_notes.append((hit.title, content))
            else:
                hits = simple_search_markdown(
                    wiki_dir=wiki_dir,
                    query=args.question,
                    max_hits=max_context_notes,
                    max_chars_per_note=max_note_chars,
                )
                context_notes = load_notes_for_context(hits, max_note_chars=max_note_chars)
        except Exception:
            hits = simple_search_markdown(
                wiki_dir=wiki_dir,
                query=args.question,
                max_hits=max_context_notes,
                max_chars_per_note=max_note_chars,
            )
            context_notes = load_notes_for_context(hits, max_note_chars=max_note_chars)
    else:
        hits = simple_search_markdown(
            wiki_dir=wiki_dir,
            query=args.question,
            max_hits=max_context_notes,
            max_chars_per_note=max_note_chars,
        )
        context_notes = load_notes_for_context(hits, max_note_chars=max_note_chars)

    system_prompt = read_prompt("query_system.md")
    user_prompt = _build_query_user_prompt(args.question, context_notes)
    answer = llm.generate_markdown(system_prompt=system_prompt, user_prompt=user_prompt)

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    filename = safe_stem(f"{timestamp}-{args.question[:40]}") + ".md"
    out_path = outbox_dir / filename
    out_path.write_text(answer, encoding="utf-8")
    print(f"[{APP_CLI_NAME}] wrote answer to {out_path}")
    return 0


def _build_query_user_prompt(question: str, context_notes: list[tuple[str, str]]) -> str:
    blocks = [f"### Note: {title}\n\n{content}" for title, content in context_notes]
    context = "\n\n---\n\n".join(blocks) if blocks else "(No matching notes. Suggest what to add.)"
    return f"Question: {question}\n\nRetrieved note excerpts:\n\n{context}\n"


def cmd_reindex(args: argparse.Namespace) -> int:
    vault_root, cfg = _resolve_runtime(args.vault, args.config)
    paths_cfg = cfg["paths"]
    wiki_dir = (vault_root / paths_cfg["wiki_dir"]).resolve()
    db_path = (vault_root / (paths_cfg.get("fts_db") or ".vault2wiki/fts.sqlite3")).resolve()
    rebuild_index(vault_root=vault_root, wiki_dir=wiki_dir, db_path=db_path)
    print(f"[{APP_CLI_NAME}] rebuilt FTS index at {db_path}")
    return 0


def cmd_health(args: argparse.Namespace) -> int:
    vault_root, cfg = _resolve_runtime(args.vault, args.config)
    paths_cfg = cfg["paths"]
    wiki_dir = (vault_root / paths_cfg["wiki_dir"]).resolve()
    health_cfg = (cfg.get("compile", {}) or {}).get("health", {}) or {}
    out_path = vault_root / str(health_cfg.get("path", "wiki/_health.md"))
    write_health_report(
        vault_root=vault_root,
        wiki_dir=wiki_dir,
        out_path=out_path,
        max_items_per_section=int(health_cfg.get("max_items_per_section", 200)),
    )
    print(f"[{APP_CLI_NAME}] wrote health report to {out_path}")
    return 0


def cmd_maintain(args: argparse.Namespace) -> int:
    vault_root, cfg = _resolve_runtime(args.vault, args.config)
    _run_maintenance(vault_root=vault_root, cfg=cfg)
    print(f"[{APP_CLI_NAME}] maintenance complete")
    return 0


def _run_maintenance(*, vault_root: Path, cfg: dict) -> None:
    paths_cfg = cfg["paths"]
    compile_cfg = cfg.get("compile", {}) or {}
    wiki_dir = (vault_root / paths_cfg["wiki_dir"]).resolve()
    db_path = (vault_root / (paths_cfg.get("fts_db") or ".vault2wiki/fts.sqlite3")).resolve()

    rebuild_index(vault_root=vault_root, wiki_dir=wiki_dir, db_path=db_path)

    index_cfg = compile_cfg.get("index", {}) or {}
    if bool(index_cfg.get("enabled", False)):
        update_index_file(
            vault_root=vault_root,
            wiki_dir=wiki_dir,
            index_path=vault_root / str(index_cfg.get("path", "wiki/_index.md")),
            recent_limit=int(index_cfg.get("recent_limit", 50)),
            group_by_folder=bool(index_cfg.get("group_by_folder", True)),
        )

    health_cfg = compile_cfg.get("health", {}) or {}
    if bool(health_cfg.get("enabled", False)):
        write_health_report(
            vault_root=vault_root,
            wiki_dir=wiki_dir,
            out_path=vault_root / str(health_cfg.get("path", "wiki/_health.md")),
            max_items_per_section=int(health_cfg.get("max_items_per_section", 200)),
        )

    moc_cfg = compile_cfg.get("moc", {}) or {}
    if bool(moc_cfg.get("enabled", False)):
        generate_moc(
            vault_root=vault_root,
            wiki_dir=wiki_dir,
            moc_dir=vault_root / str(moc_cfg.get("dir", "wiki/moc")),
            top_tag_limit=int(moc_cfg.get("top_tag_limit", 30)),
        )

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

    gate_cfg = compile_cfg.get("gate", {}) or {}
    if bool(gate_cfg.get("enabled", False)):
        ensure_dir(vault_root / str(gate_cfg.get("staging_dir", "outbox/_staging")))
        ensure_dir(vault_root / str(gate_cfg.get("rejected_dir", "outbox/_rejected")))

    verify_cfg = compile_cfg.get("verify", {}) or {}
    if bool(verify_cfg.get("enabled", True)):
        write_verify_report(
            vault_root=vault_root,
            cfg=cfg,
            wiki_dir=wiki_dir,
            written_paths=[],
            out_path=vault_root / str(verify_cfg.get("path", "wiki/_verify.md")),
        )


def cmd_watch(args: argparse.Namespace) -> int:
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer

    class DebouncedCompiler(FileSystemEventHandler):
        def __init__(self, *, vault_root: Path, cfg: dict):
            self.vault_root = vault_root
            self.cfg = cfg
            self.llm = build_llm(cfg)
            self.debounce_seconds = float(cfg.get("compile", {}).get("debounce_seconds", 2))
            self._lock = Lock()
            self._timer: Timer | None = None
            self._changed: set[Path] = set()

        def on_any_event(self, event) -> None:
            if getattr(event, "is_directory", False):
                return
            src_path = Path(getattr(event, "src_path", "")).resolve()
            try:
                if not src_path.exists():
                    return
            except Exception:
                return
            with self._lock:
                self._changed.add(src_path)
                if self._timer:
                    self._timer.cancel()
                self._timer = Timer(self.debounce_seconds, self._flush)
                self._timer.daemon = True
                self._timer.start()

        def _flush(self) -> None:
            with self._lock:
                changed = sorted(self._changed)
                self._changed.clear()
                self._timer = None
            if not changed:
                return
            try:
                written = compile_paths(vault_root=self.vault_root, cfg=self.cfg, llm=self.llm, changed_paths=None)
                print(f"[{APP_CLI_NAME}] compiled {len(written)} file(s)")
            except Exception as exc:
                print(f"[{APP_CLI_NAME}] compile error ignored while watching: {exc}")

    vault_root, cfg = _resolve_runtime(args.vault, args.config)
    llm = build_llm(cfg)
    compile_paths(vault_root=vault_root, cfg=cfg, llm=llm, changed_paths=None)

    raw_dir = (vault_root / cfg["paths"]["raw_dir"]).resolve()
    raw_dir.mkdir(parents=True, exist_ok=True)

    observer = Observer()
    handler = DebouncedCompiler(vault_root=vault_root, cfg=cfg)
    observer.schedule(handler, str(raw_dir), recursive=True)
    observer.start()

    print(f"[{APP_CLI_NAME}] watching {raw_dir}")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print(f"\n[{APP_CLI_NAME}] stopping watcher")
        observer.stop()
        observer.join()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=APP_CLI_NAME,
        description="Compile raw notes into an Obsidian-friendly LLM-managed wiki / 将原始材料编译成适合 Obsidian 风格 vault 的 LLM wiki",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_common(subparser: argparse.ArgumentParser) -> None:
        subparser.add_argument("--vault", type=str, default=".", help="Path to the target vault / 目标 vault 路径")
        subparser.add_argument(
            "--config",
            type=str,
            default="config.yaml",
            help="Config path, absolute or relative to the vault root / 配置文件路径，可为绝对或相对 vault 的路径",
        )

    compile_parser = subparsers.add_parser("compile", help="Compile raw material into wiki notes / 编译 raw 内容到 wiki")
    add_common(compile_parser)
    compile_parser.set_defaults(func=cmd_compile)

    watch_parser = subparsers.add_parser("watch", help="Watch raw/ and compile changes continuously / 持续监听 raw 并自动编译")
    add_common(watch_parser)
    watch_parser.set_defaults(func=cmd_watch)

    query_parser = subparsers.add_parser("query", help="Answer a question over wiki notes / 在 wiki 上做问答")
    add_common(query_parser)
    query_parser.add_argument("question", type=str, help="Question to ask the knowledge base / 你的问题")
    query_parser.set_defaults(func=cmd_query)

    reindex_parser = subparsers.add_parser("reindex", help="Rebuild the local FTS index / 重建本地 FTS 索引")
    add_common(reindex_parser)
    reindex_parser.set_defaults(func=cmd_reindex)

    health_parser = subparsers.add_parser("health", help="Regenerate the health report / 重建健康检查报告")
    add_common(health_parser)
    health_parser.set_defaults(func=cmd_health)

    maintain_parser = subparsers.add_parser(
        "maintain",
        help="Rebuild derived wiki artifacts without LLM calls / 无需 LLM 重建派生产物",
    )
    add_common(maintain_parser)
    maintain_parser.set_defaults(func=cmd_maintain)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
