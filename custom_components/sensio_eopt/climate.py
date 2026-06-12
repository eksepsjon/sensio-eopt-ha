"""
Sensio Eopt climate platform — floor heating thermostats.

Each SensioEoptThermostat becomes an HA climate entity with:
  - HVAC mode: "heat" only (floor heating is always on unless in away mode)
  - Preset modes: Home / Away / Night / Vacation  (via zone ModeSelector funcs)
  - set_temperature: uses the _Set function with value = int(°C × 10)
    Fallback: step up/down with _Temp_Inc / _Temp_Dec if _Set is unavailable.
  - Target temperature tracked optimistically; starts at 21 °C.

Temperature encoding assumption: X-Comfort encodes temperature as integer
tenths-of-a-degree (e.g. 215 = 21.5 °C).  If your thermostat responds oddly
to set_temperature, adjust TEMP_SCALE below.
"""

from __future__ import annotations

import logging
import math
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.components.climate.const import PRESET_AWAY, PRESET_HOME, PRESET_SLEEP
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PRECISION_HALVES, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .lib.devices import SensioEoptModeSelector, SensioEoptThermostat

from .coordinator import SensioEoptCoordinator
from .entity import SensioEoptEntity

_LOGGER = logging.getLogger(__name__)

# Controller encodes temperature as int(°C × TEMP_SCALE).
# Common X-Comfort value is 10 (tenths of a degree).
TEMP_SCALE = 10

PRESET_VACATION = "vacation"
PRESET_NIGHT    = "night"

# Mapping: HA preset name → ModeSelector option key
PRESET_TO_MODE = {
    PRESET_HOME:     "home",
    PRESET_AWAY:     "away",
    PRESET_SLEEP:    "night",
    PRESET_VACATION: "vacation",
}
MODE_TO_PRESET = {v: k for k, v in PRESET_TO_MODE.items()}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: SensioEoptCoordinator = entry.runtime_data
    reg = coordinator.device_registry

    # Build a mapping from zone_key → mode selector.
    # Both SensioEoptThermostat and SensioEoptModeSelector carry the same zone_key
    # derived from the internal function name prefix (e.g. "vaskerom").
    mode_by_zone: dict[str, SensioEoptModeSelector] = {
        ms.zone_key: ms for ms in reg.mode_selectors
    }

    entities = []
    for thermo in reg.thermostats:
        mode_sel = mode_by_zone.get(thermo.zone_key)
        entities.append(SensioEoptClimateEntity(coordinator, thermo, mode_sel))

    async_add_entities(entities)


class SensioEoptClimateEntity(SensioEoptEntity, ClimateEntity):
    """Floor heating thermostat zone."""

    _attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]
    _attr_hvac_mode  = HVACMode.HEAT
    _attr_icon = "mdi:radiator"
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_precision = PRECISION_HALVES
    _attr_target_temperature_step = 0.5
    _attr_min_temp = 5.0
    _attr_max_temp = 40.0

    def __init__(
        self,
        coordinator: SensioEoptCoordinator,
        device: SensioEoptThermostat,
        mode_selector: SensioEoptModeSelector | None,
    ) -> None:
        super().__init__(coordinator, device)
        self._attr_name = device.name
        self._mode_selector = mode_selector

        features = ClimateEntityFeature.TARGET_TEMPERATURE

        if mode_selector and mode_selector.options:
            features |= ClimateEntityFeature.PRESET_MODE
            self._attr_preset_modes = [
                MODE_TO_PRESET[key]
                for key in mode_selector.options
                if key in MODE_TO_PRESET
            ]
        else:
            self._attr_preset_modes = []

        self._attr_supported_features = features
        self._attr_target_temperature = device.target_temperature
        self._attr_preset_mode = PRESET_HOME

    @property
    def target_temperature(self) -> float:
        return self.device.target_temperature

    @property
    def preset_mode(self) -> str | None:
        if self._mode_selector:
            return MODE_TO_PRESET.get(self._mode_selector.current_option, PRESET_HOME)
        return None

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Switch heat/off by toggling the away mode."""
        if not self._mode_selector:
            return
        if hvac_mode == HVACMode.OFF:
            try:
                await self._set_zone_mode("away")
            except Exception as exc:
                _LOGGER.error("Failed to set HVAC mode for %s: %s", self._attr_name, exc)
                self.async_write_ha_state()
                return
            self._attr_hvac_mode = HVACMode.OFF
        else:
            try:
                await self._set_zone_mode("home")
            except Exception as exc:
                _LOGGER.error("Failed to set HVAC mode for %s: %s", self._attr_name, exc)
                self.async_write_ha_state()
                return
            self._attr_hvac_mode = HVACMode.HEAT
        self.async_write_ha_state()

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        mode_key = PRESET_TO_MODE.get(preset_mode, "home")
        try:
            await self._set_zone_mode(mode_key)
        except Exception as exc:
            _LOGGER.error("Failed to set preset mode for %s: %s", self._attr_name, exc)
            self.async_write_ha_state()
            return
        self.async_write_ha_state()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temp = kwargs.get("temperature")
        if temp is None:
            return

        try:
            if self.device.func_set:
                # Direct set — encode as integer tenths-of-a-degree
                raw = int(round(temp * TEMP_SCALE))
                await self.coordinator.controller.trigger(self.device.func_set, raw)
            else:
                # Fallback: step up or down from current target
                current = self.device.target_temperature
                delta = temp - current
                steps = abs(int(round(delta / 0.5)))
                func = self.device.func_inc if delta > 0 else self.device.func_dec
                for _ in range(steps):
                    await self.coordinator.controller.trigger(func)
        except Exception as exc:
            _LOGGER.error("Failed to set temperature for %s: %s", self._attr_name, exc)
            self.async_write_ha_state()
            return

        self.device.target_temperature = temp
        self._attr_target_temperature = temp
        self.async_write_ha_state()

    # ------------------------------------------------------------------
    # Event handling
    # ------------------------------------------------------------------

    def _handle_event(self, event) -> None:
        # Type 23: M_* float register — temperature setpoint (value = °C × TEMP_SCALE)
        if event.is_register:
            # B_Vaskerom0533_Temp_Dec → prefix_no_b = "Vaskerom0533"
            prefix_no_b = self.device.func_dec.split("_Temp_Dec")[0][2:]
            if event.name.startswith("M_" + prefix_no_b):
                temp = event.float_value / TEMP_SCALE
                if self._attr_min_temp <= temp <= self._attr_max_temp:
                    self.device.target_temperature = temp
                    self._attr_target_temperature = temp
                    self.async_write_ha_state()
        elif event.is_trigger:
            # Increment/decrement buttons — adjust optimistic setpoint
            if event.name == self.device.func_inc:
                new_temp = min(self.device.target_temperature + 0.5, self._attr_max_temp)
                self.device.target_temperature = new_temp
                self._attr_target_temperature = new_temp
                self.async_write_ha_state()
            elif event.name == self.device.func_dec:
                new_temp = max(self.device.target_temperature - 0.5, self._attr_min_temp)
                self.device.target_temperature = new_temp
                self._attr_target_temperature = new_temp
                self.async_write_ha_state()
            elif self._mode_selector:
                # Zone mode changed externally (physical button / other HA instance)
                for mode_key, func in self._mode_selector.options.items():
                    if event.name == func:
                        self._mode_selector.current_option = mode_key
                        self._attr_hvac_mode = HVACMode.OFF if mode_key == "away" else HVACMode.HEAT
                        self.async_write_ha_state()
                        break

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _set_zone_mode(self, mode_key: str) -> None:
        if not self._mode_selector:
            return
        func = self._mode_selector.options.get(mode_key)
        if func:
            await self.coordinator.controller.trigger(func)
            self._mode_selector.current_option = mode_key

    # ------------------------------------------------------------------
    # Restore
    # ------------------------------------------------------------------

    async def _async_restore_state(self, last_state) -> None:
        if last_state.state == HVACMode.OFF:
            self._attr_hvac_mode = HVACMode.OFF
        else:
            self._attr_hvac_mode = HVACMode.HEAT

        attrs = last_state.attributes
        if (t := attrs.get("temperature")) is not None:
            self.device.target_temperature = float(t)
            self._attr_target_temperature = float(t)
        if (p := attrs.get("preset_mode")) is not None:
            mode_key = PRESET_TO_MODE.get(p, "home")
            if self._mode_selector:
                self._mode_selector.current_option = mode_key
