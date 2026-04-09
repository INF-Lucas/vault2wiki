from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Iterable

from .util import read_text_file


@dataclass
class NoteHit:
    path: Path
    title: str
    score: float
    snippet: str


def simple_search_markdown(
    *,
    wiki_dir: Path,
    query: str,
    max_hits: int = 10,
    max_chars_per_note: int = 8000,
) -> list[NoteHit]:
    q = (query or "").strip().lower()
    if not q:
        return []

    query_tokens = _query_tokens(q)
    hits: list[NoteHit] = []
    for path in wiki_dir.rglob("*.md"):
        if _should_search_path(path):
            continue
        text = read_text_file(path, max_chars=max_chars_per_note)
        lowered = text.lower()
        exact_index = lowered.find(q)
        token_hits = [(token, lowered.find(token)) for token in query_tokens]
        token_hits = [(token, index) for token, index in token_hits if index >= 0]

        if exact_index < 0 and not token_hits:
            continue

        if exact_index >= 0:
            index = exact_index
            score = 1000.0 / (1 + exact_index)
        else:
            index = min(index for _, index in token_hits)
            overlap = len(token_hits)
            score = overlap * 10.0 + (1.0 / (1 + index))

        start = max(0, index - 120)
        end = min(len(text), index + 240)
        snippet = text[start:end].replace("\n", " ").strip()
        hits.append(NoteHit(path=path, title=path.stem, score=score, snippet=snippet))

    hits.sort(key=lambda hit: hit.score, reverse=True)
    return hits[:max_hits]


def load_notes_for_context(hits: Iterable[NoteHit], max_note_chars: int) -> list[tuple[str, str]]:
    return [(hit.title, read_text_file(hit.path, max_chars=max_note_chars)) for hit in hits]


def _query_tokens(query: str) -> list[str]:
    ascii_tokens = re.findall(r"[a-z0-9_]{2,}", query)
    cjk_sequences = re.findall(r"[\u4e00-\u9fff]{2,}", query)
    cjk_tokens: list[str] = []
    for sequence in cjk_sequences:
        if len(sequence) == 2:
            cjk_tokens.append(sequence)
            continue
        for index in range(len(sequence) - 1):
            cjk_tokens.append(sequence[index : index + 2])

    seen: set[str] = set()
    out: list[str] = []
    for token in ascii_tokens + cjk_tokens:
        if token in seen:
            continue
        seen.add(token)
        out.append(token)
    return out


def _should_search_path(path: Path) -> bool:
    if path.name.lower() in {"_index.md", "_health.md", "_verify.md"}:
        return True
    return "moc" in path.parts
