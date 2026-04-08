"""Helpers for loading project configuration files."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

PROFILE_PATH = Path(__file__).resolve().parent / "profile.yaml"


def load_profile() -> dict[str, Any]:
    """Load the candidate profile from YAML as a plain dict."""
    with PROFILE_PATH.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}

    if not isinstance(data, dict):
        raise ValueError("profile.yaml must contain a top-level mapping")

    return data
