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
        if effect and effect.startswith("Scene "):
            idx = int(effect.split()[-1]) - 1
            if 0 <= idx < len(self.device.scenes):
                await self.coordinator.controller.trigger(self.device.scenes[idx])
                self._attr_effect = effect
                self.device.is_on = True
                self.async_write_ha_state()
                return

        await self.coordinator.controller.trigger(self.device.func_on)
        self.device.is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.controller.trigger(self.device.func_off)
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

    def __init__(self, coordinator: SensioEoptCoordinator, device: SensioEoptDimmer) -> None:
        super().__init__(coordinator, device)
        self._attr_name = device.name

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
        await self.coordinator.controller.dim(self.device.func_set, percent)
        self.device.brightness_pct = percent
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.controller.dim(self.device.func_set, 0)
        self.device.brightness_pct = 0
        self.async_write_ha_state()

    def _handle_event(self, event) -> None:
        # Type 21: D_* device value — real current brightness from the controller (0-100)
        if event.is_device_value and event.name.startswith("D_"):
            # D_Hall2etgHallTrappEntre matches B_D_Hall2etgHallTrappEntre_SET
            expected_d = "D_" + self.device.func_set[4:-4]  # strip B_D_ and _SET
            if event.name == expected_d:
                self.device.brightness_pct = max(0, min(100, event.int_value))
                self.async_write_ha_state()
        # Type 23: M_D_*_Val float register — same info as D_* but as a float
        elif event.is_register:
            # B_D_Hall2etgHallTrappEntre_SET → M_D_Hall2etgHallTrappEntre_Val
            expected_m = "M_" + self.device.func_set[2:-4] + "_Val"  # strip B_ and _SET
            if event.name == expected_m:
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
