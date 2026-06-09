# Sensio Eopt / X-Comfort for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)

Home Assistant integration for [Eaton X-Comfort / Sensio Eopt](https://www.eaton.com/xcomfort) smart home systems, connecting locally over LAN — no cloud required.

## Features

- Local LAN connection (no cloud, no polling — push-based)
- Automatic device discovery from your controller's function list
- Supported device types:
  - **Lights** — on/off groups with optional lighting scenes
  - **Dimmers** — brightness control (0–100%)
  - **Switches** — binary relay outputs
  - **Climate** — floor heating zones with preset modes (Home / Away / Night / Vacation)
  - **Select** — zone and house-wide mode selectors
  - **Buttons** — one-shot scene triggers and alarm resets
- State persistence across Home Assistant restarts

## Requirements

- Eaton X-Comfort / Sensio Eopt controller reachable on your local network
- The `smarthome.bash` credential file from your installer or the Sensio Eopt app

## Installation via HACS

1. In HACS, go to **Integrations** → three-dot menu → **Custom repositories**
2. Add `https://github.com/eksepsjon/sensio-eopt-control` with category **Integration**
3. Click **Download** on the Sensio Eopt / X-Comfort card
4. Restart Home Assistant

## Manual Installation

1. Copy the `custom_components/sensio_eopt` folder into your `<config>/custom_components/` directory
2. Restart Home Assistant

## Setup

1. Go to **Settings → Devices & Services → Add Integration** and search for **Sensio Eopt**
2. **Step 1 — Credentials:** Paste the contents of your `smarthome.bash` script. This file contains the base64-encoded token ID and secret used to authenticate with the controller.
3. **Step 2 — Controller IP:** Enter the local IP address of your Sensio Eopt / X-Comfort controller. The integration will test the connection before saving.

### Getting your `smarthome.bash` file

The credential file is typically provided by your installer or can be exported from the Sensio Eopt configuration tool. It looks like:

```bash
#!/bin/bash
# ...
TOKEN_ID="..."
TOKEN_SECRET="..."
```

## Troubleshooting

- **Cannot connect** — verify the controller IP and that port 10023 is reachable from your Home Assistant host
- **No devices found** — check that the function list in the credential file is populated; re-export from the Sensio Eopt tool if needed
- **Entities unavailable after restart** — the integration reconnects automatically; allow a few seconds after HA starts

## Contributing

Issues and pull requests are welcome at [github.com/eksepsjon/sensio-eopt-control](https://github.com/eksepsjon/sensio-eopt-control/issues).
