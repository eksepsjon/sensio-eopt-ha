"""Config flow for Sensio / X-Comfort integration."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST

from sensio.controller import SensioController

from .const import CONF_TOKEN_ID, CONF_TOKEN_SECRET, DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST, description={"suggested_value": "192.168.1.x"}): str,
        vol.Required(CONF_TOKEN_ID):     str,
        vol.Required(CONF_TOKEN_SECRET): str,
    }
)


class SensioConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial setup UI for Sensio."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            host         = user_input[CONF_HOST].strip()
            token_id     = user_input[CONF_TOKEN_ID].strip()
            token_secret = user_input[CONF_TOKEN_SECRET].strip()

            # Validate by actually connecting
            try:
                controller = SensioController(host, token_id, token_secret)
                info = await controller.connect()
                await controller.disconnect()
            except asyncio.TimeoutError:
                errors["base"] = "timeout"
            except OSError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error during Sensio setup")
                errors["base"] = "unknown"
            else:
                # Prevent duplicate entries for the same controller
                await self.async_set_unique_id(
                    info.mac or host, raise_on_progress=False
                )
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=f"Sensio ({host})",
                    data={
                        CONF_HOST:         host,
                        CONF_TOKEN_ID:     token_id,
                        CONF_TOKEN_SECRET: token_secret,
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_SCHEMA,
            errors=errors,
            description_placeholders={
                "port": "10023",
                "script": "smarthome.bash",
            },
        )
