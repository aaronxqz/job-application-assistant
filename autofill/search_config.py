"""Loads data/search_config.yaml -- keywords, company tokens, rate limits."""

from __future__ import annotations

import pathlib
from typing import Any

import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_SEARCH_CONFIG_PATH = REPO_ROOT / "data" / "search_config.yaml"


class SearchConfigError(RuntimeError):
    pass


def load_search_config(path: pathlib.Path | str | None = None) -> dict[str, Any]:
    path = pathlib.Path(path) if path else DEFAULT_SEARCH_CONFIG_PATH
    if not path.exists():
        raise SearchConfigError(
            f"No search config found at {path}.\n"
            f"See data/search_config.yaml for the expected format."
        )
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return raw
