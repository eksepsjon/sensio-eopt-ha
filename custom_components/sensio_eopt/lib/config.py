"""
Object ID cache for the Sensio controller.

Stores name -> numeric controller ID mappings discovered from RSN events.
Persisted to ~/.sensio/id_cache.json so d_obj queries work across sessions.

Note: This module is used by the async controller to pre-populate state
on connect. The cache lives in the HA host's home directory under ~/.sensio/.
"""

from __future__ import annotations

import json
from pathlib import Path

CONFIG_DIR = Path.home() / ".sensio"
ID_CACHE_FILE = CONFIG_DIR / "id_cache.json"


def load_id_cache() -> dict[str, int]:
    """Return the name->numericId map saved from previous RSN observations."""
    if ID_CACHE_FILE.exists():
        try:
            with ID_CACHE_FILE.open("r", encoding="utf-8") as f:
                return {k: int(v) for k, v in json.load(f).items()}
        except Exception:
            return {}
    return {}


def save_id_cache(cache: dict[str, int]) -> None:
    """Persist the name->numericId map to disk."""
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with ID_CACHE_FILE.open("w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2, sort_keys=True)
    except Exception:
        pass


def update_id_cache(new_ids: dict[str, int]) -> None:
    """Merge new name->id pairs into the persisted cache."""
    cache = load_id_cache()
    cache.update(new_ids)
    save_id_cache(cache)
