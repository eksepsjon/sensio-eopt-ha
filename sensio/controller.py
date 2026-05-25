"""
Async TCP client for Sensio/X-Comfort controllers.

Uses asyncio.StreamReader/StreamWriter — runs inside Home Assistant's event loop
or any other asyncio application.  The sync LocalClient in local.py remains
available for the CLI and simple scripts.

Typical usage in Home Assistant:

    controller = SensioController(host, token_id, token_secret)
    controller.add_listener(my_event_callback)
    asyncio.create_task(controller.connect_with_retry())
    ...
    await controller.trigger("B_LightUtelys_ON")
    ...
    await controller.disconnect()
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Optional

from .local import ControllerInfo, CONTROLLER_PORT, ENCODING, _smux_encode, _smux_parse

_LOGGER = logging.getLogger(__name__)

RECONNECT_DELAY = 5   # seconds between reconnect attempts
CONNECT_TIMEOUT = 10  # seconds for initial TCP connect
LOGIN_TIMEOUT   = 5   # seconds to receive <connect/> banner


class SensioController:
    """
    Persistent async connection to a Sensio/X-Comfort controller.

    Events (raw text lines from the server) are dispatched to all registered
    listeners.  State is optimistic: entities assume commands succeeded and
    update when matching events arrive.

    Thread-safety: call from within the asyncio event loop only.
    """

    def __init__(
        self,
        host: str,
        token_id: str,
        token_secret: str,
        port: int = CONTROLLER_PORT,
    ) -> None:
        self.host = host
        self.token_id = token_id
        self.token_secret = token_secret
        self.port = port

        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._read_task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()

        self._listeners: list[Callable[[str], None]] = []
        self._connection_listeners: list[Callable[[bool], None]] = []

        self.controller_info: Optional[ControllerInfo] = None
        self.connected: bool = False

    # ------------------------------------------------------------------
    # Subscription API
    # ------------------------------------------------------------------

    def add_listener(
        self, callback: Callable[[str], None]
    ) -> Callable[[], None]:
        """
        Register a callback for every incoming event line.
        Returns a zero-argument callable that unregisters the callback.
        """
        self._listeners.append(callback)
        def _remove() -> None:
            try:
                self._listeners.remove(callback)
            except ValueError:
                pass
        return _remove

    def add_connection_listener(
        self, callback: Callable[[bool], None]
    ) -> Callable[[], None]:
        """
        Register a callback that fires with True on connect, False on disconnect.
        Returns unsubscribe callable.
        """
        self._connection_listeners.append(callback)
        def _remove() -> None:
            try:
                self._connection_listeners.remove(callback)
            except ValueError:
                pass
        return _remove

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> ControllerInfo:
        """
        Open TCP connection and perform the LOGIN-TO handshake.
        Starts the background read loop.
        Returns ControllerInfo parsed from the server banner.
        Raises OSError / asyncio.TimeoutError on failure.
        """
        self._stop_event.clear()

        self._reader, self._writer = await asyncio.wait_for(
            asyncio.open_connection(self.host, self.port),
            timeout=CONNECT_TIMEOUT,
        )

        # Read the <connect .../> SMUX banner the controller sends immediately
        raw_banner = await asyncio.wait_for(
            self._reader.read(4096), timeout=LOGIN_TIMEOUT
        )
        banner_msgs, _ = _smux_parse(raw_banner)
        for msg in banner_msgs:
            if "<connect" in msg:
                self.controller_info = ControllerInfo(msg)
                break

        # Handshake: SMUX-framed LOGIN-TO
        await self._send(
            f"LOGIN-TO "
            f"<tokenId>{self.token_id}</tokenId>"
            f"<secret>{self.token_secret}</secret>"
            f"<dev>WEB</dev>"
            f"<feet>16</feet>"
        )

        self.connected = True
        _LOGGER.info("Sensio connected: %s", self.controller_info)
        self._notify_connection(True)

        # Start background reader
        self._read_task = asyncio.create_task(
            self._read_loop(), name="sensio_read_loop"
        )

        return self.controller_info or ControllerInfo("")

    async def disconnect(self) -> None:
        """Disconnect and stop the reconnect loop."""
        self._stop_event.set()
        await self._close_socket()

    async def connect_with_retry(self) -> None:
        """
        Connect and automatically reconnect after failures.
        Runs until disconnect() is called.  Meant to be run as an asyncio Task.
        """
        while not self._stop_event.is_set():
            try:
                await self.connect()
                assert self._read_task is not None
                await self._read_task   # blocks until connection drops
            except asyncio.CancelledError:
                return
            except Exception as exc:
                _LOGGER.warning(
                    "Sensio connection failed (%s: %s), retrying in %ds",
                    type(exc).__name__, exc, RECONNECT_DELAY,
                )

            if not self._stop_event.is_set():
                self.connected = False
                self._notify_connection(False)
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(), timeout=RECONNECT_DELAY
                    )
                except asyncio.TimeoutError:
                    pass   # time to retry

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    async def trigger(self, func_name: str, value: int = 0) -> None:
        """
        Send a new_state command.

        func_name: B_* name from the controller project config
        value:     0 for buttons/on-off; unused for dimmers — use dim() instead
        """
        if not self.connected:
            raise RuntimeError("Not connected to controller")
        await self._send(f"new_state {func_name} {value}")

    async def dim(self, set_action_name: str, percent: int) -> None:
        """
        Set a dimmer to a percentage level (0–100).

        set_action_name: the B_D_*_SET function name,
                         e.g. "B_D_Hall2etgHallTrappEntre_SET"
        percent: 0–100

        Sends:
          set_value M_D_{name}_Val {percent}
          new_state B_D_{name}_SET 0
        """
        if not self.connected:
            raise RuntimeError("Not connected to controller")
        if set_action_name.startswith("B_D_") and set_action_name.endswith("_SET"):
            val_register = "M_D_" + set_action_name[4:-4] + "_Val"
        else:
            raise ValueError(
                f"dim() expects a B_D_*_SET action name, got {set_action_name!r}"
            )
        percent = max(0, min(100, percent))
        await self._send(f"set_value {val_register} {percent}")
        await self._send(f"new_state {set_action_name} 0")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _send(self, line: str) -> None:
        if self._writer is None:
            raise RuntimeError("Not connected")
        self._writer.write(_smux_encode(line))
        await self._writer.drain()

    async def _close_socket(self) -> None:
        if self._read_task and not self._read_task.done():
            self._read_task.cancel()
            try:
                await self._read_task
            except (asyncio.CancelledError, Exception):
                pass
        self._read_task = None

        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
            self._writer = None
            self._reader = None

        if self.connected:
            self.connected = False
            self._notify_connection(False)

    async def _read_loop(self) -> None:
        """Read SMUX-framed messages and dispatch to listeners until connection closes."""
        assert self._reader is not None
        buf = b""
        try:
            while not self._stop_event.is_set():
                chunk = await self._reader.read(4096)
                if not chunk:
                    _LOGGER.debug("Sensio: server closed connection")
                    break
                buf += chunk
                msgs, buf = _smux_parse(buf)
                for line in msgs:
                    line = line.strip()
                    if not line:
                        continue
                    _LOGGER.debug("Sensio event: %r", line)
                    # Echo keepalive ACKs back to the controller (SMUX-framed)
                    if "x_bm_st ACK_DIR" in line or "PANEL_BRIGHTNESS" in line:
                        try:
                            await self._send(line)
                        except Exception:
                            pass
                    self._dispatch(line)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if not self._stop_event.is_set():
                _LOGGER.error("Sensio read loop error: %s", exc)
        finally:
            if not self._stop_event.is_set():
                self.connected = False
                self._notify_connection(False)

    def _dispatch(self, line: str) -> None:
        for cb in list(self._listeners):
            try:
                cb(line)
            except Exception:
                _LOGGER.exception("Error in Sensio event listener")

    def _notify_connection(self, state: bool) -> None:
        for cb in list(self._connection_listeners):
            try:
                cb(state)
            except Exception:
                _LOGGER.exception("Error in Sensio connection listener")
