from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Protocol

import yaml

_FM_RE = re.compile(r"^\s*---\s*\n(.*?)\n---\s*\n", re.DOTALL)


@dataclass
class GateResult:
    ok: bool
    reasons: list[str]
    score: int | None = None
    status: str | None = None


class _LLMLike(Protocol):
    def generate_markdown(self, system_prompt: str, user_prompt: str) -> str: ...


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


def _body(md_text: str) -> str:
    match = _FM_RE.match(md_text or "")
    if not match:
        return md_text or ""
    return (md_text[match.end() :] or "").strip()


def check_note_quality(md_text: str, *, min_body_chars: int = 400) -> GateResult:
    reasons: list[str] = []
    frontmatter = _parse_frontmatter(md_text)
    if not frontmatter:
        return GateResult(False, ["Missing YAML front matter"])

    for field in ["title", "source", "updated", "tags"]:
        if field == "tags":
            if not frontmatter.get("tags"):
                reasons.append("Missing field: tags")
        elif not str(frontmatter.get(field) or "").strip():
            reasons.append(f"Missing field: {field}")

    body = _body(md_text)
    if len(body) < min_body_chars:
        reasons.append(f"Body too short (<{min_body_chars} chars)")

    if "Stub Note" in md_text or "Text extraction was empty" in md_text:
        reasons.append("Likely stub content")

    return GateResult(len(reasons) == 0, reasons)


def promote_or_reject(
    *,
    vault_root: Path,
    staging_path: Path,
    wiki_target_path: Path,
    rejected_dir: Path,
    min_body_chars: int,
    llm: Optional[_LLMLike] = None,
    llm_enabled: bool = False,
    llm_min_score: int = 70,
    llm_on_error: str = "approve_with_needs_review",
) -> GateResult:
    markdown = staging_path.read_text(encoding="utf-8", errors="ignore")
    result = check_note_quality(markdown, min_body_chars=min_body_chars)

    llm_score: int | None = None
    llm_status: str | None = None
    llm_reasons: list[str] = []

    if result.ok and llm_enabled and llm is not None:
        try:
            llm_score, llm_reasons = llm_score_note(llm, markdown)
            if llm_score is None:
                raise ValueError("LLM did not return a parseable score")
            if llm_score < llm_min_score:
                result.ok = False
                result.reasons.append(f"LLM score too low: {llm_score} < {llm_min_score}")
                result.reasons.extend([f"LLM: {reason}" for reason in llm_reasons[:5]])
                llm_status = "rejected"
            else:
                llm_status = "approved"
        except Exception as exc:
            if llm_on_error == "reject":
                result.ok = False
                result.reasons.append(f"LLM gate failed: {exc}")
                llm_status = "rejected"
            else:
                llm_status = "needs_review"
                llm_reasons = [f"LLM gate failed: {exc}"]

    result.score = llm_score
    result.status = llm_status or ("approved" if result.ok else "rejected")

    if result.ok:
        staging_path.write_text(
            _annotate_approved_markdown(markdown, score=result.score, status=result.status or "approved"),
            encoding="utf-8",
        )
        wiki_target_path.parent.mkdir(parents=True, exist_ok=True)
        staging_path.replace(wiki_target_path)
        return result

    staging_path.write_text(_annotate_rejected_markdown(markdown, reasons=result.reasons), encoding="utf-8")
    rejected_dir.mkdir(parents=True, exist_ok=True)
    rejected_path = rejected_dir / staging_path.name
    suffix = 1
    while rejected_path.exists():
        rejected_path = rejected_dir / f"{staging_path.stem}-{suffix}{staging_path.suffix}"
        suffix += 1
    staging_path.replace(rejected_path)
    return result


def _annotate_rejected_markdown(md_text: str, *, reasons: list[str]) -> str:
    match = _FM_RE.match(md_text or "")
    if not match:
        fm = {
            "title": "",
            "source": "",
            "updated": "",
            "tags": ["rejected"],
            "gate_status": "rejected",
            "gate_reasons": reasons,
        }
        fm_text = yaml.safe_dump(fm, allow_unicode=True, sort_keys=False).strip()
        return f"---\n{fm_text}\n---\n\n{md_text}"

    fm_raw = match.group(1)
    body = md_text[match.end() :]
    try:
        fm = yaml.safe_load(fm_raw) or {}
        if not isinstance(fm, dict):
            fm = {}
    except Exception:
        fm = {}

    tags = fm.get("tags") or []
    if isinstance(tags, str):
        tags = [tags]
    if not isinstance(tags, list):
        tags = []
    if "rejected" not in tags:
        tags.append("rejected")
    fm["tags"] = tags
    fm["gate_status"] = "rejected"
    fm["gate_reasons"] = reasons
    fm_text = yaml.safe_dump(fm, allow_unicode=True, sort_keys=False).strip()
    return f"---\n{fm_text}\n---\n{body.lstrip()}"


def _annotate_approved_markdown(md_text: str, *, score: int | None, status: str) -> str:
    match = _FM_RE.match(md_text or "")
    if not match:
        return md_text

    fm_raw = match.group(1)
    body = md_text[match.end() :]
    try:
        fm = yaml.safe_load(fm_raw) or {}
        if not isinstance(fm, dict):
            fm = {}
    except Exception:
        fm = {}

    tags = fm.get("tags") or []
    if isinstance(tags, str):
        tags = [tags]
    if not isinstance(tags, list):
        tags = []
    if "approved" not in tags:
        tags.append("approved")
    if status == "needs_review" and "needs_review" not in tags:
        tags.append("needs_review")
    fm["tags"] = tags
    fm["gate_status"] = status
    if score is not None:
        fm["gate_score"] = int(score)
    fm_text = yaml.safe_dump(fm, allow_unicode=True, sort_keys=False).strip()
    return f"---\n{fm_text}\n---\n{body.lstrip()}"


def llm_score_note(llm: _LLMLike, md_text: str) -> tuple[int | None, list[str]]:
    system = (
        "You are auditing a generated knowledge-base note.\n"
        "Score it for source grounding, clarity, structure, and restraint.\n"
        'Return strict JSON: {"score": 0-100, "reasons": ["..."]}'
    )
    user = "Evaluate this Markdown note:\n\n" + md_text[:20000]
    output = (llm.generate_markdown(system_prompt=system, user_prompt=user) or "").strip()
    try:
        data = json.loads(output)
        score = int(data.get("score"))
        reasons = data.get("reasons") or []
        if not isinstance(reasons, list):
            reasons = [str(reasons)]
        return score, [str(reason) for reason in reasons]
    except Exception:
        return None, []
