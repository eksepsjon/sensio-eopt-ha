"""
Sensio Eopt / X-Comfort local LAN integration for Home Assistant.

Sets up a persistent TCP connection to the controller (port 10023) and
exposes all devices as HA entities.  No cloud connection required.

Setup: Configuration > Integrations > Add Integration > Sensio Eopt / X-Comfort
Credentials come from the supplier-provided smarthome.bash script.
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr

from .lib.controller import SensioEoptController
from .lib.devices import discover_devices

from .const import CONF_FUNCTIONS, CONF_TOKEN_ID, CONF_TOKEN_SECRET, DOMAIN, PLATFORMS
from .coordinator import SensioEoptCoordinator

_LOGGER = logging.getLogger(__name__)

# Type alias (ConfigEntry carrying our coordinator as runtime_data)
SensioEoptConfigEntry = ConfigEntry  # type: ignore[type-arg]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Sensio Eopt from a config entry."""
    host         = entry.data[CONF_HOST]
    token_id     = entry.data[CONF_TOKEN_ID]
    token_secret = entry.data[CONF_TOKEN_SECRET]

    controller = SensioEoptController(host, token_id, token_secret)

    # Attempt an initial connection to verify credentials before proceeding
    try:
        await controller.connect()
    except Exception as exc:
        raise ConfigEntryNotReady(
            f"Cannot connect to Sensio Eopt controller at {host}:10023 — {exc}"
        ) from exc

    functions = [tuple(pair) for pair in entry.data.get(CONF_FUNCTIONS, [])]
    device_registry = discover_devices(functions)

    coordinator = SensioEoptCoordinator(hass, controller, device_registry)
    entry.runtime_data = coordinator

    # Register the gateway as a hub device so sub-devices can reference it
    # via via_device without creating a dangling reference.
    dev_reg = dr.async_get(hass)
    dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, host)},
        name="Sensio Eopt Controller",
        manufacturer="Eaton / Sensio Eopt",
        model="X-Comfort Gateway",
        sw_version=(
            controller.controller_info.firmware
            if controller.controller_info
            else None
        ),
    )

    # Start the reconnect loop (initial connect already done above)
    await coordinator.async_start()

    await hass.config_entries.async_forward_entry_setups(
        entry, [Platform(p) for p in PLATFORMS]
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    coordinator: SensioEoptCoordinator = entry.runtime_data
    await coordinator.async_stop()
    return await hass.config_entries.async_unload_platforms(
        entry, [Platform(p) for p in PLATFORMS]
    )
