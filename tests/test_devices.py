"""
Tests for device discovery (sensio/devices.py).
Uses a small subset of realistic function names.
"""

import pytest
from sensio.devices import discover_devices, SensioLight, SensioDimmer, SensioRelay


SAMPLE_FUNCTIONS = [
    # Lights
    ("B_LightHallTrappEntre_ON",       "Hall/Trapp/Entre Light On"),
    ("B_LightHallTrappEntre_OFF",      "Hall/Trapp/Entre Light Off"),
    ("B_LightHallTrappEntre_ToggleOn", "Hall/Trapp/Entre Light Toggle"),
    ("B_LightHallTrappEntre_Sc1",      "Hall/Trapp/Entre Scene 1"),
    ("B_LightHallTrappEntre_Sc2",      "Hall/Trapp/Entre Scene 2"),
    ("B_LightKjkkenStue_ON",           "Kjøkken/Stue Light On"),
    ("B_LightKjkkenStue_OFF",          "Kjøkken/Stue Light Off"),
    # Dimmer
    ("B_D_Hall2etgHallTrappEntre_SET", "Hall 2etg Dimmer Set"),
    ("B_D_SpotlightsKjkken_SET",       "Spotlights Kjøkken Set"),
    # Relay
    ("B_R_UtelysUtelys_ON",            "Utelys On"),
    ("B_R_UtelysUtelys_OFF",           "Utelys Off"),
    # Leftover / scene
    ("B_HouseMode_Away",               "House Away"),
    ("B_HouseMode_In",                 "House Home"),
    ("B_HouseMode_Night",              "House Night"),
    ("B_HouseMode_Vacation",           "House Vacation"),
]


@pytest.fixture
def reg():
    return discover_devices(SAMPLE_FUNCTIONS)


class TestDiscoverLights:
    def test_light_count(self, reg):
        assert len(reg.lights) == 2

    def test_light_fields(self, reg):
        hall = next(l for l in reg.lights if "HallTrappEntre" in l.unique_id)
        assert hall.func_on  == "B_LightHallTrappEntre_ON"
        assert hall.func_off == "B_LightHallTrappEntre_OFF"
        assert hall.func_toggle == "B_LightHallTrappEntre_ToggleOn"
        assert hall.scenes == [
            "B_LightHallTrappEntre_Sc1",
            "B_LightHallTrappEntre_Sc2",
        ]

    def test_light_no_scenes(self, reg):
        kjk = next(l for l in reg.lights if "KjkkenStue" in l.unique_id)
        assert kjk.scenes == []
        assert kjk.func_toggle is None


class TestDiscoverDimmers:
    def test_dimmer_count(self, reg):
        assert len(reg.dimmers) == 2

    def test_dimmer_func_set(self, reg):
        hall = next(d for d in reg.dimmers if "Hall2etg" in d.func_set)
        assert hall.func_set == "B_D_Hall2etgHallTrappEntre_SET"
        assert hall.brightness_pct == 0  # initial state

    def test_dimmer_not_in_scenes(self, reg):
        # Dimmers should not appear as scenes
        scene_funcs = {s.func for s in reg.scenes}
        for d in reg.dimmers:
            assert d.func_set not in scene_funcs


class TestDiscoverRelays:
    def test_relay_count(self, reg):
        assert len(reg.relays) == 1

    def test_relay_fields(self, reg):
        r = reg.relays[0]
        assert r.func_on  == "B_R_UtelysUtelys_ON"
        assert r.func_off == "B_R_UtelysUtelys_OFF"


class TestDiscoverModeSelectors:
    def test_mode_selector_count(self, reg):
        assert len(reg.mode_selectors) == 1

    def test_mode_selector_options(self, reg):
        sel = reg.mode_selectors[0]
        assert sel.options["away"]     == "B_HouseMode_Away"
        assert sel.options["home"]     == "B_HouseMode_In"
        assert sel.options["night"]    == "B_HouseMode_Night"
        assert sel.options["vacation"] == "B_HouseMode_Vacation"


class TestNothingDoubleConsumed:
    def test_no_function_appears_twice(self, reg):
        """Every B_* name should appear in exactly one device."""
        seen = set()
        for light in reg.lights:
            names = {light.func_on, light.func_off}
            if light.func_toggle:
                names.add(light.func_toggle)
            names.update(light.scenes)
            for n in names:
                assert n not in seen, f"{n} consumed twice"
                seen.add(n)
        for d in reg.dimmers:
            assert d.func_set not in seen
            seen.add(d.func_set)
        for r in reg.relays:
            assert r.func_on  not in seen
            assert r.func_off not in seen
            seen.update({r.func_on, r.func_off})
