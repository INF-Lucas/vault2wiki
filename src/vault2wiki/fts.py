from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml

_FM_RE = re.compile(r"^\s*---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_CJK_RE = re.compile(r"[\u4e00-\u9fff]+")


@dataclass
class FtsHit:
    rel_path: str
    stem: str
    title: str
    updated: str
    score: float
    snippet: str


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


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(db_path))
    connection.row_factory = sqlite3.Row
    return connection


def ensure_schema(connection: sqlite3.Connection) -> None:
    cur = connection.cursor()
    row = cur.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='notes'").fetchone()
    sql = str(row["sql"]) if row and row["sql"] else ""
    if "content_zh" not in sql:
        cur.execute("DROP TABLE IF EXISTS notes")

    cur.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS notes USING fts5(
          title,
          content,
          content_zh,
          path UNINDEXED,
          updated UNINDEXED,
          tags UNINDEXED,
          tokenize = 'unicode61'
        )
        """
    )
    connection.commit()


def zh_tokenize_bigrams(text: str) -> str:
    if not text:
        return ""

    tokens: list[str] = []
    for word in re.findall(r"[A-Za-z0-9_]{2,}", text):
        tokens.append(word.lower())

    for match in _CJK_RE.finditer(text):
        value = match.group(0)
        if len(value) == 1:
            tokens.append(value)
            continue
        for index in range(len(value) - 1):
            tokens.append(value[index : index + 2])

    return " ".join(tokens)


def _upsert_note(
    connection: sqlite3.Connection,
    *,
    rel_path: str,
    title: str,
    updated: str,
    tags: list[str],
    content: str,
) -> None:
    cur = connection.cursor()
    cur.execute("DELETE FROM notes WHERE path = ?", (rel_path,))
    cur.execute(
        "INSERT INTO notes(title, content, content_zh, path, updated, tags) VALUES(?,?,?,?,?,?)",
        (title, content, zh_tokenize_bigrams(content), rel_path, updated, ",".join(tags)),
    )


def rebuild_index(*, vault_root: Path, wiki_dir: Path, db_path: Path) -> None:
    connection = connect(db_path)
    ensure_schema(connection)
    cur = connection.cursor()
    cur.execute("DELETE FROM notes")

    for path in wiki_dir.rglob("*.md"):
        if _should_index_path(path):
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
        _upsert_note(
            connection,
            rel_path=rel_path,
            title=str(fm.get("title") or path.stem).strip(),
            updated=str(fm.get("updated") or "").strip(),
            tags=tags,
            content=text,
        )

    connection.commit()
    connection.close()


def update_index_for_paths(*, vault_root: Path, db_path: Path, wiki_paths: Iterable[Path]) -> None:
    connection = connect(db_path)
    ensure_schema(connection)
    for path in wiki_paths:
        if not path.exists() or path.suffix.lower() != ".md":
            continue
        if _should_index_path(path):
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
        _upsert_note(
            connection,
            rel_path=rel_path,
            title=str(fm.get("title") or path.stem).strip(),
            updated=str(fm.get("updated") or "").strip(),
            tags=tags,
            content=text,
        )

    connection.commit()
    connection.close()


def _is_probably_chinese(query: str) -> bool:
    return bool(_CJK_RE.search(query or ""))


def _build_match_query(query: str) -> str:
    q = (query or "").strip()
    if not q:
        return ""
    if _is_probably_chinese(q):
        zh = zh_tokenize_bigrams(q)
        if zh:
            return f"content_zh:{zh} OR title:{q}"
    return q


def search(*, db_path: Path, query: str, limit: int = 10) -> list[FtsHit]:
    q = (query or "").strip()
    if not q:
        return []

    connection = connect(db_path)
    ensure_schema(connection)
    cur = connection.cursor()
    match_query = _build_match_query(q)
    if not match_query:
        connection.close()
        return []

    rows = cur.execute(
        """
        SELECT
          path,
          title,
          updated,
          snippet(notes, 1, '[', ']', ' ... ', 12) AS snip,
          bm25(notes) AS score
        FROM notes
        WHERE notes MATCH ?
        ORDER BY score
        LIMIT ?
        """,
        (match_query, limit),
    ).fetchall()
    connection.close()

    hits: list[FtsHit] = []
    for row in rows:
        rel_path = str(row["path"])
        stem = Path(rel_path).stem
        hits.append(
            FtsHit(
                rel_path=rel_path,
                stem=stem,
                title=str(row["title"] or stem),
                updated=str(row["updated"] or ""),
                score=float(row["score"] or 0.0),
                snippet=str(row["snip"] or "").replace("\n", " ").strip(),
            )
        )
    return hits


def _should_index_path(path: Path) -> bool:
    if path.name.lower() in {"_index.md", "_health.md", "_verify.md"}:
        return True
    return "moc" in path.parts
