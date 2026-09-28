"""Loads config.yaml and environment secrets."""
from __future__ import annotations

import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def load_config(path: str | os.PathLike | None = None) -> dict:
    p = Path(path) if path else ROOT / "config.yaml"
    with open(p, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    cfg.setdefault("model", "claude-sonnet-5")
    cfg.setdefault("drafting", {})
    cfg.setdefault("pricing", {})
    cfg.setdefault("printify", {})
    # Environment overrides (GitHub repo variables) win over the file.
    env_map = {
        "PRINTIFY_SHOP_ID": ("printify", "shop_id"),
        "PRINTIFY_BLUEPRINT_ID": ("printify", "blueprint_id"),
        "PRINTIFY_PROVIDER_ID": ("printify", "print_provider_id"),
    }
    for env, (sect, key) in env_map.items():
        v = os.environ.get(env, "").strip()
        if v:
            cfg[sect][key] = int(v) if v.isdigit() else v
    if os.environ.get("FORGE_MODEL", "").strip():
        cfg["model"] = os.environ["FORGE_MODEL"].strip()
    return cfg


def secret(name: str, required: bool = True) -> str | None:
    v = os.environ.get(name, "").strip()
    if required and not v:
        raise SystemExit(
            f"Missing secret {name}. Add it on GitHub: Settings → Secrets and variables → Actions → New repository secret."
        )
    return v or None
