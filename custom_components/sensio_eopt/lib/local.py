"""
Local LAN TCP client for Sensio Eopt / X-Comfort controllers.

Protocol details reverse-engineered from Sensio Eopt.ControllerClient.Lite.dll.

Connection:
  - Host: controller local IP (e.g. 192.168.68.119)
  - Port: 10023 (TCP, no TLS)
  - Encoding: Windows-1252 (cp1252)

SMUX message framing (used for ALL messages in both directions):
  \x01{text}\x02    — regular message (type 1 = MessageBegin)
  \x07{header}\x01{text}\x02  — message with header (header contains "oid {guid}")
  \x05{text}\x02    — error message
  \x02 alone        — MessageEnd byte

Handshake (after receiving <connect> banner):
  <- \x01<connect sn="..." ip="..." mac="..." .../>\x02
  -> \x01LOGIN-TO <tokenId>GUID</tokenId><secret>SECRET</secret><dev>WEB</dev><feet>16</feet>\x02
  <- (controller starts sending SMUX events)

Outgoing commands:
  -> \x01new_state {function_name} 0\x02     -- trigger a named function
  -> \x01new_state {function_name} {n}\x02   -- trigger with value (dimmers 0-255)

Incoming events (SMUX-framed text):
  RSN {shortId} {name} {typeId} {enabled} {state} {value}
  SSN {shortId} {name} {typeId} {enabled} {state} {value}
  x_bm_st ACK_DIR seq={N}    -- keepalive (echo back as-is)
  PANEL_BRIGHTNESS {N}       -- panel keepalive (echo back as-is)
  end {function_name}        -- command execution confirmation
"""

from __future__ import annotations

import re
import select
import socket
import threading
import time
from collections.abc import Callable
from typing import Optional


CONTROLLER_PORT = 10023
ENCODING = "cp1252"
RECV_BUF = 4096

# SMUX framing bytes
_MSG_BEGIN = b'\x01'
_MSG_END   = b'\x02'
_HDR_BEGIN = b'\x07'
_ERR_BEGIN = b'\x05'
_START_BYTES = frozenset([0x01, 0x05, 0x06, 0x07])
_RSN_ID_RE = re.compile(r"^(?:RSN|SSN)\s+(\d+)\s+(\S+)")


def _smux_encode(message: str) -> bytes:
    """Wrap a message in SMUX framing: \\x01{message}\\x02"""
    return b'\x01' + message.encode(ENCODING) + b'\x02'


def _smux_parse(buf: bytes) -> tuple[list[str], bytes]:
    """
    Extract complete SMUX messages from a byte buffer.
    Returns (list_of_messages, remaining_buffer).
    Messages with headers (\\x07...\\x01...\\x02) have the header stripped.
    """
    messages: list[str] = []
    i = 0
    while i < len(buf):
        # Find the next start byte
        while i < len(buf) and buf[i] not in _START_BYTES:
            i += 1
        if i >= len(buf):
            break

        start_type = buf[i]
        i += 1

        if start_type == 0x07:
            # Header block: \x07{header}\x01{body}\x02
            # Find the \x01 that follows the header
            header_end = -1
            for j in range(i, len(buf)):
                if buf[j] in _START_BYTES:
                    header_end = j
                    break
            if header_end == -1:
                # Incomplete header
                i -= 1
                break
            # Skip header, process body
            start_type = buf[header_end]
            i = header_end + 1

        # Read until \x02 (MessageEnd)
        end = buf.find(b'\x02', i)
        if end == -1:
            # Incomplete message -- back up to start
            i -= 1
            break

        body = buf[i:end].decode(ENCODING, errors="replace")
        messages.append(body)
        i = end + 1

    return messages, buf[i:]


class ControllerInfo:
    """Parsed from the <connect .../> banner the controller sends on connect."""
    def __init__(self, line: str) -> None:
        self.raw = line
        self.sn = _attr(line, "sn")
        self.ip = _attr(line, "ip")
        self.mac = _attr(line, "mac")
        self.project_id = _attr(line, "pid")
        self.firmware = _attr(line, "fw")

    def __str__(self) -> str:
        return (
            f"Controller sn={self.sn} ip={self.ip} "
            f"fw={self.firmware!r} project={self.project_id}"
        )


def _attr(s: str, name: str) -> str:
    m = re.search(rf'{name}="([^"]*)"', s)
    return m.group(1) if m else ""


class LocalClient:
    """
    Connects to a Sensio Eopt controller on the local network using SMUX framing.

    Usage (blocking / scripted):
        client = LocalClient("192.168.68.119", token_id, token_secret)
        client.connect()
        info = client.controller_info   # ControllerInfo after connect
        client.trigger("B_LightUtelys_ON")
        client.disconnect()

    Usage (context manager):
        with LocalClient(...) as c:
            c.trigger("B_HouseMode_Away")

    Usage (live event stream, blocking):
        def on_event(line):
            print(line)
        with LocalClient(..., event_callback=on_event) as c:
            c.run_forever()
    """

    def __init__(
        self,
        host: str,
        token_id: str,
        token_secret: str,
        port: int = CONTROLLER_PORT,
        event_callback: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.host = host
        self.token_id = token_id
        self.token_secret = token_secret
        self.port = port
        self._event_callback = event_callback
        self._sock: Optional[socket.socket] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self.controller_info: Optional[ControllerInfo] = None

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    def connect(self) -> ControllerInfo:
        """Open TCP connection, read SMUX banner, send LOGIN-TO handshake."""
        self._stop.clear()
        self._sock = socket.create_connection((self.host, self.port), timeout=10)
        self._sock.settimeout(None)  # blocking

        # Read the initial <connect .../> banner (SMUX framed)
        banner_msgs = self._read_smux_messages(timeout=5.0)
        for msg in banner_msgs:
            if "<connect" in msg:
                self.controller_info = ControllerInfo(msg)
                break

        # Handshake: send LOGIN-TO with SMUX framing
        login = (
            f"LOGIN-TO "
            f"<tokenId>{self.token_id}</tokenId>"
            f"<secret>{self.token_secret}</secret>"
            f"<dev>WEB</dev>"
            f"<feet>16</feet>"
        )
        self._send(login)

        if self._event_callback:
            self._reader_thread = threading.Thread(
                target=self._read_loop, daemon=True
            )
            self._reader_thread.start()

        return self.controller_info or ControllerInfo("")

    def disconnect(self) -> None:
        self._stop.set()
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def run_forever(self) -> None:
        """Block until disconnected (Ctrl-C / disconnect())."""
        try:
            while not self._stop.is_set():
                time.sleep(0.1)
        except KeyboardInterrupt:
            pass

    def __enter__(self) -> "LocalClient":
        self.connect()
        return self

    def __exit__(self, *_: object) -> None:
        self.disconnect()

    # ------------------------------------------------------------------
    # Sending commands
    # ------------------------------------------------------------------

    def trigger(self, function_name: str, value: int = 0) -> None:
        """
        Trigger a named function on the controller.

        function_name: one of the B_* names from the controller config
                       e.g. "B_LightUtelys_ON", "B_HouseMode_Away"
        value: optional value (0 for buttons/toggles; unused for dimmers -- use dim() instead)
        """
        self._send(f"new_state {function_name} {value}")

    def dim(self, set_action_name: str, percent: int) -> None:
        """
        Set a dimmer to a percentage level (0-100).

        set_action_name: the B_D_*_SET function name,
                         e.g. "B_D_Hall2etgHallTrappEntre_SET"
        percent: 0-100

        The controller requires two messages:
          set_value M_D_{name}_Val {percent}   -- write target value to register
          new_state B_D_{name}_SET 0           -- trigger the SET action
        """
        # Derive the value-register name: B_D_{name}_SET -> M_D_{name}_Val
        if set_action_name.startswith("B_D_") and set_action_name.endswith("_SET"):
            val_register = "M_D_" + set_action_name[4:-4] + "_Val"
        else:
            raise ValueError(
                f"dim() expects a B_D_*_SET action name, got {set_action_name!r}"
            )
        percent = max(0, min(100, percent))
        self._send(f"set_value {val_register} {percent}")
        self._send(f"new_state {set_action_name} 0")

    def request_state(self, numeric_id: int) -> None:
        """
        Request current state for a specific object by numeric ID.
        The controller responds with an SSN event containing the current value.
        """
        self._send(f"d_obj {numeric_id}")

    def send_raw(self, command: str) -> None:
        """Send a raw protocol command (SMUX-framed)."""
        self._send(command)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _send(self, message: str) -> None:
        if not self._sock:
            raise RuntimeError("Not connected")
        self._sock.sendall(_smux_encode(message))

    def _read_smux_messages(self, timeout: float = 3.0) -> list[str]:
        """Read available bytes and return parsed SMUX messages."""
        if not self._sock:
            return []
        buf = b""
        deadline = time.monotonic() + timeout
        while True:
            remaining = max(0.0, deadline - time.monotonic())
            if remaining == 0:
                break
            ready, _, _ = select.select([self._sock], [], [], remaining)
            if not ready:
                break
            chunk = self._sock.recv(RECV_BUF)
            if not chunk:
                break
            buf += chunk
            # Stop if we have at least one complete message
            msgs, _ = _smux_parse(buf)
            if msgs:
                return msgs
        msgs, _ = _smux_parse(buf)
        return msgs

    def read_lines(self, count: int = 20, timeout: float = 3.0) -> list[str]:
        """Read up to `count` SMUX messages with a combined timeout."""
        if not self._sock:
            return []
        buf = b""
        deadline = time.monotonic() + timeout
        collected: list[str] = []

        while len(collected) < count and time.monotonic() < deadline:
            remaining = max(0.05, deadline - time.monotonic())
            ready, _, _ = select.select([self._sock], [], [], remaining)
            if not ready:
                break
            chunk = self._sock.recv(RECV_BUF)
            if not chunk:
                break
            buf += chunk
            msgs, buf = _smux_parse(buf)
            collected.extend(msgs)

        return collected[:count]

    def _read_loop(self) -> None:
        from .config import update_id_cache
        _id_batch: dict[str, int] = {}
        _batch_count = 0

        buf = b""
        while not self._stop.is_set():
            if not self._sock:
                break
            try:
                ready, _, _ = select.select([self._sock], [], [], 0.5)
                if not ready:
                    continue
                chunk = self._sock.recv(RECV_BUF)
                if not chunk:
                    break
                buf += chunk
                msgs, buf = _smux_parse(buf)
                for text in msgs:
                    text = text.strip()
                    if not text:
                        continue
                    # Echo keepalive ACKs back to the controller (SMUX-framed)
                    if "x_bm_st ACK_DIR" in text or "PANEL_BRIGHTNESS" in text:
                        try:
                            self._send(text)
                        except OSError:
                            pass
                    # Harvest name->id pairs from RSN/SSN events for d_obj use
                    m = _RSN_ID_RE.match(text)
                    if m:
                        num_id, name = int(m.group(1)), m.group(2)
                        if name not in _id_batch:
                            _id_batch[name] = num_id
                            _batch_count += 1
                            # Flush to disk every 20 new IDs
                            if _batch_count % 20 == 0:
                                update_id_cache(_id_batch)
                    if self._event_callback:
                        self._event_callback(text)
            except OSError:
                break

        # Final flush of any harvested IDs
        if _id_batch:
            try:
                update_id_cache(_id_batch)
            except Exception:
                pass
