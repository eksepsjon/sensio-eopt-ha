"""
Tests for the HA coordinator and dimmer entity logic.
Uses unittest.mock — no real HA instance or controller required.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call
from sensio_eopt.events import SensioEoptEvent, parse_event
from sensio_eopt.devices import SensioEoptDimmer, SensioEoptLight


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
