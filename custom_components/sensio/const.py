"""Constants for the Sensio / X-Comfort integration."""

DOMAIN = "sensio"

# Config entry keys
CONF_TOKEN_ID     = "token_id"
CONF_TOKEN_SECRET = "token_secret"
CONF_MAC          = "mac"

# Dispatcher signal: fired for every raw event line from the controller.
# Payload: str (the raw line, e.g. "DB:EVENT,..." or "RPC B_LightUtelys_ON")
SIGNAL_EVENT = f"{DOMAIN}_event"

# Dispatcher signal: fired when connection state changes.
# Payload: bool (True = connected, False = disconnected)
SIGNAL_CONNECTED = f"{DOMAIN}_connected"

# Platforms registered by this integration
PLATFORMS = ["light", "switch", "climate", "select", "button"]
