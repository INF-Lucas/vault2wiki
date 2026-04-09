from __future__ import annotations

import os
from importlib import resources
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from .llm import LLMClient, LLMConfig


def load_environment(vault_root: Path) -> None:
    load_dotenv(vault_root / ".env", override=False)


def resolve_config_path(vault_root: Path, config_arg: str) -> Path:
    raw = Path(config_arg)
    if raw.is_absolute():
        return raw
    return (vault_root / raw).resolve()


def load_config(vault_root: Path, config_path: Path) -> dict[str, Any]:
    cfg = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(cfg, dict):
        raise ValueError(f"Config file did not load as a mapping: {config_path}")
    cfg["vault_root"] = str(vault_root)
    return cfg


def build_llm(cfg: dict[str, Any]) -> LLMClient:
    llm_cfg = cfg["llm"]
    openai_cfg = llm_cfg.get("openai", {}) or {}
    fallback_cfg = openai_cfg.get("fallback", {}) or {}
    anthropic_cfg = llm_cfg.get("anthropic", {}) or {}

    client_cfg = LLMConfig(
        provider=str(llm_cfg.get("provider", "openai")),
        openai_model=str(openai_cfg.get("model", "gpt-4o-mini")),
        openai_base_url=openai_cfg.get("base_url") or None,
        openai_api_key=os.environ.get(str(openai_cfg.get("api_key_env") or "OPENAI_API_KEY")),
        openai_fallback_model=(str(fallback_cfg.get("model")).strip() if fallback_cfg.get("model") else None),
        openai_fallback_base_url=(str(fallback_cfg.get("base_url")).strip() if fallback_cfg.get("base_url") else None),
        openai_fallback_api_key=os.environ.get(
            str(fallback_cfg.get("api_key_env") or "OPENAI_FALLBACK_API_KEY")
        ),
        anthropic_model=str(anthropic_cfg.get("model", "claude-3-5-sonnet-latest")),
        anthropic_api_key=os.environ.get(str(anthropic_cfg.get("api_key_env") or "ANTHROPIC_API_KEY")),
    )
    return LLMClient(client_cfg)


def read_prompt(name: str) -> str:
    return resources.files("vault2wiki.prompts").joinpath(name).read_text(encoding="utf-8")
