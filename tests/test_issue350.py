import logging
from unittest.mock import patch

from homeassistant import setup
from homeassistant.core import HomeAssistant
import yaml

from .test_schedule import TIME_FUNCTION_PATH, check_state, make_testtime

_LOGGER = logging.getLogger(__name__)


async def test_issue350(hass: HomeAssistant):
    with open("tests/../config/issues/issue350.yaml") as f:
        config = yaml.safe_load(f)

    now = make_testtime(4, 0)
    with patch(TIME_FUNCTION_PATH, return_value=now):
        for component in ("input_number", "input_boolean", "binary_sensor", "sensor"):
            ret = await setup.async_setup_component(
                hass,
                component,
                {component: config[component]},
            )
            await hass.async_block_till_done()
            assert ret, f"Setup failed ({component})"

        sensors = [e for e in hass.data["sensor"].entities]
        sensor = sensors[0]

        check_state(hass, "sensor.issue350", "18.0")

        assert sensor._attr_icon == "mdi:weather-night", "Icon was wrong"
