"""Configuration loading with ``${VAR:-default}`` environment interpolation."""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = REPO_ROOT / "config"

_ENV_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)(?::-([^}]*))?\}")


def _interpolate(value: Any) -> Any:
    if isinstance(value, str):
        def repl(match: re.Match[str]) -> str:
            name, default = match.group(1), match.group(2)
            return os.environ.get(name, default if default is not None else "")

        return _ENV_PATTERN.sub(repl, value)
    if isinstance(value, dict):
        return {k: _interpolate(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_interpolate(v) for v in value]
    return value


def load_yaml(name: str) -> dict[str, Any]:
    path = CONFIG_DIR / name
    with path.open(encoding="utf-8") as fh:
        return _interpolate(yaml.safe_load(fh))


@lru_cache(maxsize=None)
def local_config() -> dict[str, Any]:
    return load_yaml("local.yaml")


@lru_cache(maxsize=None)
def financial_rules() -> dict[str, Any]:
    return load_yaml("financial-rules.yaml")


@lru_cache(maxsize=None)
def source_config() -> dict[str, Any]:
    return load_yaml("source-config.yaml")


def repo_path(relative: str | Path) -> Path:
    """Resolve a configured path relative to the repository root (absolute paths pass through)."""
    p = Path(relative)
    return p if p.is_absolute() else REPO_ROOT / p
