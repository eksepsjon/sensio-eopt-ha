"""
Sensio Eopt light platform.

Two entity types:
  SensioEoptLightEntity  — zone light group (on/off + up to 4 lighting scenes)
  SensioEoptDimmerEntity — single dimmable channel (brightness 0-255)

State is optimistic: assumed correct after each command, then refined when
the controller echoes back an RPC event for the triggered function.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .lib.devices import SensioEoptDimmer, SensioEoptLight

from .coordinator import SensioEoptCoordinator
from .entity import SensioEoptEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: SensioEoptCoordinator = entry.runtime_data
    reg = coordinator.device_registry

    entities: list[LightEntity] = []
    for light in reg.lights:
        entities.append(SensioEoptLightEntity(coordinator, light))
    for dimmer in reg.dimmers:
        entities.append(SensioEoptDimmerEntity(coordinator, dimmer))

    async_add_entities(entities)


# ---------------------------------------------------------------------------
# Light group (on/off)
# ---------------------------------------------------------------------------

class SensioEoptLightEntity(SensioEoptEntity, LightEntity):
    """Zone light group with on/off control and optional scenes."""

    _attr_color_mode = ColorMode.ONOFF
    _attr_supported_color_modes = {ColorMode.ONOFF}
    _attr_icon = "mdi:lightbulb-group"

    def __init__(self, coordinator: SensioEoptCoordinator, device: SensioEoptLight) -> None:
        super().__init__(coordinator, device)
        self._attr_name = device.name
        self._attr_is_on = device.is_on

        # Expose lighting scenes as HA effect list
        if device.scenes:
            self._attr_supported_features = LightEntityFeature.EFFECT
            self._attr_effect_list = [f"Scene {i+1}" for i in range(len(device.scenes))]
        self._attr_effect = None

    @property
    def is_on(self) -> bool:
        return self.device.is_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        effect = kwargs.get("effect")
        prev_is_on = self.device.is_on
        prev_effect = self._attr_effect
        if effect and effect.startswith("Scene "):
            try:
                idx = int(effect.split()[-1]) - 1
            except (ValueError, IndexError):
                _LOGGER.warning("Ignoring unrecognised light effect %r", effect)
                idx = -1
            if 0 <= idx < len(self.device.scenes):
                try:
                    await self.coordinator.controller.trigger(self.device.scenes[idx])
                except Exception as exc:
                    _LOGGER.error("Failed to trigger scene for %s: %s", self._attr_name, exc)
                    self.device.is_on = prev_is_on
                    self._attr_effect = prev_effect
                    self.async_write_ha_state()
                    return
                self._attr_effect = effect
                self.device.is_on = True
                self.async_write_ha_state()
                return

        try:
            await self.coordinator.controller.trigger(self.device.func_on)
        except Exception as exc:
            _LOGGER.error("Failed to turn on %s: %s", self._attr_name, exc)
            self.device.is_on = prev_is_on
            self._attr_effect = prev_effect
            self.async_write_ha_state()
            return
        self.device.is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        prev_is_on = self.device.is_on
        prev_effect = self._attr_effect
        try:
            await self.coordinator.controller.trigger(self.device.func_off)
        except Exception as exc:
            _LOGGER.error("Failed to turn off %s: %s", self._attr_name, exc)
            self.device.is_on = prev_is_on
            self._attr_effect = prev_effect
            self.async_write_ha_state()
            return
        self.device.is_on = False
        self._attr_effect = None
        self.async_write_ha_state()

    # ------------------------------------------------------------------
    # Event handling (refine optimistic state from controller events)
    # ------------------------------------------------------------------

    def _handle_event(self, event) -> None:
        # Type 6: a B_* function was triggered
        if event.is_trigger:
            if event.name == self.device.func_on:
                self.device.is_on = True
                self.async_write_ha_state()
            elif event.name == self.device.func_off:
                self.device.is_on = False
                self.async_write_ha_state()
            elif event.name in self.device.scenes:
                self.device.is_on = True
                idx = self.device.scenes.index(event.name)
                self._attr_effect = f"Scene {idx+1}"
                self.async_write_ha_state()

    async def _async_restore_state(self, last_state) -> None:
        self.device.is_on = last_state.state == "on"


# ---------------------------------------------------------------------------
# Dimmer channel (brightness 0-255)
# ---------------------------------------------------------------------------

class SensioEoptDimmerEntity(SensioEoptEntity, LightEntity):
    """Single dimmable channel.

    The controller uses 0-100 (percent) internally.
    HA uses 0-255 for brightness. Conversion happens here.
    """

    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}
    _attr_icon = "mdi:lightbulb"

    def __init__(self, coordinator: SensioEoptCoordinator, device: SensioEoptDimmer) -> None:
        super().__init__(coordinator, device)
        self._attr_name = device.name

        # Derive base device name for event matching.
        # Function names may be truncated in the bash script (~30-char limit),
        # e.g. "B_D_Trapp2etgHallTrappEntre_S" instead of full "_SET".
        # Strip B_D_ prefix and any partial _SET suffix, then use prefix matching.
        base = device.func_set[4:] if device.func_set.startswith("B_D_") else device.func_set
        for suffix in ("_SET", "_SE", "_S"):
            if base.endswith(suffix):
                base = base[:-len(suffix)]
                break
        base = base.rstrip("_")
        self._d_prefix = "D_" + base
        self._m_prefix = "M_D_" + base

    @property
    def is_on(self) -> bool:
        return self.device.brightness_pct > 0

    @property
    def brightness(self) -> int:
        """Return brightness in HA scale (0-255)."""
        return round(self.device.brightness_pct * 255 / 100)

    async def async_turn_on(self, **kwargs: Any) -> None:
        # HA passes brightness in 0-255; convert to controller percent (0-100)
        ha_level = kwargs.get(ATTR_BRIGHTNESS, 255)
        percent = round(int(ha_level) * 100 / 255)
        percent = max(1, min(100, percent))  # turn_on should never go to 0
        prev_pct = self.device.brightness_pct
        try:
            await self.coordinator.controller.dim(self.device.func_set, percent)
        except Exception as exc:
            _LOGGER.error("Failed to set brightness for %s: %s", self._attr_name, exc)
            self.device.brightness_pct = prev_pct
            self.async_write_ha_state()
            return
        self.device.brightness_pct = percent
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        prev_pct = self.device.brightness_pct
        try:
            await self.coordinator.controller.dim(self.device.func_set, 0)
        except Exception as exc:
            _LOGGER.error("Failed to turn off %s: %s", self._attr_name, exc)
            self.device.brightness_pct = prev_pct
            self.async_write_ha_state()
            return
        self.device.brightness_pct = 0
        self.async_write_ha_state()

    def _handle_event(self, event) -> None:
        # Type 21: D_* device value — real current brightness from the controller (0-100)
        # SSN events carry the value in the state field (value_raw is 0);
        # RSN events carry it in both fields.  Prefix match handles truncated
        # function names from the bash script.
        if event.is_device_value and event.name.startswith(self._d_prefix):
            pct = max(event.state, event.int_value)
            self.device.brightness_pct = max(0, min(100, pct))
            self.async_write_ha_state()
        # Type 23: M_D_*_Val float register — same info as D_* but as a float
        elif event.is_register and event.name.startswith(self._m_prefix) and event.name.endswith("_Val"):
            pct = max(0, min(100, int(round(event.float_value))))
            self.device.brightness_pct = pct
            self.async_write_ha_state()
        # Type 6: function trigger confirmation — just refresh state
        elif event.is_trigger and event.name == self.device.func_set:
            self.async_write_ha_state()

    async def _async_restore_state(self, last_state) -> None:
        if last_state.state == "on":
            brightness_attr = last_state.attributes.get("brightness")
            # Restore in percent (HA stores 0-255, convert back)
            ha_brightness = int(brightness_attr) if brightness_attr else 255
            self.device.brightness_pct = round(ha_brightness * 100 / 255)
        else:
            self.device.brightness_pct = 0
