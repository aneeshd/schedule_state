from datetime import time
import math
from unittest.mock import patch

from homeassistant import setup
from homeassistant.core import HomeAssistant
import yaml

from .test_schedule import TIME_FUNCTION_PATH, make_testtime, setup_test_entities


async def test_issue187(hass: HomeAssistant):
    with open("tests/issue187.yaml") as f:
        config = yaml.safe_load(f)

    # create input_boolean "wohnzimmer_fenster" in lieu of the binary_sensor from the bug report
    await setup.async_setup_component(
        hass,
        "input_boolean",
        {
            "input_boolean": {
                "wohnzimmer_fenster": {},
            }
        },
    )

    now = make_testtime(4, 0)
    with patch(TIME_FUNCTION_PATH, return_value=now) as p:
        await setup_test_entities(
            hass,
            config[0],
        )

        assert p.called, "Time patch was not applied"
        assert p.return_value == now, "Time patch was wrong"

        sensor = [e for e in hass.data["sensor"].entities][-1]

    now = make_testtime(13, 0)
    with patch(TIME_FUNCTION_PATH, return_value=now) as p:
        await sensor.async_update_ha_state(force_refresh=True)
        assert math.isclose(
            float(sensor._state), 15
        ), f"expected stat=15 vs actual={sensor._state}"
        assert (
            sensor._attributes["start"] == make_testtime(10, 0).time()
        ), f'expected start=10:00 vs actual {sensor._attributes["start"]}'
        assert (
            sensor._attributes["end"] == make_testtime(15, 0).time()
        ), f'expected end=15:00 vs actual {sensor._attributes["end"]}'
        assert math.isclose(
            float(sensor._attributes["next_state"]), 20
        ), f"expected next_state=20 vs actual={sensor._attributes['next_state']}"

    # flip wohnzimmer_fenster" to on - this overrides everything
    now = make_testtime(13, 1)
    with patch(TIME_FUNCTION_PATH, return_value=now) as p:
        await hass.services.async_call(
            "input_boolean",
            "toggle",
            blocking=True,
            target={
                "entity_id": "input_boolean.wohnzimmer_fenster",
            },
        )
        await hass.async_block_till_done()

        assert math.isclose(
            float(sensor._state), 18
        ), f"expected stat=18 vs actual={sensor._state}"
        assert (
            sensor._attributes["start"] == make_testtime(0, 0).time()
        ), f'expected start=0:00 vs actual {sensor._attributes["start"]}'
        assert (
            sensor._attributes["end"] == time.max
        ), f'expected end=23:59 vs actual {sensor._attributes["end"]}'
        assert math.isclose(
            float(sensor._attributes["next_state"]), 18
        ), f"expected next_state=18 vs actual={sensor._attributes['next_state']}"
        assert sensor._attributes["window"] == "open"
