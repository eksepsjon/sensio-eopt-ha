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

## Repository Layout

```
sensio_eopt/                          # SDK package (used by CLI and copied into HA)
├── local.py                          # Synchronous TCP client (CLI/scripting)
├── controller.py                     # Async TCP client (Home Assistant)
├── devices.py                        # Device discovery & models
├── events.py                         # Event parser
├── config.py                         # Credentials & config file management
├── cli.py                            # Click-based CLI commands
├── functions.py                      # In-memory function index loader
├── auth.py                           # Portal login & OAuth2 (optional cloud auth)
└── cloud.py                          # REST API client for unity.eopthome.no (optional)

custom_components/sensio_eopt/        # Home Assistant integration (v0.2.0)
├── __init__.py                       # Entry point: setup/unload
├── const.py                          # DOMAIN, SIGNAL_EVENT, SIGNAL_CONNECTED, PLATFORMS
├── config_flow.py                    # UI setup wizard (bash paste → IP)
├── coordinator.py                    # Push-based event hub wrapping SensioEoptController
├── entity.py                         # Base class (RestoreEntity, optimistic state)
├── light.py                          # SensioEoptLightEntity, SensioEoptDimmerEntity
├── switch.py                         # SensioEoptSwitchEntity
├── climate.py                        # SensioEoptClimateEntity (floor heating)
├── button.py                         # SensioEoptButtonEntity, SensioEoptModeButtonEntity
├── select.py                         # Empty stub (superseded by button entities)
├── manifest.json                     # iot_class: local_push, no extra requirements
└── lib/                              # Verbatim copy of sensio_eopt SDK for HA isolation
    ├── local.py, controller.py, devices.py, events.py, config.py

tests/
├── conftest.py                       # asyncio.DefaultEventLoopPolicy() for all async tests
├── test_protocol.py                  # SMUX framing and LocalClient tests
├── test_devices.py                   # Device discovery tests
├── test_events.py                    # Event parser tests
└── test_coordinator.py               # HA coordinator and entity tests
```

## Architecture

The codebase has two parallel implementations: the `sensio_eopt/` SDK (used by the CLI) and `custom_components/sensio_eopt/lib/` (a deliberate copy for Home Assistant isolation). When fixing protocol bugs or device logic, changes must be applied to **both** locations.

### Protocol layer (`sensio_eopt/local.py`, `sensio_eopt/controller.py`)

SMUX framing:
- Frames: `\x01{msg}\x02` (standard), `\x07{header}\x01{msg}\x02` (with header), `\x05{msg}` (error)
- Encoding: cp1252 (Windows-1252), TCP port 10023, no TLS
- Handshake: receive `<connect sn=... ip=... mac=.../>`, then send LOGIN-TO with token_id + secret
- Keepalives: `x_bm_st ACK_DIR seq={N}` and `PANEL_BRIGHTNESS` must be echoed back

`LocalClient` (`local.py`) is synchronous (blocking socket + reader thread) — used by the CLI.  
`SensioEoptController` (`controller.py`) is async (`asyncio.StreamReader/Writer`) with auto-reconnect and exponential backoff (5s) — used by Home Assistant.

### Device discovery (`sensio_eopt/devices.py`)

Devices are discovered by regex-matching a flat list of function names parsed from the supplier's `smarthome.bash` script. Name patterns and resulting types:

| Pattern | Class |
|---------|-------|
| `B_Light{Zone}_ON/OFF/Sc{1-4}` | `SensioEoptLight` |
| `B_D_{Name}_SET` | `SensioEoptDimmer` |
| `B_R_{Name}_ON/OFF` | `SensioEoptRelay` |
| `B_*{digits}_Temp_Dec` (anchor) | `SensioEoptThermostat` |
| `B_*Mode_Away` (anchor) | `SensioEoptModeSelector` |
| Remaining `B_*` | `SensioEoptScene` |

Discovery order matters: dimmers and relays are consumed first; lights, thermostats, and mode selectors use anchored patterns; whatever remains becomes scenes. `DeviceRegistry` is the container for all discovered devices.

### Event parsing (`sensio_eopt/events.py`)

Events arrive as text lines: `RSN/SSN {seq} {name} {typeId} {enabled} {state} {value}`

Type IDs:
- `6` = trigger (`B_*` function executed)
- `21` = integer device value (`D_*` current state)
- `23` = float register (`M_*` metadata, e.g. setpoints)

`SensioEoptEvent` dataclass provides `is_trigger`, `is_device_value`, `is_register`, `int_value`, `float_value`, `is_on`.

### Home Assistant integration (`custom_components/sensio_eopt/`)

- **`coordinator.py`**: Not a `DataUpdateCoordinator` — push-based, never polls. Wraps `SensioEoptController`, maintains a `state_cache: dict[str, SensioEoptEvent]`, and dispatches two HA dispatcher signals:
  - `SIGNAL_EVENT = "sensio_eopt_event"` (payload = `SensioEoptEvent`)
  - `SIGNAL_CONNECTED = "sensio_eopt_connected"` (payload = bool)
- **`entity.py`**: Base class (`RestoreEntity`). `_attr_should_poll = False`. Subscribes to both signals in `async_added_to_hass()`, replays coordinator cache on startup for instant state. Applies optimistic state (assumes commands succeed immediately, corrects on incoming events).
- **`config_flow.py`**: Step 1 — user pastes `smarthome.bash` script (base64-decoded to extract token_id, token_secret, MAC, functions). Step 2 — enter controller IP and test connection.
- **`light.py`**: `SensioEoptLightEntity` handles on/off + up to 4 scenes as HA effects. `SensioEoptDimmerEntity` maps brightness 0–255 (HA) ↔ 0–100 (protocol) and tracks both `D_*` (type 21) and `M_D_*_Val` (type 23) events.
- **`switch.py`**: `SensioEoptSwitchEntity` tracks `B_R_*_ON/OFF` triggers and `D_R_*` device values.
- **`climate.py`**: `SensioEoptClimateEntity` for floor heating. HVAC modes: HEAT / OFF (OFF = away). Preset modes: home / away / night / vacation. Temperature encoding: `value = int(°C × 10)`. Supports direct `_Set` command or fallback to `_Inc/_Dec` stepping.
- **`button.py`**: `SensioEoptButtonEntity` (one-shot scene trigger) and `SensioEoptModeButtonEntity` (one button per mode option). Mode selectors are exposed as buttons, not a select entity.
- **`select.py`**: Empty stub — kept for platform registration but no entities are created.

### Config & state (`sensio_eopt/config.py`)

- `~/.sensio_eopt/config.json`: credentials (token_id, token_secret, controller_ip), mode 0o600
- `~/.sensio_eopt/id_cache.json`: name→numeric ID mappings, populated from live RSN events, used for `d_obj {id}` state queries
- `~/.sensio_eopt/functions.json`: parsed function list

Environment variable overrides: `SENSIO_TOKEN_ID`, `SENSIO_TOKEN_SECRET`, `SENSIO_CONTROLLER_IP`.

### Optional cloud modules

`auth.py` handles OAuth2 portal login to `unity.eopthome.no` (harvests ASP.NET VIEWSTATE, exchanges code for Bearer token, stores in keyring). `cloud.py` wraps the REST API. Both are optional — local LAN control works without them.

### CLI (`sensio_eopt/cli.py`)

Click-based commands: `setup`, `config`, `list`, `run`, `dim`, `monitor`, `state`, `status`, `forget`. Uses `rich` for formatted table output.

## Key Gotchas

- **Dual codebase**: `custom_components/sensio_eopt/lib/` mirrors `sensio_eopt/`. Both must be kept in sync for any changes to `local.py`, `controller.py`, `devices.py`, `events.py`, or `config.py`.
- **cp1252 encoding**: All TCP traffic is Windows-1252, not UTF-8. Encoding errors will silently corrupt commands.
- **Thermostat temperatures** are transmitted multiplied by 10 (e.g., 21.5°C → `215`).
- **No DataUpdateCoordinator**: `SensioEoptCoordinator` is push-driven. Do not add polling.
- **conftest.py** sets `asyncio.DefaultEventLoopPolicy()` for all async tests to avoid conflicts with HA's custom event loop policy.
- **select.py is empty**: Mode selectors are exposed as `button` entities, not `select` entities. The file exists only to satisfy the `PLATFORMS` list.
- `smarthome.bash` and `config.json` are in `.gitignore` — never commit them.
