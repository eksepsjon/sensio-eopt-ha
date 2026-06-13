"""
Sensio Eopt switch platform.

Exposes SensioEoptRelay devices (B_R_*_ON / B_R_*_OFF) as HA switch entities.
State is optimistic.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .lib.devices import SensioEoptRelay

from .coordinator import SensioEoptCoordinator
from .entity import SensioEoptEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: SensioEoptCoordinator = entry.runtime_data
    async_add_entities(
        SensioEoptSwitchEntity(coordinator, relay)
        for relay in coordinator.device_registry.relays
    )


class SensioEoptSwitchEntity(SensioEoptEntity, SwitchEntity):
    """A Sensio Eopt relay output as an HA switch."""

    _attr_icon = "mdi:toggle-switch"

    def __init__(self, coordinator: SensioEoptCoordinator, device: SensioEoptRelay) -> None:
        super().__init__(coordinator, device)
        self._attr_name = device.name
        # B_R_UtelysUtelys → D_R_UtelysUtelys
        self._d_event_name = "D_" + device.unique_id[2:]

    @property
    def is_on(self) -> bool:
        return self.device.is_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        prev = self.device.is_on
        try:
            await self.coordinator.controller.trigger(self.device.func_on)
        except Exception as exc:
            _LOGGER.error("Failed to turn on %s: %s", self._attr_name, exc)
            self.device.is_on = prev
            self.async_write_ha_state()
            return
        self.device.is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        prev = self.device.is_on
        try:
            await self.coordinator.controller.trigger(self.device.func_off)
        except Exception as exc:
            _LOGGER.error("Failed to turn off %s: %s", self._attr_name, exc)
            self.device.is_on = prev
            self.async_write_ha_state()
            return
        self.device.is_on = False
        self.async_write_ha_state()

    def _handle_event(self, event) -> None:
        if event.is_trigger:
            if event.name == self.device.func_on:
                self.device.is_on = True
                self.async_write_ha_state()
            elif event.name == self.device.func_off:
                self.device.is_on = False
                self.async_write_ha_state()
        elif event.is_device_value:
            if event.name == self._d_event_name:
                self.device.is_on = max(event.state, event.int_value) > 0
                self.async_write_ha_state()

    async def _async_restore_state(self, last_state) -> None:
        self.device.is_on = last_state.state == "on"
