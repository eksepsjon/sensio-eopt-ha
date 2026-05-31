"""
Device model for a Sensio/X-Comfort installation.

Parses the flat list of B_* function names into logical device objects
that map naturally to Home Assistant entity types:

  SensioLight       → HA light  (on/off + lighting scenes)
  SensioDimmer      → HA light  (brightness 0-100 percent, converted to 0-255 for HA)
  SensioRelay       → HA switch
  SensioThermostat  → HA climate (floor heating)
  SensioModeSelector→ HA select  (home/away/night/vacation per zone)
  SensioScene       → HA scene / button (house-wide modes, leftover B_* triggers)

Usage:
    from sensio.devices import discover_devices
    from sensio.functions import FUNCTIONS

    registry = discover_devices(FUNCTIONS)
    for light in registry.lights:
        print(light.name, light.func_on)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Device dataclasses
# ---------------------------------------------------------------------------

@dataclass
class SensioLight:
    """A zone light group controllable as on/off with optional scenes."""
    unique_id: str          # e.g. "B_LightUtelys"
    name: str               # e.g. "Utelys Light"
    func_on: str            # B_Light*_ON
    func_off: str           # B_Light*_OFF
    func_toggle: Optional[str]      # B_Light*_ToggleOn (may not exist)
    scenes: list[str]       # [B_Light*_Sc1, ..._Sc4] (those that exist)
    # optimistic state (updated from events or after commands)
    is_on: bool = False


@dataclass
class SensioDimmer:
    """A dimmable channel; brightness controlled via a single _SET function."""
    unique_id: str          # e.g. "B_D_SpotlightsKjkkenKjkkenStu"
    name: str               # display name from bash script
    func_set: str           # the B_D_* function name
    # optimistic state — stored in controller native scale (0-100 percent)
    brightness_pct: int = 0


@dataclass
class SensioRelay:
    """A binary output (relay) with separate on/off functions."""
    unique_id: str          # e.g. "B_R_UtelysUtelys"
    name: str               # cleaned display name
    func_on: str
    func_off: str
    # optimistic state
    is_on: bool = False


@dataclass
class SensioThermostat:
    """
    A floor-heating zone thermostat.

    The controller exposes temperature as increment/decrement buttons and
    (optionally) a direct-set command.  Three independent setpoints (states)
    can be stored as scenes.

    Temperature encoding for func_set: value = int(°C × 10)
    e.g. 21.5 °C → new_state B_Vaskerom0533_Set 215
    (This is the X-Comfort convention; verify with your installation.)
    """
    unique_id: str          # e.g. "Vaskerom0533"
    name: str               # e.g. "Vaskerom"
    zone_key: str           # normalised zone key for thermostat↔mode-selector linking
    func_dec: str           # B_*_Temp_Dec
    func_inc: str           # B_*_Temp_Inc
    func_set: Optional[str]  # B_*_Set  (value = °C × 10)
    preset_scenes: list[str]  # [B_*_Sc1, _Sc2, _Sc3]
    # optimistic state
    target_temperature: float = 21.0
    preset: str = "none"    # "sc1", "sc2", "sc3"


@dataclass
class SensioModeSelector:
    """
    A zone or house-wide mode selector (home / away / night / vacation).
    Maps to an HA select entity.
    """
    unique_id: str              # e.g. "VaskeromMode"
    name: str                   # e.g. "Vaskerom Mode"
    zone_key: str               # normalised zone key, matches SensioThermostat.zone_key
    options: dict[str, str]     # {"home": "B_VaskeromMode_In", "away": ..., ...}
    current_option: str = "home"


@dataclass
class SensioScene:
    """
    A one-shot trigger (alarm reset, house-wide scene, temperature preset).
    Maps to an HA button or HA scene entity.
    """
    unique_id: str
    name: str
    func: str
    value: int = 0


@dataclass
class DeviceRegistry:
    """All discovered devices for one Sensio installation."""
    lights: list[SensioLight] = field(default_factory=list)
    dimmers: list[SensioDimmer] = field(default_factory=list)
    relays: list[SensioRelay] = field(default_factory=list)
    thermostats: list[SensioThermostat] = field(default_factory=list)
    mode_selectors: list[SensioModeSelector] = field(default_factory=list)
    scenes: list[SensioScene] = field(default_factory=list)

    def all_devices(self):
        """Iterate over every device regardless of type."""
        return (
            self.lights
            + self.dimmers
            + self.relays
            + self.thermostats
            + self.mode_selectors
            + self.scenes
        )


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

# Regexes for the four primary grouping patterns
_LIGHT_ON_RE = re.compile(r"^(B_Light.+)_ON$")
_RELAY_ON_RE = re.compile(r"^(B_R_.+)_ON$")
_THERMO_DEC_RE = re.compile(r"^(B_.+\d{3,4})_Temp_Dec$")
_MODE_AWAY_RE = re.compile(r"^(B_.+Mode)_Away$")


def _strip_digits(s: str) -> str:
    """Strip trailing digits from an internal zone key. 'Vaskerom0533' → 'Vaskerom'."""
    return re.sub(r"\d+$", "", s)


def discover_devices(functions: list[tuple[str, str]]) -> DeviceRegistry:
    """
    Parse a list of (internal_name, display_name) tuples into a DeviceRegistry.

    Pass FUNCTIONS from sensio.functions:
        from sensio.functions import FUNCTIONS
        registry = discover_devices(FUNCTIONS)
    """
    func_set = {fn for fn, _ in functions}
    consumed: set[str] = set()
    registry = DeviceRegistry()

    # ------------------------------------------------------------------
    # 1. Dimmers  (B_D_* — each function is its own dimmer channel)
    # ------------------------------------------------------------------
    for fn, lbl in functions:
        if fn.startswith("B_D_"):
            # Display names look like "Spotlights KjøkkenSet" — strip trailing "Set"
            name = lbl[:-3].strip() if lbl.endswith("Set") else lbl
            registry.dimmers.append(SensioDimmer(
                unique_id=fn,
                name=name,
                func_set=fn,
            ))
            consumed.add(fn)

    # ------------------------------------------------------------------
    # 2. Relays  (B_R_*_ON / B_R_*_OFF pairs)
    # ------------------------------------------------------------------
    for fn, lbl in functions:
        if fn in consumed:
            continue
        m = _RELAY_ON_RE.match(fn)
        if m:
            base   = m.group(1)      # "B_R_UtelysUtelys"
            fn_off = base + "_OFF"
            name   = lbl[:-2].strip() if lbl.endswith("On") else lbl
            registry.relays.append(SensioRelay(
                unique_id=base,
                name=name,
                func_on=fn,
                func_off=fn_off,
            ))
            consumed.update({fn, fn_off})

    # ------------------------------------------------------------------
    # 3. Light groups  (B_Light*_ON / _OFF / _Sc*)
    #    Side-effect: build zone_display dict for later use.
    # ------------------------------------------------------------------
    # zone_display: internal_zone_key → human zone name
    # e.g. "KjkkenStue" → "Kjøkken/Stue"
    zone_display: dict[str, str] = {}

    for fn, lbl in functions:
        if fn in consumed:
            continue
        m = _LIGHT_ON_RE.match(fn)
        if m:
            base      = m.group(1)       # e.g. "B_LightUtelys"
            fn_off    = base + "_OFF"
            fn_toggle = base + "_ToggleOn"
            scenes    = [base + f"_Sc{i}" for i in range(1, 5)
                         if (base + f"_Sc{i}") in func_set]

            # "Utelys Light On" → "Utelys Light"
            name = lbl[:-3].strip() if lbl.endswith(" On") else lbl
            # zone display name: strip " Light" suffix
            zone_name = name[:-6].strip() if name.endswith(" Light") else name
            # internal zone key: strip "B_Light" prefix
            zone_key_raw = base[7:]   # e.g. "Utelys", "KjkkenStue"
            zone_display[zone_key_raw.lower()] = zone_name

            registry.lights.append(SensioLight(
                unique_id=base,
                name=name,
                func_on=fn,
                func_off=fn_off,
                func_toggle=fn_toggle if fn_toggle in func_set else None,
                scenes=scenes,
            ))
            to_consume = {fn, fn_off}
            if fn_toggle in func_set:
                to_consume.add(fn_toggle)
            to_consume.update(scenes)
            for suffix in ("_Save", "_SaveSc1", "_SaveSc2", "_SaveSc3", "_SaveSc4"):
                if (base + suffix) in func_set:
                    to_consume.add(base + suffix)
            consumed.update(to_consume)

    # ------------------------------------------------------------------
    # 4. Thermostats  (B_*{digits}_Temp_Dec anchor)
    # ------------------------------------------------------------------
    for fn, lbl in functions:
        if fn in consumed:
            continue
        m = _THERMO_DEC_RE.match(fn)
        if m:
            prefix   = m.group(1)    # e.g. "B_Vaskerom0533"
            fn_inc   = prefix + "_Temp_Inc"
            fn_set   = prefix + "_Set"
            scenes   = [prefix + f"_Sc{i}" for i in range(1, 4)
                        if (prefix + f"_Sc{i}") in func_set]

            # Internal zone key: strip "B_" + trailing digits
            # "B_Vaskerom0533" → zone_key "vaskerom"
            raw_key  = prefix[2:]           # "Vaskerom0533"
            zone_key = _strip_digits(raw_key).lower()   # "vaskerom"

            # Human name from zone_display, fallback to stripping the label
            name = zone_display.get(zone_key) or re.sub(r"\s*Temperature.*", "", lbl).strip()

            # Register in zone_display so mode selectors can use it too
            zone_display.setdefault(zone_key, name)

            unique = raw_key  # e.g. "Vaskerom0533"

            registry.thermostats.append(SensioThermostat(
                unique_id=unique,
                name=name,
                zone_key=zone_key,
                func_dec=fn,
                func_inc=fn_inc,
                func_set=fn_set if fn_set in func_set else None,
                preset_scenes=scenes,
            ))
            to_consume = {f for f in func_set if f.startswith(prefix)}
            consumed.update(to_consume)

    # ------------------------------------------------------------------
    # 5. Mode selectors  (B_*Mode_Away anchor)
    # ------------------------------------------------------------------
    MODE_SUFFIXES = {
        "home":     "_In",
        "away":     "_Away",
        "night":    "_Night",
        "vacation": "_Vacation",
    }
    for fn, lbl in functions:
        if fn in consumed:
            continue
        m = _MODE_AWAY_RE.match(fn)
        if m:
            base = m.group(1)   # e.g. "B_VaskeromMode" or "B_HouseMode"
            options: dict[str, str] = {}
            for mode_name, suffix in MODE_SUFFIXES.items():
                candidate = base + suffix
                if candidate in func_set:
                    options[mode_name] = candidate

            # Internal zone key: strip "B_" and trailing "Mode", lowercase
            raw      = base[2:]                       # "VaskeromMode"
            raw_zone = re.sub(r"Mode$", "", raw)      # "Vaskerom"
            zone_key = raw_zone.lower()               # "vaskerom"

            # Human name: look up zone display name, fall back to raw_zone
            zone_display_name = zone_display.get(zone_key, raw_zone)
            name = zone_display_name + " Mode"

            registry.mode_selectors.append(SensioModeSelector(
                unique_id=base,
                name=name,
                zone_key=zone_key,
                options=options,
            ))
            consumed.update(options.values())
            consumed.add(fn)

    # ------------------------------------------------------------------
    # 6. Everything else → scenes / buttons
    # ------------------------------------------------------------------
    for fn, lbl in functions:
        if fn not in consumed:
            registry.scenes.append(SensioScene(
                unique_id=fn,
                name=lbl,
                func=fn,
            ))

    return registry
