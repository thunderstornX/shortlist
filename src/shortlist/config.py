"""Configuration and secrets, kept apart on purpose.

config.yaml is committed-safe and describes behaviour. Secrets live only in .env.
Nothing in this module ever writes a key to a log or an error message.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]

ENV_VAR_FOR_PROVIDER = {
    "openrouter": "OPENROUTER_API_KEY",
    "groq": "GROQ_API_KEY",
}


class ConfigError(RuntimeError):
    pass


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    p = Path(path) if path else ROOT / "config" / "config.yaml"
    if not p.exists():
        example = ROOT / "config" / "config.example.yaml"
        raise ConfigError(
            f"No config at {p}.\nCopy the example first:\n    cp {example} {p}"
        )
    with p.open() as fh:
        cfg = yaml.safe_load(fh) or {}
    if not cfg.get("model", {}).get("providers"):
        raise ConfigError(f"{p} has no model.providers list")
    return cfg


def load_secrets() -> None:
    load_dotenv(ROOT / ".env")


def api_key_for(provider: str) -> str | None:
    var = ENV_VAR_FOR_PROVIDER.get(provider)
    return os.environ.get(var) if var else None


def available_providers(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Providers that have a key present. Order is preserved as configured."""
    return [p for p in cfg["model"]["providers"] if api_key_for(p["name"])]
