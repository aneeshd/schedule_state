import logging

from homeassistant.core import HomeAssistant
import yaml

from .test_schedule import check_state, make_testtime, set_override, setup_test_sensor

_LOGGER = logging.getLogger(__name__)


async def test_issue356(hass: HomeAssistant):
    with open("tests/../config/issues/issue356.yaml") as f:
        config = yaml.safe_load(f)

    await setup_test_sensor(
        hass,
        config["sensor"][0],
    )

    sensor = [e for e in hass.data["sensor"].entities][-1]
    _LOGGER.error(sensor.data.events)

    now = make_testtime(4, 0)
    await set_override(
        hass,
        "sensor.base_heating_schedule",
        now,
        "custom",
        duration=600,
        icon="mdi:home-thermometer",
        extra_attributes=dict(override_temperature=25, icon_color="blue"),
    )

    check_state(hass, "sensor.base_heating_schedule", "custom")

    assert sensor._attributes["icon_color"] == "blue"
    assert str(sensor._attributes["override_temperature"]) == "25"
