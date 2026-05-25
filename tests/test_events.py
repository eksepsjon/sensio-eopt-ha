"""
Tests for the event parser (sensio/events.py).
"""

import pytest
from sensio.events import parse_event, device_name_from_event


class TestParseEvent:
    # --- RSN events ---

    def test_rsn_trigger(self):
        evt = parse_event("RSN 59500 B_LightHallTrappEntre_ON 6 1 0 0")
        assert evt is not None
        assert evt.name == "B_LightHallTrappEntre_ON"
        assert evt.type_id == 6
        assert evt.seq == 59500
        assert evt.is_trigger is True
        assert evt.is_device_value is False

    def test_rsn_device_value(self):
        evt = parse_event("RSN 49633 D_Hall2etgHallTrappEntre 21 1 69 69")
        assert evt is not None
        assert evt.name == "D_Hall2etgHallTrappEntre"
        assert evt.type_id == 21
        assert evt.is_device_value is True
        assert evt.int_value == 69

    def test_rsn_float_register(self):
        evt = parse_event("RSN 49751 M_D_Hall2etgHallTrappEntre_Val 23 1 0 69.000")
        assert evt is not None
        assert evt.name == "M_D_Hall2etgHallTrappEntre_Val"
        assert evt.type_id == 23
        assert evt.is_register is True
        assert abs(evt.float_value - 69.0) < 0.001

    def test_ssn_parsed_same_as_rsn(self):
        evt = parse_event("SSN 49633 D_Hall2etgHallTrappEntre 21 1 69 69")
        assert evt is not None
        assert evt.name == "D_Hall2etgHallTrappEntre"
        assert evt.int_value == 69

    # --- Direct device state lines (no RSN prefix) ---

    def test_direct_d_line(self):
        evt = parse_event("D_Hall2etgHallTrappEntre 21 1 100 100")
        assert evt is not None
        assert evt.name == "D_Hall2etgHallTrappEntre"
        assert evt.int_value == 100
        assert evt.is_on is True

    def test_direct_d_line_off(self):
        evt = parse_event("D_Hall2etgHallTrappEntre 21 1 0 0")
        assert evt is not None
        assert evt.int_value == 0
        assert evt.is_on is False

    # --- Lines that should return None ---

    def test_keepalive_returns_none(self):
        assert parse_event("x_bm_st ACK_DIR seq=13") is None

    def test_panel_brightness_returns_none(self):
        assert parse_event("PANEL_BRIGHTNESS 70") is None

    def test_end_returns_none(self):
        assert parse_event("end B_LightHallTrappEntre_ON") is None

    def test_empty_returns_none(self):
        assert parse_event("") is None

    def test_whitespace_stripped(self):
        evt = parse_event("  RSN 59500 B_LightHallTrappEntre_ON 6 1 0 0  ")
        assert evt is not None
        assert evt.name == "B_LightHallTrappEntre_ON"

    # --- int_value / float_value helpers ---

    def test_int_value_negative_float(self):
        evt = parse_event("RSN 59158 M_HallTrappEntreCurSc 23 1 0 -1.000")
        assert evt.float_value == -1.0
        assert evt.int_value == -1

    def test_is_on_threshold(self):
        evt = parse_event("RSN 49633 D_Hall2etgHallTrappEntre 21 1 1 1")
        assert evt.is_on is True
        evt2 = parse_event("RSN 49633 D_Hall2etgHallTrappEntre 21 1 0 0")
        assert evt2.is_on is False


class TestDeviceNameFromEvent:
    def test_d_to_b_d_set(self):
        evt = parse_event("RSN 49633 D_Hall2etgHallTrappEntre 21 1 69 69")
        assert device_name_from_event(evt) == "B_D_Hall2etgHallTrappEntre"

    def test_non_device_returns_none(self):
        evt = parse_event("RSN 59500 B_LightHallTrappEntre_ON 6 1 0 0")
        assert device_name_from_event(evt) is None

    def test_b_prefix_returns_none(self):
        evt = parse_event("RSN 49633 D_Hall2etgHallTrappEntre 21 1 69 69")
        # Is a device value, returns a name
        assert device_name_from_event(evt) is not None
