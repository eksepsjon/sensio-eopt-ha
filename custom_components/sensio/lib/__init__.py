"""
Bundled Sensio protocol library for the Home Assistant custom component.

This package is a copy of the ``sensio`` Python package from the sensio-control
repo.  It is bundled here so the custom component is self-contained and does not
require the ``sensio`` package to be installed separately in the HA Python
environment.

Do not import this package directly — import from the individual modules:
    from .lib.controller import SensioController
    from .lib.events import SensioEvent, parse_event
    from .lib.devices import discover_devices
"""
