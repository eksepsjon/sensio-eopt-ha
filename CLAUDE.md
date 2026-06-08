# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Is

A Python SDK and Home Assistant custom integration for local LAN control of Sensio/X-Comfort smart home hubs. The core is a reverse-engineered binary protocol (SMUX) that communicates over TCP port 10023 using Windows-1252 encoding. No cloud required, no build step — pure Python.

## Commands

```bash
# Run all tests
pytest tests/ -v

# Run a single test
pytest tests/test_protocol.py::TestSmuxEncode::test_simple_message -v

# Install SDK in editable mode (requires pip)
pip install -e .
```

There is no lint configuration. The project has no pyproject.toml, setup.cfg, Makefile, or CI pipeline.

## Architecture

The codebase has two parallel implementations: the `sensio/` SDK (used by the CLI) and `custom_components/sensio/lib/` (a deliberate copy for Home Assistant isolation). When fixing protocol bugs or device logic, changes must be applied to **both** locations.

### Protocol layer (`sensio/local.py`, `sensio/controller.py`)

The SMUX framing:
- Frames are delimited: `\x01{msg}\x02` (standard), `\x07{header}\x01{msg}\x02` (with header), `\x05{msg}` (error)
- Encoding: cp1252 (Windows-1252), TCP port 10023, no TLS
- Handshake: receive `<connect sn=... ip=... mac=.../>`, then send LOGIN with token_id + secret
- Keepalives arrive as `x_bm_st ACK_DIR seq={N}` and must be echoed back

`LocalClient` (`local.py`) is synchronous (blocking sockets + reader thread) — used by the CLI.  
`SensioController` (`controller.py`) is async (`asyncio.StreamReader/Writer`) with auto-reconnect — used by Home Assistant.

### Device discovery (`sensio/devices.py`)

Devices are discovered by regex-matching a flat list of function names parsed from the supplier's `smarthome.bash` script. Name patterns:
- `B_Light{Zone}_ON/OFF/Sc{1-4}` → `SensioLight`
- `B_D_{Name}_SET` → `SensioDimmer`
- `B_R_{Name}_ON/OFF` → `SensioRelay`
- `B_{Zone}0{digits}_Temp_*` → `SensioThermostat`
- `B_{Zone}Mode_*` → `SensioModeSelector`
- Remaining `B_*` functions → `SensioScene`

### Event parsing (`sensio/events.py`)

Events arrive as text lines: `RSN/SSN {seq} {name} {typeId} {enabled} {state} {value}`  
Type IDs: `6` = trigger, `21` = integer device value, `23` = float register.  
`SensioEvent` dataclass provides `is_trigger`, `is_device_value`, `is_register`, `int_value`, `float_value`, `is_on`.

### Home Assistant integration (`custom_components/sensio/`)

- **`coordinator.py`**: Not a `DataUpdateCoordinator`. It wraps `SensioController`, dispatches HA signals on each parsed event. Two signals: `sensio_event` (payload = `SensioEvent`) and `sensio_connected` (payload = bool).
- **`entity.py`**: Base class — uses `RestoreEntity`, subscribes to dispatcher signals, applies optimistic state (assumes commands succeed immediately, corrects on incoming events).
- **`config_flow.py`**: Accepts a pasted `smarthome.bash` file and controller IP. The bash file is base64-decoded internally to extract the function list.
- **Entity files** (`light.py`, `switch.py`, `climate.py`, `select.py`, `button.py`): Standard HA entity patterns. Brightness is normalized 0–255 (HA) ↔ 0–100 (protocol).

### Config & state (`sensio/config.py`)

- `~/.sensio/config.json`: credentials (token_id, token_secret, controller_ip)
- `~/.sensio/id_cache.json`: name→numeric ID mappings, populated from live RSN events, used for `d_obj {id}` state queries
- `~/.sensio/functions.json`: parsed function list

Environment variable overrides: `SENSIO_TOKEN_ID`, `SENSIO_TOKEN_SECRET`, `SENSIO_CONTROLLER_IP`.

## Key Gotchas

- **Dual codebase**: `custom_components/sensio/lib/` mirrors `sensio/`. Both must be kept in sync for protocol/device/event changes.
- **cp1252 encoding**: All TCP traffic is Windows-1252, not UTF-8. Encoding errors will silently corrupt commands.
- **Thermostat temperatures** are transmitted multiplied by 10 (`set_value ... {temp*10}`).
- `conftest.py` forces `SelectorEventLoop` policy in tests to avoid conflicts with HA's custom event loop.
- `smarthome.bash` and `config.json` are in `.gitignore` — never commit them.
