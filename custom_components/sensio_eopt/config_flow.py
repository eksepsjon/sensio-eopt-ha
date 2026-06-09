"""Config flow for Sensio Eopt / X-Comfort integration."""

from __future__ import annotations

import asyncio
import base64
import logging
import re
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST

from .lib.controller import SensioEoptController

from .const import CONF_FUNCTIONS, CONF_TOKEN_ID, CONF_TOKEN_SECRET, DOMAIN

_LOGGER = logging.getLogger(__name__)

CONF_SCRIPT = "script"


def _parse_smarthome_bash(
    text: str,
) -> tuple[str, str, str, list[list[str]]]:
    """Extract (token_id, token_secret, mac, functions) from a smarthome.bash script.

    functions is a list of [internal_name, display_name] pairs (JSON-serialisable).
    Raises ValueError with an error key on failure.
    """
    m = re.search(r"<<__BASE64__\s*([\s\S]+?)__BASE64__", text)
    if not m:
        raise ValueError("no_base64_block")

    try:
        decoded = base64.b64decode("".join(m.group(1).split())).decode("utf-8")
    except Exception:
        raise ValueError("invalid_base64")

    def _field(name: str) -> str:
        fm = re.search(rf'^{name}="([^"]+)"', decoded, re.MULTILINE)
        if not fm:
            raise ValueError(f"missing_field_{name}")
        return fm.group(1)

    def _array(name: str) -> list[str]:
        am = re.search(rf'^{name}=\(\s*([\s\S]*?)\s*\)', decoded, re.MULTILINE)
        if not am:
            raise ValueError(f"missing_array_{name}")
        return re.findall(r'"([^"]*)"', am.group(1))

    func_names = _array("func_names")
    nice_names = _array("nice_names")
    if len(func_names) != len(nice_names):
        raise ValueError("functions_length_mismatch")

    functions = [[fn, nn] for fn, nn in zip(func_names, nice_names)]
    return _field("token"), _field("secret"), _field("mac"), functions


class SensioEoptConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial setup UI for Sensio Eopt."""

    VERSION = 1

    def __init__(self) -> None:
        self._token_id: str = ""
        self._token_secret: str = ""
        self._mac: str = ""
        self._functions: list[list[str]] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                token_id, token_secret, mac, functions = _parse_smarthome_bash(
                    user_input[CONF_SCRIPT]
                )
            except ValueError as exc:
                errors["base"] = str(exc)
            else:
                self._token_id = token_id
                self._token_secret = token_secret
                self._mac = mac
                self._functions = functions
                return await self.async_step_ip()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_SCRIPT): str}),
            errors=errors,
        )

    async def async_step_ip(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST].strip()

            try:
                controller = SensioEoptController(host, self._token_id, self._token_secret)
                info = await controller.connect()
                await controller.disconnect()
            except asyncio.TimeoutError:
                errors["base"] = "timeout"
            except OSError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error during Sensio Eopt setup")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(
                    info.mac or host, raise_on_progress=False
                )
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=f"Sensio Eopt ({host})",
                    data={
                        CONF_HOST:         host,
                        CONF_TOKEN_ID:     self._token_id,
                        CONF_TOKEN_SECRET: self._token_secret,
                        CONF_FUNCTIONS:    self._functions,
                    },
                )

        return self.async_show_form(
            step_id="ip",
            data_schema=vol.Schema(
                {vol.Required(CONF_HOST): str}
            ),
            errors=errors,
            description_placeholders={"mac": self._mac},
        )
