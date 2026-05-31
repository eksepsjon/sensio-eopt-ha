"""
Sensio coordinator — owns the controller connection and dispatches events.

Rather than using DataUpdateCoordinator (which is poll-oriented) we use a
simple class that holds the persistent async connection and fans out incoming
event lines via HA's dispatcher.  Entities subscribe once in
async_added_to_hass() and receive callbacks whenever state changes.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .lib.controller import SensioController
from .lib.devices import DeviceRegistry
from .lib.events import SensioEvent, parse_event

from .const import SIGNAL_CONNECTED, SIGNAL_EVENT

_LOGGER = logging.getLogger(__name__)


class SensioCoordinator:
    """
    Manages the TCP connection to one Sensio controller.

    Lifecycle (managed by __init__.py):
        await coordinator.async_start()   # begin connect-with-retry loop
        await coordinator.async_stop()    # clean shutdown
    """

    def __init__(
        self,
        hass: HomeAssistant,
        controller: SensioController,
        device_registry: DeviceRegistry,
    ) -> None:
        self.hass = hass
        self.controller = controller
        self.device_registry = device_registry
        self._retry_task: asyncio.Task | None = None

        # Cache of latest event per object name — keyed by event.name
        # Populated as RSN/SSN events arrive; lets entities get current state
        # immediately when they subscribe rather than waiting for the next event.
        self.state_cache: dict[str, SensioEvent] = {}

        # Wire up controller callbacks → HA dispatcher
        controller.add_listener(self._on_event)
        controller.add_connection_listener(self._on_connection_change)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def async_start(self) -> None:
        """Start the persistent connect-with-retry loop."""
        self._retry_task = self.hass.async_create_task(
            self.controller.connect_with_retry(),
            name="sensio_connect",
        )

    async def async_stop(self) -> None:
        """Disconnect and cancel the retry loop."""
        await self.controller.disconnect()
        if self._retry_task and not self._retry_task.done():
            self._retry_task.cancel()
            try:
                await self._retry_task
            except (asyncio.CancelledError, Exception):
                pass

    # ------------------------------------------------------------------
    # Internal callbacks
    # ------------------------------------------------------------------

    def get_cached_state(self, name: str) -> Optional[SensioEvent]:
        """Return the latest known event for a given object name, or None."""
        return self.state_cache.get(name)

    @callback
    def _on_event(self, line: str) -> None:
        """Parse and dispatch an event line to all listening entities."""
        evt = parse_event(line)
        if evt is not None:
            # Update cache so late-subscribing entities can get current state
            self.state_cache[evt.name] = evt
            # Dispatch the parsed event (entities use evt.name to filter)
            async_dispatcher_send(self.hass, SIGNAL_EVENT, evt)
        # Also dispatch raw for debugging / future use
        # async_dispatcher_send(self.hass, SIGNAL_EVENT_RAW, line)

    @callback
    def _on_connection_change(self, connected: bool) -> None:
        """Dispatch connection state change."""
        _LOGGER.info("Sensio controller %s", "connected" if connected else "disconnected")
        async_dispatcher_send(self.hass, SIGNAL_CONNECTED, connected)
