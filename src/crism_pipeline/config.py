"""Carga de configuración YAML del pipeline."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"


def load_yaml(name: str) -> dict[str, Any]:
    path = CONFIG_DIR / name
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def pipeline_config() -> dict[str, Any]:
    return load_yaml("pipeline.yaml")


def viviano_config() -> dict[str, Any]:
    return load_yaml("viviano2014.yaml")


def resolve_path(key: str) -> Path:
    rel = pipeline_config()["paths"][key]
    return (ROOT / rel).resolve()
