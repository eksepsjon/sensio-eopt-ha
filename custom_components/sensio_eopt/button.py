"""
Sensio Eopt button platform.

Exposes two kinds of pressable buttons:
  - SensioEoptScene objects (one-shot triggers: alarm resets, house-wide scenes, etc.)
  - SensioEoptModeSelector options — one button per mode (Home / Away / Night / Vacation)
    so that pressing always re-applies the mode even if it is already active.
"""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .lib.devices import SensioEoptModeSelector, SensioEoptScene

from .const import DOMAIN
from .coordinator import SensioEoptCoordinator
from .entity import SensioEoptEntity

_LOGGER = logging.getLogger(__name__)

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
    coordinator: SensioEoptCoordinator = entry.runtime_data

    entities: list[ButtonEntity] = [
        SensioEoptButtonEntity(coordinator, scene)
        for scene in coordinator.device_registry.scenes
    ]

    for ms in coordinator.device_registry.mode_selectors:
        for option_key, func in ms.options.items():
            entities.append(SensioEoptModeButtonEntity(coordinator, ms, option_key, func))

    async_add_entities(entities)


class SensioEoptButtonEntity(SensioEoptEntity, ButtonEntity):
    """A one-shot scene or action button."""

    _attr_icon = "mdi:gesture-tap-button"

    def __init__(self, coordinator: SensioEoptCoordinator, device: SensioEoptScene) -> None:
        super().__init__(coordinator, device)
        self._attr_name = device.name

    async def async_press(self) -> None:
        try:
            await self.coordinator.controller.trigger(self.device.func, self.device.value)
        except Exception as exc:
            _LOGGER.error("Failed to press button %s: %s", self._attr_name, exc)


class SensioEoptModeButtonEntity(SensioEoptEntity, ButtonEntity):
    """One pressable button per mode option — always re-applies the mode on press."""

    _attr_icon = "mdi:home-circle"

    def __init__(
        self,
        coordinator: SensioEoptCoordinator,
        device: SensioEoptModeSelector,
        option_key: str,
        func: str,
    ) -> None:
        super().__init__(coordinator, device)
        self._option_key = option_key
        self._func = func
        label = OPTION_LABELS.get(option_key, option_key.capitalize())
        self._attr_name = f"{device.name} {label}"
        self._attr_unique_id = f"{DOMAIN}_{device.unique_id}_{option_key}"

    async def async_press(self) -> None:
        try:
            await self.coordinator.controller.trigger(self._func)
        except Exception as exc:
            _LOGGER.error("Failed to press button %s: %s", self._attr_name, exc)
