from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def load_yaml(path: str | Path) -> dict:
    with Path(path).open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def load_fields() -> dict:
    return load_yaml(ROOT / "config" / "fields.yaml")["fields"]


def load_settings() -> dict:
    return load_yaml(ROOT / "config" / "settings.yaml")

