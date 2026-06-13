"""
Tests for the HA coordinator and dimmer entity logic.
Uses unittest.mock — no real HA instance or controller required.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call
from sensio_eopt.events import SensioEoptEvent, parse_event
from sensio_eopt.devices import SensioEoptDimmer, SensioEoptLight, SensioEoptRelay, SensioEoptThermostat


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_dimmer(name="B_D_Hall2etgHallTrappEntre_SET"):
    return SensioEoptDimmer(
        unique_id=name,
        name="Hall Dimmer",
        func_set=name,
        brightness_pct=0,
    )

def make_light(base="B_LightHallTrappEntre"):
    return SensioEoptLight(
        unique_id=base,
        name="Hall Light",
        func_on=base + "_ON",
        func_off=base + "_OFF",
        func_toggle=None,
        scenes=[],
        is_on=False,
    )

def rsn(line):
    evt = parse_event(line)
    assert evt is not None, f"Failed to parse: {line!r}"
    return evt


# ---------------------------------------------------------------------------
# State cache in coordinator
# ---------------------------------------------------------------------------

class TestStateCache:
    def test_cache_populated_on_event(self):
        """_on_event should update state_cache keyed by event name."""
        from custom_components.sensio_eopt.coordinator import SensioEoptCoordinator

        hass = MagicMock()
        hass.async_create_task = MagicMock()
        controller = MagicMock()
        controller.add_listener = MagicMock()
        controller.add_connection_listener = MagicMock()
        registry = MagicMock()

        with patch("custom_components.sensio_eopt.coordinator.async_dispatcher_send"):
            coord = SensioEoptCoordinator(hass, controller, registry)
            coord._on_event("RSN 49633 D_Hall2etgHallTrappEntre 21 1 69 69")

        assert "D_Hall2etgHallTrappEntre" in coord.state_cache
        assert coord.state_cache["D_Hall2etgHallTrappEntre"].int_value == 69

    def test_cache_ignores_unparseable(self):
        from custom_components.sensio_eopt.coordinator import SensioEoptCoordinator

        hass = MagicMock()
        controller = MagicMock()
        controller.add_listener = MagicMock()
        controller.add_connection_listener = MagicMock()
        registry = MagicMock()

        with patch("custom_components.sensio_eopt.coordinator.async_dispatcher_send"):
            coord = SensioEoptCoordinator(hass, controller, registry)
            coord._on_event("x_bm_st ACK_DIR seq=1")

        assert len(coord.state_cache) == 0

    def test_get_cached_state(self):
        from custom_components.sensio_eopt.coordinator import SensioEoptCoordinator

        hass = MagicMock()
        controller = MagicMock()
        controller.add_listener = MagicMock()
        controller.add_connection_listener = MagicMock()
        registry = MagicMock()

        with patch("custom_components.sensio_eopt.coordinator.async_dispatcher_send"):
            coord = SensioEoptCoordinator(hass, controller, registry)
            coord._on_event("RSN 49633 D_Hall2etgHallTrappEntre 21 1 50 50")

        assert coord.get_cached_state("D_Hall2etgHallTrappEntre").int_value == 50
        assert coord.get_cached_state("D_Unknown") is None


# ---------------------------------------------------------------------------
# SensioEoptDimmerEntity._handle_event — brightness tracking
# ---------------------------------------------------------------------------

class TestDimmerHandleEvent:
    def _make_entity(self, func_set="B_D_Hall2etgHallTrappEntre_SET"):
        """Build a SensioEoptDimmerEntity with mocked coordinator and HA internals."""
        from custom_components.sensio_eopt.light import SensioEoptDimmerEntity

        device = make_dimmer(func_set)
        coord = MagicMock()
        entity = SensioEoptDimmerEntity.__new__(SensioEoptDimmerEntity)
        entity.coordinator = coord
        entity.device = device
        entity.async_write_ha_state = MagicMock()
        return entity

    def test_d_event_updates_brightness_pct(self):
        entity = self._make_entity()
        evt = rsn("RSN 49633 D_Hall2etgHallTrappEntre 21 1 69 69")
        entity._handle_event(evt)
        assert entity.device.brightness_pct == 69
        entity.async_write_ha_state.assert_called_once()

    def test_d_event_for_wrong_dimmer_ignored(self):
        entity = self._make_entity("B_D_OtherDimmer_SET")
        evt = rsn("RSN 49633 D_Hall2etgHallTrappEntre 21 1 69 69")
        entity._handle_event(evt)
        assert entity.device.brightness_pct == 0  # unchanged
        entity.async_write_ha_state.assert_not_called()

    def test_trigger_event_refreshes_state(self):
        entity = self._make_entity()
        entity.device.brightness_pct = 50
        evt = rsn("RSN 59500 B_D_Hall2etgHallTrappEntre_SET 6 1 0 0")
        entity._handle_event(evt)
        entity.async_write_ha_state.assert_called_once()

    def test_is_on_true_when_brightness_nonzero(self):
        entity = self._make_entity()
        entity.device.brightness_pct = 75
        assert entity.is_on is True

    def test_is_on_false_when_brightness_zero(self):
        entity = self._make_entity()
        entity.device.brightness_pct = 0
        assert entity.is_on is False

    def test_brightness_converts_pct_to_ha_scale(self):
        entity = self._make_entity()
        entity.device.brightness_pct = 100
        assert entity.brightness == 255
        entity.device.brightness_pct = 50
        assert entity.brightness == round(50 * 255 / 100)
        entity.device.brightness_pct = 0
        assert entity.brightness == 0


# ---------------------------------------------------------------------------
# SensioEoptDimmerEntity.async_turn_on / async_turn_off — protocol calls
# ---------------------------------------------------------------------------

class TestDimmerTurnOnOff:
    def _make_entity(self):
        from custom_components.sensio_eopt.light import SensioEoptDimmerEntity
        device = make_dimmer()
        coord = MagicMock()
        coord.controller.dim = AsyncMock()
        entity = SensioEoptDimmerEntity.__new__(SensioEoptDimmerEntity)
        entity.coordinator = coord
        entity.device = device
        entity.async_write_ha_state = MagicMock()
        return entity

    @pytest.mark.asyncio
    async def test_turn_on_full(self):
        entity = self._make_entity()
        await entity.async_turn_on()
        entity.coordinator.controller.dim.assert_awaited_once_with(
            "B_D_Hall2etgHallTrappEntre_SET", 100
        )

    @pytest.mark.asyncio
    async def test_turn_on_with_ha_brightness(self):
        from homeassistant.components.light import ATTR_BRIGHTNESS
        entity = self._make_entity()
        await entity.async_turn_on(**{ATTR_BRIGHTNESS: 128})
        # 128 / 255 * 100 = 50.2 → round to 50
        entity.coordinator.controller.dim.assert_awaited_once_with(
            "B_D_Hall2etgHallTrappEntre_SET", 50
        )

    @pytest.mark.asyncio
    async def test_turn_on_clamps_to_1_minimum(self):
        from homeassistant.components.light import ATTR_BRIGHTNESS
        entity = self._make_entity()
        # HA brightness=1 should not send 0 (that would turn it off)
        await entity.async_turn_on(**{ATTR_BRIGHTNESS: 1})
        pct = entity.coordinator.controller.dim.call_args[0][1]
        assert pct >= 1

    @pytest.mark.asyncio
    async def test_turn_off(self):
        entity = self._make_entity()
        entity.device.brightness_pct = 75
        await entity.async_turn_off()
        entity.coordinator.controller.dim.assert_awaited_once_with(
            "B_D_Hall2etgHallTrappEntre_SET", 0
        )
        assert entity.device.brightness_pct == 0


# ---------------------------------------------------------------------------
# SensioEoptLightEntity — on/off and scenes
# ---------------------------------------------------------------------------

class TestLightEntity:
    def _make_entity(self, scenes=None):
        from custom_components.sensio_eopt.light import SensioEoptLightEntity
        device = make_light()
        if scenes:
            device.scenes = scenes
        coord = MagicMock()
        coord.controller.trigger = AsyncMock()
        entity = SensioEoptLightEntity.__new__(SensioEoptLightEntity)
        entity.coordinator = coord
        entity.device = device
        entity.async_write_ha_state = MagicMock()
        entity._attr_effect = None
        return entity

    @pytest.mark.asyncio
    async def test_turn_on(self):
        entity = self._make_entity()
        await entity.async_turn_on()
        entity.coordinator.controller.trigger.assert_awaited_once_with(
            "B_LightHallTrappEntre_ON"
        )
        assert entity.device.is_on is True

    @pytest.mark.asyncio
    async def test_turn_off(self):
        entity = self._make_entity()
        entity.device.is_on = True
        await entity.async_turn_off()
        entity.coordinator.controller.trigger.assert_awaited_once_with(
            "B_LightHallTrappEntre_OFF"
        )
        assert entity.device.is_on is False

    @pytest.mark.asyncio
    async def test_turn_on_scene(self):
        scenes = ["B_LightHallTrappEntre_Sc1", "B_LightHallTrappEntre_Sc2"]
        entity = self._make_entity(scenes=scenes)
        await entity.async_turn_on(effect="Scene 2")
        entity.coordinator.controller.trigger.assert_awaited_once_with(
            "B_LightHallTrappEntre_Sc2"
        )
        assert entity.device.is_on is True

    def test_handle_on_event(self):
        entity = self._make_entity()
        evt = rsn("RSN 59500 B_LightHallTrappEntre_ON 6 1 0 0")
        entity._handle_event(evt)
        assert entity.device.is_on is True

    def test_handle_off_event(self):
        entity = self._make_entity()
        entity.device.is_on = True
        evt = rsn("RSN 59501 B_LightHallTrappEntre_OFF 6 1 0 0")
        entity._handle_event(evt)
        assert entity.device.is_on is False


# ---------------------------------------------------------------------------
# SensioEoptSwitchEntity._handle_event — relay state tracking
# ---------------------------------------------------------------------------

def make_relay(base="B_R_UtelysUtelys"):
    return SensioEoptRelay(
        unique_id=base,
        name="Utelys",
        func_on=base + "_ON",
        func_off=base + "_OFF",
        is_on=False,
    )


class TestSwitchHandleEvent:
    def _make_entity(self):
        from custom_components.sensio_eopt.switch import SensioEoptSwitchEntity
        device = make_relay()
        coord = MagicMock()
        entity = SensioEoptSwitchEntity.__new__(SensioEoptSwitchEntity)
        entity.coordinator = coord
        entity.device = device
        entity.async_write_ha_state = MagicMock()
        return entity

    def test_trigger_on_updates_state(self):
        entity = self._make_entity()
        evt = rsn("RSN 1 B_R_UtelysUtelys_ON 6 1 0 0")
        entity._handle_event(evt)
        assert entity.device.is_on is True
        entity.async_write_ha_state.assert_called_once()

    def test_trigger_off_updates_state(self):
        entity = self._make_entity()
        entity.device.is_on = True
        evt = rsn("RSN 2 B_R_UtelysUtelys_OFF 6 1 0 0")
        entity._handle_event(evt)
        assert entity.device.is_on is False

    def test_device_value_on_updates_state(self):
        """D_R_* type 21 event with value 100 → relay on."""
        entity = self._make_entity()
        evt = rsn("RSN 3 D_R_UtelysUtelys 21 1 100 100")
        entity._handle_event(evt)
        assert entity.device.is_on is True
        entity.async_write_ha_state.assert_called_once()

    def test_device_value_off_updates_state(self):
        """D_R_* type 21 event with value 0 → relay off."""
        entity = self._make_entity()
        entity.device.is_on = True
        evt = rsn("RSN 4 D_R_UtelysUtelys 21 1 0 0")
        entity._handle_event(evt)
        assert entity.device.is_on is False

    def test_device_value_wrong_relay_ignored(self):
        entity = self._make_entity()
        evt = rsn("RSN 5 D_R_OtherRelay 21 1 100 100")
        entity._handle_event(evt)
        assert entity.device.is_on is False
        entity.async_write_ha_state.assert_not_called()


# ---------------------------------------------------------------------------
# SensioEoptDimmerEntity._handle_event — M_D_*_Val type 23 register
# ---------------------------------------------------------------------------

class TestDimmerHandleRegisterEvent:
    def _make_entity(self, func_set="B_D_Hall2etgHallTrappEntre_SET"):
        from custom_components.sensio_eopt.light import SensioEoptDimmerEntity
        device = make_dimmer(func_set)
        coord = MagicMock()
        entity = SensioEoptDimmerEntity.__new__(SensioEoptDimmerEntity)
        entity.coordinator = coord
        entity.device = device
        entity.async_write_ha_state = MagicMock()
        return entity

    def test_m_register_updates_brightness(self):
        """M_D_*_Val type 23 float register updates brightness_pct."""
        entity = self._make_entity()
        evt = rsn("RSN 49751 M_D_Hall2etgHallTrappEntre_Val 23 1 0 69.000")
        entity._handle_event(evt)
        assert entity.device.brightness_pct == 69
        entity.async_write_ha_state.assert_called_once()

    def test_m_register_wrong_dimmer_ignored(self):
        entity = self._make_entity("B_D_OtherDimmer_SET")
        evt = rsn("RSN 49751 M_D_Hall2etgHallTrappEntre_Val 23 1 0 69.000")
        entity._handle_event(evt)
        assert entity.device.brightness_pct == 0
        entity.async_write_ha_state.assert_not_called()

    def test_m_register_clamps_to_100(self):
        entity = self._make_entity()
        evt = rsn("RSN 49751 M_D_Hall2etgHallTrappEntre_Val 23 1 0 110.000")
        entity._handle_event(evt)
        assert entity.device.brightness_pct == 100

    def test_m_register_zero(self):
        entity = self._make_entity()
        entity.device.brightness_pct = 50
        evt = rsn("RSN 49751 M_D_Hall2etgHallTrappEntre_Val 23 1 0 0.000")
        entity._handle_event(evt)
        assert entity.device.brightness_pct == 0


# ---------------------------------------------------------------------------
# SensioEoptClimateEntity._handle_event — thermostat state updates
# ---------------------------------------------------------------------------

def make_thermostat(prefix="B_Vaskerom0533"):
    return SensioEoptThermostat(
        unique_id="Vaskerom0533",
        name="Vaskerom",
        zone_key="vaskerom",
        func_dec=prefix + "_Temp_Dec",
        func_inc=prefix + "_Temp_Inc",
        func_set=prefix + "_Set",
        preset_scenes=[],
        target_temperature=21.0,
    )


class TestClimateHandleEvent:
    def _make_entity(self, mode_selector=None):
        from custom_components.sensio_eopt.climate import SensioEoptClimateEntity, HVACMode
        device = make_thermostat()
        coord = MagicMock()
        entity = SensioEoptClimateEntity.__new__(SensioEoptClimateEntity)
        entity.coordinator = coord
        entity.device = device
        entity._mode_selector = mode_selector
        entity._attr_hvac_mode = HVACMode.HEAT
        entity._attr_min_temp = 5.0
        entity._attr_max_temp = 40.0
        entity._attr_target_temperature = device.target_temperature
        entity.async_write_ha_state = MagicMock()
        return entity

    def test_register_event_updates_temperature(self):
        """M_Vaskerom0533* type 23 float register updates target_temperature."""
        entity = self._make_entity()
        evt = rsn("RSN 100 M_Vaskerom0533_Temp 23 1 0 215.000")
        entity._handle_event(evt)
        assert abs(entity.device.target_temperature - 21.5) < 0.01
        assert abs(entity._attr_target_temperature - 21.5) < 0.01
        entity.async_write_ha_state.assert_called_once()

    def test_register_event_out_of_range_ignored(self):
        """Values outside 5-40°C after scaling are ignored."""
        entity = self._make_entity()
        evt = rsn("RSN 100 M_Vaskerom0533_Temp 23 1 0 500.000")
        entity._handle_event(evt)
        assert entity.device.target_temperature == 21.0  # unchanged
        entity.async_write_ha_state.assert_not_called()

    def test_register_event_wrong_zone_ignored(self):
        entity = self._make_entity()
        evt = rsn("RSN 100 M_OtherZone_Temp 23 1 0 215.000")
        entity._handle_event(evt)
        assert entity.device.target_temperature == 21.0
        entity.async_write_ha_state.assert_not_called()

    def test_inc_trigger_steps_up(self):
        entity = self._make_entity()
        entity.device.target_temperature = 21.0
        evt = rsn("RSN 101 B_Vaskerom0533_Temp_Inc 6 1 0 0")
        entity._handle_event(evt)
        assert abs(entity.device.target_temperature - 21.5) < 0.01
        entity.async_write_ha_state.assert_called_once()

    def test_dec_trigger_steps_down(self):
        entity = self._make_entity()
        entity.device.target_temperature = 21.0
        evt = rsn("RSN 102 B_Vaskerom0533_Temp_Dec 6 1 0 0")
        entity._handle_event(evt)
        assert abs(entity.device.target_temperature - 20.5) < 0.01

    def test_inc_clamps_at_max(self):
        entity = self._make_entity()
        entity.device.target_temperature = 40.0
        evt = rsn("RSN 101 B_Vaskerom0533_Temp_Inc 6 1 0 0")
        entity._handle_event(evt)
        assert entity.device.target_temperature == 40.0

    def test_dec_clamps_at_min(self):
        entity = self._make_entity()
        entity.device.target_temperature = 5.0
        evt = rsn("RSN 102 B_Vaskerom0533_Temp_Dec 6 1 0 0")
        entity._handle_event(evt)
        assert entity.device.target_temperature == 5.0

    def test_mode_trigger_updates_preset(self):
        """Mode function trigger updates mode_selector and hvac_mode."""
        from sensio_eopt.devices import SensioEoptModeSelector
        from custom_components.sensio_eopt.climate import HVACMode
        mode_sel = SensioEoptModeSelector(
            unique_id="B_VaskeromMode",
            name="Vaskerom Mode",
            zone_key="vaskerom",
            options={"home": "B_VaskeromMode_In", "away": "B_VaskeromMode_Away"},
            current_option="home",
        )
        entity = self._make_entity(mode_selector=mode_sel)
        evt = rsn("RSN 103 B_VaskeromMode_Away 6 1 0 0")
        entity._handle_event(evt)
        assert mode_sel.current_option == "away"
        assert entity._attr_hvac_mode == HVACMode.OFF
        entity.async_write_ha_state.assert_called_once()

    def test_mode_trigger_home_sets_heat(self):
        from sensio_eopt.devices import SensioEoptModeSelector
        from custom_components.sensio_eopt.climate import HVACMode
        mode_sel = SensioEoptModeSelector(
            unique_id="B_VaskeromMode",
            name="Vaskerom Mode",
            zone_key="vaskerom",
            options={"home": "B_VaskeromMode_In", "away": "B_VaskeromMode_Away"},
            current_option="away",
        )
        entity = self._make_entity(mode_selector=mode_sel)
        entity._attr_hvac_mode = HVACMode.OFF
        evt = rsn("RSN 104 B_VaskeromMode_In 6 1 0 0")
        entity._handle_event(evt)
        assert mode_sel.current_option == "home"
        assert entity._attr_hvac_mode == HVACMode.HEAT


# ---------------------------------------------------------------------------
# Optimistic state rollback on command failure
# ---------------------------------------------------------------------------

class TestLightRollbackOnError:
    def _make_entity(self, scenes=None):
        from custom_components.sensio_eopt.light import SensioEoptLightEntity
        device = make_light()
        if scenes:
            device.scenes = scenes
        coord = MagicMock()
        coord.controller.trigger = AsyncMock(side_effect=RuntimeError("disconnected"))
        entity = SensioEoptLightEntity.__new__(SensioEoptLightEntity)
        entity.coordinator = coord
        entity.device = device
        entity.async_write_ha_state = MagicMock()
        entity._attr_effect = None
        entity._attr_name = "Hall Light"
        return entity

    @pytest.mark.asyncio
    async def test_turn_on_rolls_back(self):
        entity = self._make_entity()
        entity.device.is_on = False
        await entity.async_turn_on()
        assert entity.device.is_on is False

    @pytest.mark.asyncio
    async def test_turn_off_rolls_back(self):
        entity = self._make_entity()
        entity.device.is_on = True
        await entity.async_turn_off()
        assert entity.device.is_on is True

    @pytest.mark.asyncio
    async def test_scene_rolls_back(self):
        scenes = ["B_LightHallTrappEntre_Sc1", "B_LightHallTrappEntre_Sc2"]
        entity = self._make_entity(scenes=scenes)
        entity.device.is_on = False
        entity._attr_effect = None
        await entity.async_turn_on(effect="Scene 1")
        assert entity.device.is_on is False
        assert entity._attr_effect is None

    @pytest.mark.asyncio
    async def test_malformed_effect_falls_through_to_func_on(self):
        """Effect string with no trailing number falls back to plain turn_on call."""
        entity = self._make_entity()
        entity.coordinator.controller.trigger = AsyncMock()
        entity.device.is_on = False
        await entity.async_turn_on(effect="Scene")
        entity.coordinator.controller.trigger.assert_awaited_once_with(
            "B_LightHallTrappEntre_ON"
        )


class TestDimmerRollbackOnError:
    def _make_entity(self):
        from custom_components.sensio_eopt.light import SensioEoptDimmerEntity
        device = make_dimmer()
        coord = MagicMock()
        coord.controller.dim = AsyncMock(side_effect=RuntimeError("timeout"))
        entity = SensioEoptDimmerEntity.__new__(SensioEoptDimmerEntity)
        entity.coordinator = coord
        entity.device = device
        entity.async_write_ha_state = MagicMock()
        entity._attr_name = "Hall Dimmer"
        return entity

    @pytest.mark.asyncio
    async def test_turn_on_rolls_back(self):
        entity = self._make_entity()
        entity.device.brightness_pct = 50
        await entity.async_turn_on()
        assert entity.device.brightness_pct == 50

    @pytest.mark.asyncio
    async def test_turn_off_rolls_back(self):
        entity = self._make_entity()
        entity.device.brightness_pct = 75
        await entity.async_turn_off()
        assert entity.device.brightness_pct == 75


class TestSwitchRollbackOnError:
    def _make_entity(self):
        from custom_components.sensio_eopt.switch import SensioEoptSwitchEntity
        device = make_relay()
        coord = MagicMock()
        coord.controller.trigger = AsyncMock(side_effect=RuntimeError("disconnected"))
        entity = SensioEoptSwitchEntity.__new__(SensioEoptSwitchEntity)
        entity.coordinator = coord
        entity.device = device
        entity.async_write_ha_state = MagicMock()
        entity._attr_name = "Utelys"
        return entity

    @pytest.mark.asyncio
    async def test_turn_on_rolls_back(self):
        entity = self._make_entity()
        entity.device.is_on = False
        await entity.async_turn_on()
        assert entity.device.is_on is False

    @pytest.mark.asyncio
    async def test_turn_off_rolls_back(self):
        entity = self._make_entity()
        entity.device.is_on = True
        await entity.async_turn_off()
        assert entity.device.is_on is True


class TestClimateRollbackOnError:
    def _make_entity(self):
        from custom_components.sensio_eopt.climate import SensioEoptClimateEntity, HVACMode
        device = make_thermostat()
        coord = MagicMock()
        coord.controller.trigger = AsyncMock(side_effect=RuntimeError("disconnected"))
        entity = SensioEoptClimateEntity.__new__(SensioEoptClimateEntity)
        entity.coordinator = coord
        entity.device = device
        entity._mode_selector = None
        entity._attr_hvac_mode = HVACMode.HEAT
        entity._attr_min_temp = 5.0
        entity._attr_max_temp = 40.0
        entity._attr_target_temperature = device.target_temperature
        entity.async_write_ha_state = MagicMock()
        entity._attr_name = "Vaskerom"
        return entity

    @pytest.mark.asyncio
    async def test_set_temperature_does_not_mutate_on_failure(self):
        entity = self._make_entity()
        entity.device.target_temperature = 21.0
        entity._attr_target_temperature = 21.0
        await entity.async_set_temperature(temperature=22.5)
        assert entity.device.target_temperature == 21.0
        assert entity._attr_target_temperature == 21.0
