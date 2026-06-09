"""Base entity class shared by all Sensio Eopt platforms."""

from __future__ import annotations

from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN, SIGNAL_CONNECTED, SIGNAL_EVENT
from .coordinator import SensioEoptCoordinator


class SensioEoptEntity(RestoreEntity):
    """
    Base class for all Sensio Eopt entities.

    - Uses RestoreEntity so optimistic state survives HA restarts.
    - Subscribes to SIGNAL_EVENT for push state updates.
    - Subscribes to SIGNAL_CONNECTED to mark availability.
    - Never polls (_attr_should_poll = False).
    """

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(self, coordinator: SensioEoptCoordinator, device) -> None:
        self.coordinator = coordinator
        self.device = device
        self._attr_unique_id = f"{DOMAIN}_{device.unique_id}"
        # The device_info groups all entities under one "device" card in HA
        self._attr_device_info = {
            "identifiers": {
                (DOMAIN, coordinator.controller.host)
            },
            "name": "Sensio Eopt Controller",
            "manufacturer": "Eaton / Sensio Eopt",
            "model": "X-Comfort Gateway",
            "sw_version": (
                coordinator.controller.controller_info.firmware
                if coordinator.controller.controller_info
                else None
            ),
        }

    # ------------------------------------------------------------------
    # HA lifecycle
    # ------------------------------------------------------------------

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        # Subscribe to push events
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_EVENT, self._handle_event
            )
        )
        # Subscribe to connection changes
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_CONNECTED, self._handle_connected
            )
        )
        # Restore last known state from HA storage (survives restarts)
        if last := await self.async_get_last_state():
            await self._async_restore_state(last)

        # Replay any events already in the coordinator cache so entities
        # get current state immediately, even if the initial RSN burst from
        # the controller arrived before this entity subscribed.
        for evt in self.coordinator.state_cache.values():
            self._handle_event(evt)

    @property
    def available(self) -> bool:
        return self.coordinator.controller.connected

    # ------------------------------------------------------------------
    # Overridable hooks
    # ------------------------------------------------------------------

    def _handle_event(self, event) -> None:
        """Called for every parsed SensioEoptEvent from the controller. Override in subclasses."""

    def _handle_connected(self, connected: bool) -> None:
        """Called when connection state changes."""
        self.async_write_ha_state()

    async def _async_restore_state(self, last_state) -> None:
        """Restore last known state after HA restart. Override in subclasses."""
