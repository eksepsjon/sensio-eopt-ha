"""
Sensio switch platform.

Exposes SensioRelay devices (B_R_*_ON / B_R_*_OFF) as HA switch entities.
State is optimistic.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from sensio.devices import SensioRelay

from .coordinator import SensioCoordinator
from .entity import SensioEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: SensioCoordinator = entry.runtime_data
    async_add_entities(
        SensioSwitchEntity(coordinator, relay)
        for relay in coordinator.device_registry.relays
    )


class SensioSwitchEntity(SensioEntity, SwitchEntity):
    """A Sensio relay output as an HA switch."""

    def __init__(self, coordinator: SensioCoordinator, device: SensioRelay) -> None:
        super().__init__(coordinator, device)
        self._attr_name = device.name

    @property
    def is_on(self) -> bool:
        return self.device.is_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.controller.trigger(self.device.func_on)
        self.device.is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.controller.trigger(self.device.func_off)
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

    async def _async_restore_state(self, last_state) -> None:
        self.device.is_on = last_state.state == "on"
