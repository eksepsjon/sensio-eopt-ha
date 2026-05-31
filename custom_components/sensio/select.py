"""
Sensio select platform — zone and house-wide mode selectors.

Each SensioModeSelector (Home / Away / Night / Vacation per zone) is exposed
as an HA select entity so it can be used in automations independently of the
thermostat preset.

Example: "Kjøkken/Stue Mode" select with options
    Home | Away | Night | Vacation
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .lib.devices import SensioModeSelector

from .coordinator import SensioCoordinator
from .entity import SensioEntity

# Map internal option keys → display strings shown in HA UI
OPTION_LABELS = {
    "home":     "Home",
    "away":     "Away",
    "night":    "Night",
    "vacation": "Vacation",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: SensioCoordinator = entry.runtime_data
    async_add_entities(
        SensioSelectEntity(coordinator, ms)
        for ms in coordinator.device_registry.mode_selectors
    )


class SensioSelectEntity(SensioEntity, SelectEntity):
    """Zone or house-wide mode selector."""

    def __init__(
        self, coordinator: SensioCoordinator, device: SensioModeSelector
    ) -> None:
        super().__init__(coordinator, device)
        self._attr_name = device.name
        self._attr_options = [
            OPTION_LABELS[k] for k in device.options if k in OPTION_LABELS
        ]

    @property
    def current_option(self) -> str | None:
        return OPTION_LABELS.get(self.device.current_option)

    async def async_select_option(self, option: str) -> None:
        # Reverse-map display label → key
        key = next((k for k, v in OPTION_LABELS.items() if v == option), None)
        if key is None:
            return
        func = self.device.options.get(key)
        if func:
            await self.coordinator.controller.trigger(func)
            self.device.current_option = key
            self.async_write_ha_state()

    def _handle_event(self, event) -> None:
        if event.is_trigger:
            for key, fn in self.device.options.items():
                if fn == event.name:
                    self.device.current_option = key
                    self.async_write_ha_state()
                    break

    async def _async_restore_state(self, last_state) -> None:
        label = last_state.state
        key = next((k for k, v in OPTION_LABELS.items() if v == label), None)
        if key:
            self.device.current_option = key
