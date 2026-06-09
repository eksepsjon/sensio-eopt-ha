"""
Configuration management for sensio-eopt-control.

Credentials are stored in ~/.sensio_eopt/config.json.
They come from the supplier-provided smarthome.bash script:
    token  → token_id   (UUID, used as tokenId in LOCAL TCP LOGIN-TO)
    secret → token_secret
    url    → controller_ip can be discovered via ARP or router DHCP table

No OAuth2 or cloud API needed for local LAN control.
"""

from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from typing import Optional

def parse_smarthome_bash(
    text: str,
) -> tuple[str, str, str, list[tuple[str, str]]]:
    """Return (token_id, token_secret, mac, functions) from a smarthome.bash script.

    functions is a list of (internal_name, display_name) pairs.
    Raises ValueError with a short message on failure.
    """
    m = re.search(r"<<__BASE64__\s*([\s\S]+?)__BASE64__", text)
    if not m:
        raise ValueError("no base64 block found — paste the complete smarthome.bash file")

    try:
        decoded = base64.b64decode("".join(m.group(1).split())).decode("utf-8")
    except Exception:
        raise ValueError("failed to decode base64 block — the script may be corrupted")

    def _field(name: str) -> str:
        fm = re.search(rf'^{name}="([^"]+)"', decoded, re.MULTILINE)
        if not fm:
            raise ValueError(f"field '{name}' not found in decoded script")
        return fm.group(1)

    def _array(name: str) -> list[str]:
        am = re.search(rf'^{name}=\(\s*([\s\S]*?)\s*\)', decoded, re.MULTILINE)
        if not am:
            raise ValueError(f"array '{name}' not found in decoded script")
        return re.findall(r'"([^"]*)"', am.group(1))

    func_names = _array("func_names")
    nice_names = _array("nice_names")
    if len(func_names) != len(nice_names):
        raise ValueError(
            f"func_names ({len(func_names)}) and nice_names ({len(nice_names)}) "
            "have different lengths"
        )

    functions = list(zip(func_names, nice_names))
    return _field("token"), _field("secret"), _field("mac"), functions


CONFIG_DIR = Path.home() / ".sensio_eopt"
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
    controller_ip: str,
) -> None:
    data = _load()
    data.update(
        token_id=token_id,
        token_secret=token_secret,
        controller_ip=controller_ip,
    )
    _save(data)


def load_credentials() -> dict:
    """Return dict with token_id, token_secret, controller_ip (or empty strs)."""
    data = _load()
    return {
        "token_id": data.get("token_id", ""),
        "token_secret": data.get("token_secret", ""),
        "controller_ip": data.get("controller_ip", ""),
    }


def is_configured() -> bool:
    creds = load_credentials()
    return bool(creds["token_id"] and creds["token_secret"] and creds["controller_ip"])


FUNCTIONS_FILE = CONFIG_DIR / "functions.json"


def save_functions(functions: list[tuple[str, str]]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with FUNCTIONS_FILE.open("w", encoding="utf-8") as f:
        json.dump(functions, f, indent=2, ensure_ascii=False)


def load_functions() -> list[tuple[str, str]] | None:
    """Return saved (internal_name, display_name) pairs, or None if not saved yet."""
    if not FUNCTIONS_FILE.exists():
        return None
    with FUNCTIONS_FILE.open("r", encoding="utf-8") as f:
        return [tuple(pair) for pair in json.load(f)]


def clear_credentials() -> None:
    if CONFIG_FILE.exists():
        CONFIG_FILE.unlink()


# ---------------------------------------------------------------------------
# Object ID cache  (name → numeric controller ID)
# Populated from RSN events; persisted so d_obj queries work across sessions.
# ---------------------------------------------------------------------------

ID_CACHE_FILE = CONFIG_DIR / "id_cache.json"


def load_id_cache() -> dict[str, int]:
    """Return the name→numericId map saved from previous RSN observations."""
    if ID_CACHE_FILE.exists():
        try:
            with ID_CACHE_FILE.open("r", encoding="utf-8") as f:
                return {k: int(v) for k, v in json.load(f).items()}
        except (json.JSONDecodeError, ValueError):
            return {}
    return {}


def save_id_cache(cache: dict[str, int]) -> None:
    """Persist the name→numericId map to disk."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with ID_CACHE_FILE.open("w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, sort_keys=True)
    ID_CACHE_FILE.chmod(0o600)


def update_id_cache(new_ids: dict[str, int]) -> None:
    """Merge new name→id pairs into the persisted cache."""
    cache = load_id_cache()
    cache.update(new_ids)
    save_id_cache(cache)
