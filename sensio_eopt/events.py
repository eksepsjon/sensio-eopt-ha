"""
Event parser for the Sensio Eopt / X-Comfort local SMUX protocol.

The controller sends SMUX-framed messages (\x01{body}\x02).  After
stripping the framing the body is plain text in one of these forms:

    RSN {seq} {name} {typeId} {enabled} {state} {value}
    SSN {seq} {name} {typeId} {enabled} {state} {value}
    {name} {typeId} {enabled} {state} {value}    (direct device state)
    end {function_name}                           (command confirmation)
    x_bm_st ACK_DIR seq={N}                      (keepalive)
    PANEL_BRIGHTNESS {N}                          (keepalive beacon)

Examples:
    RSN 59500 B_LightHallTrappEntre_ON 6 1 0 0
    RSN 42593 D_Trapp2etgHallTrappEntre 21 1 100 100
    D_Hall2etgHallTrappEntre 21 1 100 100
    end B_LightHallTrappEntre_ON
    x_bm_st ACK_DIR seq=13

Field meanings
--------------
seq        : short integer sequence number (RSN/SSN prefix)
name       : object / function name (B_* / D_* / M_*)
typeId     : 6  = function trigger (button pressed / command executed)
             21 = integer device value (dimmer level 0-255, relay 0/100)
             23 = float register (current scene index, setpoint, etc.)
value      : the new value (last field)

Object name conventions
-----------------------
B_*        : function trigger — same names as the commands we send
D_*        : dimmer/relay current integer value
M_*        : metadata register (current scene, save scene, etc.)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

# RSN/SSN {seq} {name} {typeId} {enabled} {state} {value}
_RSN_RE = re.compile(
    r"^(?:RSN|SSN)\s+(\d+)\s+(\S+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\S+)$"
)

# {name} {typeId} {enabled} {state} {value}  (direct device state lines, no prefix)
_DIRECT_RE = re.compile(
    r"^(\S+)\s+(\d+)\s+(\d+)\s+(\S+)\s+(\S+)$"
)


@dataclass
class SensioEoptEvent:
    """A single parsed event from the controller."""
    name: str            # object / function name (B_* / D_* / M_*)
    type_id: int         # 6 = trigger, 21 = int device, 23 = float register
    value_raw: str       # raw string value (last field)
    seq: int = 0         # RSN/SSN sequence number (0 if not present)
    controller_id: str = ""  # kept for compatibility (unused in SMUX protocol)

    # Convenience properties
    @property
    def is_trigger(self) -> bool:
        """Type 6: a B_* function was executed."""
        return self.type_id == 6

    @property
    def is_device_value(self) -> bool:
        """Type 21: integer device value (dimmer level / relay state)."""
        return self.type_id == 21

    @property
    def is_register(self) -> bool:
        """Type 23: float metadata register (scene index, setpoint, etc.)."""
        return self.type_id == 23

    @property
    def int_value(self) -> int:
        try:
            return int(float(self.value_raw))
        except ValueError:
            return 0

    @property
    def float_value(self) -> float:
        try:
            return float(self.value_raw)
        except ValueError:
            return 0.0

    @property
    def is_on(self) -> bool:
        """For relays and dimmers: True when value > 0."""
        return self.int_value > 0


def parse_event(line: str) -> Optional[SensioEoptEvent]:
    """
    Parse one SMUX message body into a SensioEoptEvent.
    Returns None for keepalive lines (x_bm_st, PANEL_BRIGHTNESS, end ...) and
    anything unrecognised.
    """
    line = line.strip()
    if not line:
        return None

    # RSN / SSN {seq} {name} {typeId} {enabled} {state} {value}
    m = _RSN_RE.match(line)
    if m:
        seq, name, type_id, _en, _st, value = m.groups()
        return SensioEoptEvent(name=name, type_id=int(type_id), value_raw=value, seq=int(seq))

    # Direct device state: {name} {typeId} {enabled} {state} {value}
    # Only match B_*/D_*/M_* names to avoid false positives on keepalives
    m = _DIRECT_RE.match(line)
    if m:
        name, type_id, _en, _st, value = m.groups()
        if name[1:2] == "_":  # B_, D_, M_, etc.
            return SensioEoptEvent(name=name, type_id=int(type_id), value_raw=value)

    return None


def device_name_from_event(event: SensioEoptEvent) -> Optional[str]:
    """
    Map a D_* event name back to the corresponding B_D_* function name.

    e.g. D_Hall2etgHallTrappEntre  ->  B_D_Hall2etgHallTrappEntre_SET

    Returns None if the event is not a D_* device value event.
    """
    if not (event.is_device_value and event.name.startswith("D_")):
        return None
    return "B_D_" + event.name[2:]
