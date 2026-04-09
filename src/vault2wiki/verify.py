from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .util import now_iso


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""


def _try_import(module: str) -> Check:
    try:
        __import__(module)
        return Check(name=f"import {module}", ok=True)
    except Exception as exc:
        return Check(name=f"import {module}", ok=False, detail=str(exc))


def _check_fts(db_path: Path) -> Check:
    try:
        import sqlite3

        con = sqlite3.connect(str(db_path))
        cur = con.cursor()
        cur.execute("CREATE VIRTUAL TABLE IF NOT EXISTS _fts_check USING fts5(content, tokenize='unicode61')")
        cur.execute("INSERT INTO _fts_check(content) VALUES('hello')")
        cur.execute("SELECT count(*) FROM _fts_check WHERE _fts_check MATCH 'hello'")
        cur.fetchone()
        cur.execute("DROP TABLE _fts_check")
        con.commit()
        con.close()
        return Check(name="SQLite FTS5 available", ok=True)
    except Exception as exc:
        return Check(name="SQLite FTS5 available", ok=False, detail=str(exc))


def _display_path(base: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(base.resolve()).as_posix()
    except Exception:
        return path.name


def _check_file_exists(base: Path, path: Path) -> Check:
    display = _display_path(base, path)
    if path.exists() and path.stat().st_size > 0:
        return Check(name=f"Generated file: {display}", ok=True)
    return Check(name=f"Generated file: {display}", ok=False, detail="File missing or empty")


def _check_dir_exists(base: Path, path: Path) -> Check:
    display = _display_path(base, path)
    if path.exists() and path.is_dir():
        return Check(name=f"Directory exists: {display}", ok=True)
    return Check(name=f"Directory exists: {display}", ok=False, detail="Directory missing")


def write_verify_report(
    *,
    vault_root: Path,
    cfg: dict[str, Any],
    wiki_dir: Path,
    written_paths: list[Path],
    out_path: Path,
) -> None:
    paths_cfg = cfg["paths"]
    fts_db = (vault_root / (paths_cfg.get("fts_db") or ".vault2wiki/fts.sqlite3")).resolve()

    accepted = len([path for path in written_paths if wiki_dir in path.parents])
    rejected = len([path for path in written_paths if "outbox/_rejected" in path.as_posix()])
    staged = len([path for path in written_paths if "outbox/_staging" in path.as_posix()])

    checks = [
        _try_import("yaml"),
        _try_import("watchdog"),
        _try_import("openai"),
        _try_import("anthropic"),
        _try_import("fitz"),
        _check_fts(fts_db),
    ]

    compile_cfg = cfg.get("compile", {}) or {}
    index_cfg = compile_cfg.get("index", {}) or {}
    if index_cfg.get("enabled"):
        checks.append(_check_file_exists(vault_root, vault_root / str(index_cfg.get("path", "wiki/_index.md"))))
    health_cfg = compile_cfg.get("health", {}) or {}
    if health_cfg.get("enabled"):
        checks.append(_check_file_exists(vault_root, vault_root / str(health_cfg.get("path", "wiki/_health.md"))))
    moc_cfg = compile_cfg.get("moc", {}) or {}
    if moc_cfg.get("enabled"):
        checks.append(
            _check_file_exists(vault_root, vault_root / str(moc_cfg.get("dir", "wiki/moc")) / "_home.md")
        )
    gate_cfg = compile_cfg.get("gate", {}) or {}
    if gate_cfg.get("enabled"):
        checks.append(
            _check_dir_exists(vault_root, vault_root / str(gate_cfg.get("rejected_dir", "outbox/_rejected")))
        )

    ok_count = sum(1 for check in checks if check.ok)

    lines = [
        "---",
        'title: "Verification Report"',
        'source: "wiki/_verify.md"',
        f'updated: "{now_iso()}"',
        'tags: ["verify"]',
        "---",
        "",
        "# Verification Report",
        "",
        "## Compile Summary",
        "",
        f"- Files written or updated: {len(written_paths)}",
        f"- Promoted to wiki: {accepted}",
        f"- Rejected into outbox/_rejected: {rejected}",
        f"- Left in staging: {staged}",
        "",
        "## Checks",
        "",
        f"- Passed: {ok_count}/{len(checks)}",
        "",
    ]

    for check in checks:
        prefix = "[ok]" if check.ok else "[fail]"
        if check.detail:
            lines.append(f"- {prefix} {check.name} - {check.detail}")
        else:
            lines.append(f"- {prefix} {check.name}")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
