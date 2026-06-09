"""
Controller function index for this Sensio installation.

Loaded from ~/.sensio/functions.json (written by `sensio config -f smarthome.bash`).
Run that command first; FUNCTIONS will be empty until then.

Each entry: (internal_name, display_name).

Usage:
    from sensio.functions import FUNCTIONS, find_function
    fn = find_function("kitchen light on")
    # fn -> ("B_LightKjkkenStue_ON", "Kjøkken/Stue Light On")
"""

from __future__ import annotations
from typing import Optional

from .config import load_functions

FUNCTIONS: list[tuple[str, str]] = load_functions() or []


def find_function(query: str) -> Optional[tuple[str, str]]:
    """Find a function by display name or internal name (case-insensitive, partial match).

    Returns (func_name, display_name) or None.
    Tries exact display-name match first, then partial match on both name fields.
    """
    q = query.lower()
    for func, label in FUNCTIONS:
        if q == label.lower() or q == func.lower():
            return (func, label)
    for func, label in FUNCTIONS:
        if q in label.lower() or q in func.lower():
            return (func, label)
    return None
