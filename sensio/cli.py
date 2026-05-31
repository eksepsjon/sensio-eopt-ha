"""
sensio CLI — control Sensio/X-Comfort smart home installations.

Credentials come from the supplier-provided smarthome.bash script.
No OAuth2 or cloud API required for local LAN control.

Quick start:
    sensio setup --token-id 4990ce24-... --token-secret aQhU... \\
                 --mac 98:02:84:01:42:C6 --controller-ip 192.168.68.119

    sensio list
    sensio run "Kitchen/Stue Light On"
    sensio run B_LightKjkkenStue_ON
    sensio monitor
"""

from __future__ import annotations

import sys
import time
from typing import Optional

import click
from rich.console import Console
from rich.table import Table

from .config import (
    clear_credentials,
    is_configured,
    load_credentials,
    load_id_cache,
    save_credentials,
)
from .events import parse_event
from .functions import FUNCTIONS, find_function
from .local import LocalClient

console = Console()


def _require_config() -> dict:
    if not is_configured():
        console.print(
            "[red]Not configured.[/red] Run [bold]sensio setup[/bold] first.\n"
            "Get the credentials from your supplier's smarthome.bash script:\n"
            "  sensio setup --token-id TOKEN --token-secret SECRET \\\n"
            "               --mac MAC --controller-ip IP"
        )
        sys.exit(1)
    return load_credentials()


# ---------------------------------------------------------------------------
# CLI root
# ---------------------------------------------------------------------------

@click.group()
def cli() -> None:
    """Sensio/X-Comfort smart home CLI."""


# ---------------------------------------------------------------------------
# setup / teardown
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--token-id", required=True, envvar="SENSIO_TOKEN_ID",
              help="Token GUID (from smarthome.bash 'token=' line)")
@click.option("--token-secret", required=True, envvar="SENSIO_TOKEN_SECRET",
              help="Token secret (from smarthome.bash 'secret=' line)")
@click.option("--mac", required=True, envvar="SENSIO_MAC",
              help="Controller MAC address (from smarthome.bash 'mac=' line)")
@click.option("--controller-ip", required=True, envvar="SENSIO_CONTROLLER_IP",
              help="Controller LAN IP (find via 'arp -a | grep MAC')")
def setup(token_id: str, token_secret: str, mac: str, controller_ip: str) -> None:
    """Save controller credentials from the supplier's smarthome.bash script.

    \b
    Where to find the values:
      token=     → --token-id
      secret=    → --token-secret
      mac=       → --mac
      controller IP: run  arp -a | grep <MAC>  from this PC
    """
    save_credentials(token_id, token_secret, mac, controller_ip)
    console.print(f"[green]Saved.[/green] Credentials stored in ~/.sensio/config.json")

    # Quick connectivity test
    console.print(f"Testing connection to {controller_ip}:10023 …")
    try:
        client = LocalClient(controller_ip, token_id, token_secret)
        info = client.connect()
        client.disconnect()
        console.print(f"[green]Connected![/green] {info}")
    except Exception as exc:
        console.print(f"[yellow]Connection test failed:[/yellow] {exc}")
        console.print("Credentials saved; check controller IP and network.")


@cli.command()
def forget() -> None:
    """Remove stored credentials."""
    clear_credentials()
    console.print("Credentials cleared.")


# ---------------------------------------------------------------------------
# list — show all available functions
# ---------------------------------------------------------------------------

@cli.command("list")
@click.option("--filter", "-f", "filt", default="",
              help="Filter by substring (case-insensitive)")
def list_functions(filt: str) -> None:
    """List all controllable functions on this installation."""
    t = Table(title="Available functions", show_lines=False)
    t.add_column("#", style="dim", width=4)
    t.add_column("Display name", min_width=35)
    t.add_column("Internal name", style="cyan")

    shown = 0
    for i, (func, label) in enumerate(FUNCTIONS):
        if filt and filt.lower() not in label.lower() and filt.lower() not in func.lower():
            continue
        t.add_row(str(i), label, func)
        shown += 1

    console.print(t)
    console.print(f"[dim]{shown} function(s) shown[/dim]")


# ---------------------------------------------------------------------------
# run — trigger a function by name or internal code
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("function_name")
@click.option("--value", "-v", type=int, default=0, show_default=True,
              help="Numeric value (0 for buttons; 0-255 for dimmers)")
@click.option("--dry-run", is_flag=True,
              help="Show what would be sent without actually sending")
def run(function_name: str, value: int, dry_run: bool) -> None:
    """Trigger a function by display name or internal B_* name.

    \b
    Examples:
        sensio run "Kjøkken/Stue Light On"
        sensio run "kitchen light on"           # case-insensitive partial match
        sensio run B_LightKjkkenStue_ON
        sensio run B_D_KjkkenyKjkkenStue_SET --value 200
    """
    # Resolve: exact internal name or display name search
    if function_name.startswith("B_"):
        # Direct internal name
        matched_func = function_name
        matched_label = next(
            (lbl for fn, lbl in FUNCTIONS if fn == function_name), function_name
        )
    else:
        result = find_function(function_name)
        if result is None:
            console.print(
                f"[red]No function found matching[/red] {function_name!r}\n"
                "Run [bold]sensio list[/bold] to see all available functions."
            )
            sys.exit(1)
        matched_func, matched_label = result

    console.print(f"Function: [bold]{matched_label}[/bold]  ([cyan]{matched_func}[/cyan])")

    if dry_run:
        console.print(f"[dim]Would send:[/dim] new_state {matched_func} {value}")
        return

    creds = _require_config()
    try:
        with LocalClient(
            creds["controller_ip"],
            creds["token_id"],
            creds["token_secret"],
        ) as client:
            client.trigger(matched_func, value)
            # Small pause to allow the controller to respond before closing
            time.sleep(0.3)
        console.print("[green]Done.[/green]")
    except Exception as exc:
        console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# dim — set a dimmer to a percentage
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("set_action")
@click.argument("percent", type=click.IntRange(0, 100))
@click.option("--dry-run", is_flag=True,
              help="Show what would be sent without actually sending")
def dim(set_action: str, percent: int, dry_run: bool) -> None:
    """Set a dimmer to PERCENT brightness (0–100).

    \b
    SET_ACTION is the B_D_*_SET function name, e.g.:
        sensio dim B_D_Hall2etgHallTrappEntre_SET 50
        sensio dim B_D_Hall2etgHallTrappEntre_SET 0    # off
        sensio dim B_D_Hall2etgHallTrappEntre_SET 100  # full

    The controller uses a two-message protocol:
      set_value M_D_{name}_Val {percent}
      new_state B_D_{name}_SET 0
    """
    if not (set_action.startswith("B_D_") and set_action.endswith("_SET")):
        console.print(
            f"[red]Error:[/red] SET_ACTION must be a B_D_*_SET name, got {set_action!r}\n"
            "Run [bold]sensio list[/bold] and look for B_D_* entries."
        )
        sys.exit(1)

    val_register = "M_D_" + set_action[4:-4] + "_Val"
    console.print(
        f"Dimmer: [cyan]{set_action}[/cyan]  [bold]{percent}%[/bold]"
    )

    if dry_run:
        console.print(f"[dim]Would send:[/dim] set_value {val_register} {percent}")
        console.print(f"[dim]Would send:[/dim] new_state {set_action} 0")
        return

    creds = _require_config()
    try:
        with LocalClient(
            creds["controller_ip"],
            creds["token_id"],
            creds["token_secret"],
        ) as client:
            client.dim(set_action, percent)
            time.sleep(0.3)
        console.print("[green]Done.[/green]")
    except Exception as exc:
        console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# monitor — live event stream
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--raw", is_flag=True, help="Show raw unparsed event lines")
def monitor(raw: bool) -> None:
    """Connect to local controller and stream live events (Ctrl-C to stop).

    \b
    Event types shown:
      [trigger]  B_* function was executed
      [dimmer]   D_* device value changed (0-255)
      [register] M_* metadata register updated
    """
    creds = _require_config()

    def on_event(line: str) -> None:
        ts = time.strftime("%H:%M:%S")
        if raw:
            console.print(f"[dim]{ts}[/dim] {line}")
            return

        evt = parse_event(line)
        if evt is None:
            # keepalive or unknown — show dimly
            console.print(f"[dim]{ts} {line}[/dim]")
            return

        if evt.is_trigger:
            console.print(
                f"[dim]{ts}[/dim] [bold green][trigger][/bold green]  "
                f"[cyan]{evt.name}[/cyan]"
            )
        elif evt.is_device_value:
            level = evt.int_value
            bar = "|" * (level // 5) if level > 0 else "-"
            console.print(
                f"[dim]{ts}[/dim] [bold yellow][dimmer ][/bold yellow]  "
                f"[cyan]{evt.name}[/cyan]  "
                f"[white]{level}[/white]%  {bar}"
            )
        elif evt.is_register:
            console.print(
                f"[dim]{ts}[/dim] [dim][register][/dim]  "
                f"[dim]{evt.name}  {evt.float_value:.3f}[/dim]"
            )
        else:
            console.print(f"[dim]{ts}[/dim] {line}")

    console.print(
        f"Connecting to [bold]{creds['controller_ip']}:10023[/bold] …"
    )
    try:
        with LocalClient(
            creds["controller_ip"],
            creds["token_id"],
            creds["token_secret"],
            event_callback=on_event,
        ) as client:
            info = client.controller_info
            if info:
                console.print(f"[green]Connected.[/green] {info}")
            console.print("Streaming events (Ctrl-C to stop) …\n")
            client.run_forever()
    except KeyboardInterrupt:
        console.print("\nDisconnected.")
    except Exception as exc:
        console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# state — snapshot of current device values
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--timeout", "-t", default=3.0, show_default=True,
              help="Seconds to collect events after connect")
def state(timeout: float) -> None:
    """Show current device values.

    Connects to the controller and actively requests state for all known
    objects via d_obj (if IDs have been discovered from previous monitor/state
    runs), then also passively collects any RSN events that arrive.

    \b
    Tips:
      - Run `sensio monitor` for a while first to build the ID cache
        (~/.sensio/id_cache.json) — after that, state is fetched actively
      - Without a cache, only devices that changed recently will appear
      - Dimmer levels are 0-100 (percent); use `sensio dim` to set them
    """
    creds = _require_config()

    # Collect: name -> latest SensioEvent
    from .events import SensioEvent
    latest: dict[str, SensioEvent] = {}

    def on_event(line: str) -> None:
        evt = parse_event(line)
        if evt is not None:
            latest[evt.name] = evt

    # Load cached name->id mappings from previous runs
    id_cache = load_id_cache()
    # Only request D_* and M_* objects (device values and registers)
    requestable = {name: nid for name, nid in id_cache.items()
                   if name.startswith(("D_", "M_"))}

    if requestable:
        console.print(
            f"Requesting state for [bold]{len(requestable)}[/bold] known objects, "
            f"collecting for {timeout}s..."
        )
    else:
        console.print(
            f"[yellow]No ID cache yet[/yellow] - collecting passively for {timeout}s.\n"
            f"[dim]Run [bold]sensio monitor[/bold] to build the cache for faster state queries.[/dim]"
        )

    try:
        client = LocalClient(
            creds["controller_ip"],
            creds["token_id"],
            creds["token_secret"],
            event_callback=on_event,
        )
        client.connect()
        # Actively request current state for all known object IDs
        for numeric_id in requestable.values():
            client.request_state(numeric_id)
        time.sleep(timeout)
        client.disconnect()
    except Exception as exc:
        console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)

    if not latest:
        console.print("[yellow]No events received.[/yellow]  "
                      "Try running a command first, then immediately run state.")
        return

    # Split into triggers, devices, registers
    triggers  = {n: e for n, e in latest.items() if e.is_trigger}
    devices   = {n: e for n, e in latest.items() if e.is_device_value}
    registers = {n: e for n, e in latest.items() if e.is_register}

    if devices:
        t = Table(title="Device values (D_*)", show_lines=False)
        t.add_column("Device", style="cyan")
        t.add_column("Value", width=6)
        t.add_column("State")
        for name, evt in sorted(devices.items()):
            v = evt.int_value
            state_str = (
                "[green]ON[/green]" if v > 0 else "[dim]off[/dim]"
            )
            bar = "|" * (v // 5) if v > 0 else ""
            t.add_row(name, f"{v}%", f"{state_str}  {bar}")
        console.print(t)

    if triggers:
        t = Table(title="Last executed functions (B_*)", show_lines=False)
        t.add_column("Function", style="cyan")
        for name in sorted(triggers):
            t.add_row(name)
        console.print(t)

    if registers:
        t = Table(title="Registers (M_*)", show_lines=False)
        t.add_column("Register", style="dim cyan")
        t.add_column("Value", style="dim")
        for name, evt in sorted(registers.items()):
            t.add_row(name, f"{evt.float_value:.3f}")
        console.print(t)


# ---------------------------------------------------------------------------
# status — show current config
# ---------------------------------------------------------------------------

@cli.command()
def status() -> None:
    """Show current configuration."""
    if not is_configured():
        console.print("[yellow]Not configured.[/yellow] Run `sensio setup` first.")
        return
    creds = load_credentials()
    t = Table(title="Current configuration")
    t.add_column("Key")
    t.add_column("Value")
    t.add_row("controller_ip", creds["controller_ip"])
    t.add_row("mac", creds["mac"])
    t.add_row("token_id", creds["token_id"])
    t.add_row("token_secret", creds["token_secret"][:6] + "…")
    console.print(t)
    console.print(f"[dim]Config file: ~/.sensio/config.json[/dim]")
