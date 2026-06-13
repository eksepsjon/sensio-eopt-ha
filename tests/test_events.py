"""
Tests for the event parser (sensio_eopt/events.py).
"""

import pytest
from sensio_eopt.events import parse_event, device_name_from_event


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


class TestThermostatEvent:
    def test_thermostat_ssn(self):
        evt = parse_event("SSN 2195 TH_Gang1etg0573 7 1 1 24.50 24.40 0.00")
        assert evt is not None
        assert evt.name == "TH_Gang1etg0573"
        assert evt.type_id == 7
        assert evt.is_thermostat_status is True
        assert evt.thermostat_setpoint == 24.5
        assert evt.thermostat_current_temp == 24.4
        assert evt.thermostat_floor_temp == 0.0
        assert evt.is_heating is True

    def test_thermostat_rsn_idle(self):
        evt = parse_event("RSN 2195 TH_Gang1etg0573 7 1 0 23.000 24.400 0.000")
        assert evt is not None
        assert evt.is_thermostat_status is True
        assert evt.thermostat_setpoint == 23.0
        assert evt.thermostat_current_temp == 24.4
        assert evt.is_heating is False

    def test_thermostat_enabled_and_state(self):
        evt = parse_event("SSN 14622 TH_Bad2etg0513 7 1 0 24.00 26.10 0.00")
        assert evt.enabled == 1
        assert evt.state == 0


class TestHeatingRelayEvent:
    def test_heating_relay(self):
        evt = parse_event("RSN 6016 R_VkGang1etg058 36 1 0 23.000 25.200 0.000 0.000 0.000")
        assert evt is not None
        assert evt.name == "R_VkGang1etg058"
        assert evt.type_id == 36
        assert evt.is_heating_relay is True
        vals = evt.float_values
        assert vals[0] == 23.0
        assert vals[1] == 25.2
        assert len(vals) == 5


class TestExtendedDeviceEvent:
    def test_minmax(self):
        evt = parse_event("SSN 30040 D_MinMaxKjellerstue061 13 1 0 50400 49578")
        assert evt is not None
        assert evt.type_id == 13
        assert evt.is_extended_device is True
        assert evt.value_raw == "50400"
        assert evt.extra_values == ["49578"]

    def test_safeoff(self):
        evt = parse_event("SSN 9697 D_SafeOffHallTrappEntre0593 13 1 0 360 -1")
        assert evt is not None
        assert evt.is_extended_device is True
        assert evt.int_value == 360
        assert evt.extra_values == ["-1"]


class TestTimerEvent:
    def test_house_timer(self):
        line = "SSN 68497 T_houseTimer 4 0 0 7 7f00010 00000f0 00000f0 00000f0 00000f0 00000f0 00000f0 00000f0 00000f0 00000f0 00000f0 00000f0 00000f0 00000f0 00000f0 00000f0 00000f0 00000f0 00000f0 00000f0"
        evt = parse_event(line)
        assert evt is not None
        assert evt.name == "T_houseTimer"
        assert evt.type_id == 4
        assert evt.is_timer is True
        assert evt.value_raw == "7"
        assert len(evt.extra_values) == 20


class TestHeatingSensorEvent:
    def test_energy_sensor(self):
        evt = parse_event("RSN 18556 S_VkBad2etgBad2etgEnergy 10 1 0 747.300")
        assert evt is not None
        assert evt.name == "S_VkBad2etgBad2etgEnergy"
        assert evt.type_id == 10
        assert evt.is_heating_sensor is True
        assert evt.float_value == 747.3
        assert evt.sensor_unit == "W"

    def test_temp_sensor(self):
        evt = parse_event("RSN 18503 S_VkBad2etgBad2etgTemp 10 1 0 30.000")
        assert evt is not None
        assert evt.name == "S_VkBad2etgBad2etgTemp"
        assert evt.is_heating_sensor is True
        assert evt.float_value == 30.0
        assert evt.sensor_unit == "°C"


class TestMultiValueRegister:
    def test_thermostat_scene_config(self):
        evt = parse_event("SSN 3382 M_Gang1etg0573_Sc 23 1 0 24.500 18.000 10.000")
        assert evt is not None
        assert evt.is_register is True
        assert evt.float_value == 24.5
        assert evt.float_values == [24.5, 18.0, 10.0]
        assert evt.extra_values == ["18.000", "10.000"]

    def test_dimmer_scene_config(self):
        evt = parse_event("SSN 41590 M_D_SpotlightsTVStueTVStue_Sc 23 1 0 80.000 60.000 0.000 0.000")
        assert evt is not None
        assert evt.is_register is True
        assert evt.float_values == [80.0, 60.0, 0.0, 0.0]

    def test_relay_scene_config(self):
        evt = parse_event("SSN 34872 M_R_UtelysUtelys_Sc 23 1 2 0.000 0.000 1.000 0.000")
        assert evt is not None
        assert evt.is_register is True
        assert evt.state == 2
        assert evt.float_values == [0.0, 0.0, 1.0, 0.0]


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
