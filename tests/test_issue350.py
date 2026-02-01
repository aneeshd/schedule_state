import logging

from homeassistant.core import HomeAssistant

from .test_schedule import check_state, load_config

_LOGGER = logging.getLogger(__name__)


async def test_issue350(hass: HomeAssistant):
    await load_config(hass, "tests/../config/issues/issue350.yaml")

    sensors = [e for e in hass.data["sensor"].entities]
    sensor = sensors[0]

    check_state(hass, "sensor.issue350", "18.0")

    assert sensor._attr_icon == "mdi:weather-night", "Icon was wrong"
