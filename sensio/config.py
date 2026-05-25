"""
Configuration management for sensio-control.

Credentials are stored in ~/.sensio/config.json.
They come from the supplier-provided smarthome.bash script:
    token  → token_id   (UUID, used as tokenId in LOCAL TCP LOGIN-TO)
    secret → token_secret
    mac    → mac         (controller MAC address)
    url    → controller_ip can be discovered via ARP or router DHCP table

No OAuth2 or cloud API needed for local LAN control.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

CONFIG_DIR = Path.home() / ".sensio"
CONFIG_FILE = CONFIG_DIR / "config.json"


def _load() -> dict:
    if CONFIG_FILE.exists():
        with CONFIG_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save(data: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with CONFIG_FILE.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    CONFIG_FILE.chmod(0o600)


def save_credentials(
    token_id: str,
    token_secret: str,
    mac: str,
    controller_ip: str,
) -> None:
    data = _load()
    data.update(
        token_id=token_id,
        token_secret=token_secret,
        mac=mac,
        controller_ip=controller_ip,
    )
    _save(data)


def load_credentials() -> dict:
    """Return dict with token_id, token_secret, mac, controller_ip (or empty strs)."""
    data = _load()
    return {
        "token_id": data.get("token_id", ""),
        "token_secret": data.get("token_secret", ""),
        "mac": data.get("mac", ""),
        "controller_ip": data.get("controller_ip", ""),
    }


def is_configured() -> bool:
    creds = load_credentials()
    return bool(creds["token_id"] and creds["token_secret"] and creds["controller_ip"])


def clear_credentials() -> None:
    if CONFIG_FILE.exists():
        CONFIG_FILE.unlink()
