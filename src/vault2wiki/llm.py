from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from .util import md_frontmatter, now_iso


@dataclass
class LLMConfig:
    provider: str
    openai_model: str
    openai_base_url: Optional[str]
    openai_api_key: Optional[str] = None
    openai_fallback_model: Optional[str] = None
    openai_fallback_base_url: Optional[str] = None
    openai_fallback_api_key: Optional[str] = None
    anthropic_model: Optional[str] = None
    anthropic_api_key: Optional[str] = None


class LLMClient:
    def __init__(self, cfg: LLMConfig):
        self.cfg = cfg
        self._openai = None
        self._openai_fallback = None
        self._anthropic = None

    def _get_openai_client(self, *, base_url: Optional[str], api_key: Optional[str]):
        from openai import OpenAI

        if base_url:
            return OpenAI(api_key=api_key, base_url=base_url)
        return OpenAI(api_key=api_key)

    def generate_markdown(self, system_prompt: str, user_prompt: str) -> str:
        provider = (self.cfg.provider or "").strip().lower()
        if provider == "mock":
            return self._mock_generate(user_prompt)
        if provider == "openai":
            return self._openai_generate(system_prompt, user_prompt)
        if provider == "anthropic":
            return self._anthropic_generate(system_prompt, user_prompt)
        raise ValueError(f"Unsupported llm.provider: {self.cfg.provider}")

    def _openai_generate(self, system_prompt: str, user_prompt: str) -> str:
        if self._openai is None:
            self._openai = self._get_openai_client(
                base_url=self.cfg.openai_base_url,
                api_key=self.cfg.openai_api_key,
            )

        try:
            resp = self._openai.chat.completions.create(
                model=self.cfg.openai_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.2,
            )
            return (resp.choices[0].message.content or "").strip()
        except Exception as exc:
            if self.cfg.openai_fallback_base_url and self.cfg.openai_fallback_model:
                if self._openai_fallback is None:
                    self._openai_fallback = self._get_openai_client(
                        base_url=self.cfg.openai_fallback_base_url,
                        api_key=self.cfg.openai_fallback_api_key,
                    )
                resp = self._openai_fallback.chat.completions.create(
                    model=self.cfg.openai_fallback_model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=0.2,
                )
                return (resp.choices[0].message.content or "").strip()
            raise exc

    def _anthropic_generate(self, system_prompt: str, user_prompt: str) -> str:
        from anthropic import Anthropic

        if self._anthropic is None:
            self._anthropic = Anthropic(api_key=self.cfg.anthropic_api_key)

        resp = self._anthropic.messages.create(
            model=self.cfg.anthropic_model,
            max_tokens=2048,
            temperature=0.2,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )

        parts: list[str] = []
        for block in resp.content:
            text = getattr(block, "text", None)
            if text:
                parts.append(text)
        return "".join(parts).strip()

    def _mock_generate(self, user_prompt: str) -> str:
        if "Question:" in user_prompt and "Retrieved note excerpts:" in user_prompt:
            return self._mock_query_response(user_prompt)
        return self._mock_compile_response(user_prompt)

    def _mock_compile_response(self, user_prompt: str) -> str:
        rel_src = _extract_after_prefix(user_prompt, "File path (relative to vault): ") or "raw/unknown.md"
        title = _extract_after_prefix(user_prompt, "Suggested title: ") or "Untitled"
        content = _extract_between(
            user_prompt,
            "==== Raw Material Start ====\n",
            "\n==== Raw Material End ====",
        ).strip()
        summary = _summarize_lines(content, limit=3)
        bullets = _bullet_lines(content, limit=5)
        concepts = _concept_lines(content, limit=3)
        questions = _question_lines(content, limit=3)
        related_links = _extract_raw_wikilinks(content)
        return (
            md_frontmatter(title=title, source=rel_src, updated=now_iso(), tags=["mock", "compiled"])
            + "# Summary\n\n"
            + summary
            + "\n\n# Key Ideas\n\n"
            + "\n".join(f"- {line}" for line in bullets)
            + "\n\n# Concepts and Terms\n\n"
            + "\n".join(f"- {line}" for line in concepts)
            + "\n\n# Related Links\n\n"
            + (
                "\n".join(f"- [[{term}]]" for term in related_links)
                if related_links
                else "- None generated by the mock provider.\n"
            )
            + "\n# Follow-up Questions\n\n"
            + "\n".join(f"- {line}" for line in questions)
            + "\n\n# Source\n\n"
            + f"- `{rel_src}`\n"
        )

    def _mock_query_response(self, user_prompt: str) -> str:
        question = _extract_after_prefix(user_prompt, "Question: ") or "Unknown question"
        note_titles = re.findall(r"^### Note: (.+)$", user_prompt, flags=re.MULTILINE)
        cited = ", ".join(note_titles[:3]) if note_titles else "no notes"
        evidence = "\n".join(f"- Used note: `{title}`" for title in note_titles[:5]) or "- No retrieved notes were available."
        return (
            "# Conclusion\n\n"
            + f"This is a mock answer for: {question}\n\n"
            + f"The strongest available context came from {cited}.\n"
            + "\n## Evidence\n\n"
            + evidence
            + "\n\n## Next Steps\n\n"
            + "- Switch `llm.provider` from `mock` to `openai` or `anthropic` for real model output.\n"
            + "- The `openai` provider also supports OpenAI-compatible endpoints via `base_url`.\n"
        )


def _extract_after_prefix(text: str, prefix: str) -> str | None:
    for line in text.splitlines():
        if line.startswith(prefix):
            return line[len(prefix) :].strip()
    return None


def _extract_between(text: str, start: str, end: str) -> str:
    if start not in text or end not in text:
        return text
    return text.split(start, 1)[1].split(end, 1)[0]


def _sentence_chunks(text: str) -> list[str]:
    cleaned = [line.strip(" -\t") for line in text.splitlines() if line.strip()]
    joined = " ".join(cleaned)
    parts = re.split(r"(?<=[.!?。！？])\s+", joined)
    return [part.strip() for part in parts if part.strip()]


def _summarize_lines(text: str, limit: int) -> str:
    parts = _sentence_chunks(text)[:limit]
    return " ".join(parts) if parts else "No usable source text was available."


def _bullet_lines(text: str, limit: int) -> list[str]:
    candidates = _sentence_chunks(text)
    return candidates[:limit] if candidates else ["No key ideas extracted."]


def _concept_lines(text: str, limit: int) -> list[str]:
    words = re.findall(r"\b[A-Za-z][A-Za-z0-9_-]{3,}\b", text)
    seen: list[str] = []
    for word in words:
        if word.lower() in {item.lower() for item in seen}:
            continue
        seen.append(word)
        if len(seen) >= limit:
            break
    if not seen:
        return ["No distinct concepts extracted from the mock provider."]
    return [f"{word}: surfaced from the raw source and kept for later review." for word in seen]


def _question_lines(text: str, limit: int) -> list[str]:
    seeds = _sentence_chunks(text)[:limit]
    if not seeds:
        return ["What source material should be added next?"]
    return [f"What should we explore next about: {seed[:80]}?" for seed in seeds]


def _extract_raw_wikilinks(text: str) -> list[str]:
    matches = re.findall(r"\[\[([^\]\|#]+)(?:[|#][^\]]*)?\]\]", text or "")
    seen: set[str] = set()
    out: list[str] = []
    for match in matches:
        term = match.strip()
        if not term or term in seen:
            continue
        seen.add(term)
        out.append(term)
    return out[:10]
