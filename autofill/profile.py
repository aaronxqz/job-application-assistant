"""Loads and flattens data/profile.yaml into a simple lookup dict."""

from __future__ import annotations

import pathlib
from dataclasses import dataclass
from typing import Any

import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_PROFILE_PATH = REPO_ROOT / "data" / "profile.yaml"


class ProfileError(RuntimeError):
    pass


@dataclass
class Profile:
    raw: dict[str, Any]
    path: pathlib.Path

    def flat(self) -> dict[str, Any]:
        """Return dotted-path -> value, e.g. {'personal.first_name': 'Jane', ...}."""
        out: dict[str, Any] = {}

        def _walk(prefix: str, node: Any) -> None:
            if isinstance(node, dict):
                for k, v in node.items():
                    _walk(f"{prefix}.{k}" if prefix else k, v)
            else:
                out[prefix] = node

        _walk("", self.raw)
        return out

    def get(self, dotted_path: str, default: Any = None) -> Any:
        node: Any = self.raw
        for part in dotted_path.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def resume_path(self) -> pathlib.Path:
        p = pathlib.Path(self.get("resume.file_path", "")).expanduser()
        if not p.is_absolute():
            p = self.path.parent / p
        return p


def load_profile(path: pathlib.Path | str | None = None) -> Profile:
    path = pathlib.Path(path) if path else DEFAULT_PROFILE_PATH
    if not path.exists():
        raise ProfileError(
            f"No profile found at {path}.\n"
            f"Copy data/profile.example.yaml to data/profile.yaml and fill it in first."
        )
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return Profile(raw=raw, path=path)
