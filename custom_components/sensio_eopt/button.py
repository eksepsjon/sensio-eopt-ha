"""
Sensio Eopt button platform.

Exposes SensioEoptScene objects as HA button entities — one-shot triggers that
don't have meaningful state (alarm resets, house-wide scenes, temperature
presets, etc.).

Pressing the button fires the corresponding B_* function with value 0.
"""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .lib.devices import SensioEoptScene

from .coordinator import SensioEoptCoordinator
from .entity import SensioEoptEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: SensioEoptCoordinator = entry.runtime_data
    async_add_entities(
        SensioEoptButtonEntity(coordinator, scene)
        for scene in coordinator.device_registry.scenes
    )


class SensioEoptButtonEntity(SensioEoptEntity, ButtonEntity):
    """A one-shot scene or action button."""

    def __init__(self, coordinator: SensioEoptCoordinator, device: SensioEoptScene) -> None:
        super().__init__(coordinator, device)
        self._attr_name = device.name

    async def async_press(self) -> None:
        await self.coordinator.controller.trigger(self.device.func, self.device.value)
