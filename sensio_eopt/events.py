"""
Event parser for the Sensio Eopt / X-Comfort local SMUX protocol.

The controller sends SMUX-framed messages (\x01{body}\x02).  After
stripping the framing the body is plain text in one of these forms:

    RSN {seq} {name} {typeId} {enabled} {state} {value...}
    SSN {seq} {name} {typeId} {enabled} {state} {value...}
    {name} {typeId} {enabled} {state} {value}    (direct device state)
    end {function_name}                           (command confirmation)
    x_bm_st ACK_DIR seq={N}                      (keepalive)
    PANEL_BRIGHTNESS {N}                          (keepalive beacon)

Examples:
    RSN 59500 B_LightHallTrappEntre_ON 6 1 0 0
    RSN 42593 D_Trapp2etgHallTrappEntre 21 1 100 100
    SSN 2195 TH_Gang1etg0573 7 1 1 24.50 24.40 0.00
    SSN 3382 M_Gang1etg0573_Sc 23 1 0 24.500 18.000 10.000
    RSN 6016 R_VkGang1etg058 36 1 0 23.000 25.200 0.000 0.000 0.000
    SSN 68497 T_houseTimer 4 0 0 7 7f00010 00000f0 ...
    D_Hall2etgHallTrappEntre 21 1 100 100
    end B_LightHallTrappEntre_ON
    x_bm_st ACK_DIR seq=13

Field meanings
--------------
seq        : short integer sequence number (RSN/SSN prefix)
name       : object / function name (B_* / D_* / M_* / TH_* / R_* / T_*)
typeId     : 4  = timer/schedule data
             6  = function trigger (button pressed / command executed)
             7  = thermostat status (setpoint, current temp, floor temp)
             10 = heating zone sensor (S_Vk*Energy = watts, S_Vk*Temp = °C)
             13 = extended device value (min/max, safety-off)
             21 = integer device value (dimmer level 0-100, relay 0/100)
             23 = float register (current scene index, setpoint, etc.)
             36 = heating relay/valve controller status
value      : one or more values (space-separated)

Object name conventions
-----------------------
B_*        : function trigger — same names as the commands we send
D_*        : dimmer/relay current integer value
M_*        : metadata register (current scene, save scene, etc.)
TH_*       : thermostat status (setpoint + current + floor temperatures)
R_Vk*      : heating cable/valve controller (Varmekabel)
S_Vk*      : heating zone sensor (*Energy = watts, *Temp = °C)
T_*        : timer/schedule
D_MinMax*  : min/max energy tracking
D_SafeOff* : safety-off timer
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

# RSN/SSN {seq} {name} {typeId} {enabled} {state} {values...}
_RSN_RE = re.compile(
    r"^(?:RSN|SSN)\s+(\d+)\s+(\S+)\s+(\d+)\s+(\d+)\s+(\S+)\s+(.+)$"
)

# {name} {typeId} {enabled} {state} {value}  (direct device state lines, no prefix)
_DIRECT_RE = re.compile(
    r"^(\S+)\s+(\d+)\s+(\d+)\s+(\S+)\s+(\S+)$"
)


@dataclass
class SensioEoptEvent:
    """A single parsed event from the controller."""
    name: str            # object / function name
    type_id: int         # 4/6/7/13/21/23/36
    value_raw: str       # first value token (backwards compatible)
    seq: int = 0         # RSN/SSN sequence number (0 if not present)
    controller_id: str = ""  # kept for compatibility (unused in SMUX protocol)
    enabled: int = 0     # enabled flag from the protocol
    state: int = 0       # state field (e.g. heating active for thermostats)
    extra_values: list[str] = field(default_factory=list)

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
    def is_thermostat_status(self) -> bool:
        """Type 7: thermostat status with setpoint, current, and floor temps."""
        return self.type_id == 7

    @property
    def is_timer(self) -> bool:
        """Type 4: timer/schedule data."""
        return self.type_id == 4

    @property
    def is_heating_relay(self) -> bool:
        """Type 36: heating cable/valve controller (R_Vk*)."""
        return self.type_id == 36

    @property
    def is_heating_sensor(self) -> bool:
        """Type 10: heating zone sensor (S_Vk*Energy = watts, S_Vk*Temp = °C)."""
        return self.type_id == 10

    @property
    def sensor_unit(self) -> str:
        """Unit for type 10 sensors, derived from the name suffix."""
        if self.name.endswith("Energy"):
            return "W"
        if self.name.endswith("Temp"):
            return "°C"
        return ""

    @property
    def is_extended_device(self) -> bool:
        """Type 13: extended device value (D_MinMax*, D_SafeOff*)."""
        return self.type_id == 13

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
    def float_values(self) -> list[float]:
        """All values parsed as floats (value_raw + extra_values)."""
        result = []
        for v in [self.value_raw] + self.extra_values:
            try:
                result.append(float(v))
            except ValueError:
                break
        return result

    @property
    def is_on(self) -> bool:
        """For relays and dimmers: True when value > 0."""
        return self.int_value > 0

    @property
    def thermostat_setpoint(self) -> float:
        return self.float_value

    @property
    def thermostat_current_temp(self) -> float:
        if self.extra_values:
            try:
                return float(self.extra_values[0])
            except ValueError:
                pass
        return 0.0

    @property
    def thermostat_floor_temp(self) -> float:
        if len(self.extra_values) > 1:
            try:
                return float(self.extra_values[1])
            except ValueError:
                pass
        return 0.0

    @property
    def is_heating(self) -> bool:
        """For thermostat events: True when the state field indicates heating is active."""
        return self.state > 0


def parse_event(line: str) -> Optional[SensioEoptEvent]:
    """
    Parse one SMUX message body into a SensioEoptEvent.
    Returns None for keepalive lines (x_bm_st, PANEL_BRIGHTNESS, end ...) and
    anything unrecognised.
    """
    line = line.strip()
    if not line:
        return None

    # RSN / SSN {seq} {name} {typeId} {enabled} {state} {values...}
    m = _RSN_RE.match(line)
    if m:
        seq, name, type_id, en, st, values_str = m.groups()
        parts = values_str.split()
        return SensioEoptEvent(
            name=name,
            type_id=int(type_id),
            value_raw=parts[0],
            seq=int(seq),
            enabled=int(en),
            state=int(st) if st.lstrip("-").isdigit() else 0,
            extra_values=parts[1:],
        )

    # Direct device state: {name} {typeId} {enabled} {state} {value}
    # Only match B_*/D_*/M_* names to avoid false positives on keepalives
    m = _DIRECT_RE.match(line)
    if m:
        name, type_id, en, st, value = m.groups()
        if name[1:2] == "_":  # B_, D_, M_, etc.
            return SensioEoptEvent(
                name=name,
                type_id=int(type_id),
                value_raw=value,
                enabled=int(en),
                state=int(st) if st.lstrip("-").isdigit() else 0,
            )

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
