from datetime import timedelta
from unittest.mock import patch

from homeassistant import setup
from homeassistant.core import HomeAssistant
import yaml

from custom_components.schedule_state.sensor import (
    Override,
    ScheduleStateExtraStoredData,
)

from .test_schedule import (
    TIME_FUNCTION_PATH,
    check_state_at_time,
    make_testtime,
    setup_test_entities,
)


async def test_issue188(hass: HomeAssistant):
    with open("tests/issue188.yaml") as f:
        config = yaml.safe_load(f)

    # create zone "home" -- https://www.home-assistant.io/integrations/zone/
    await setup.async_setup_component(
        hass,
        "zone",
        {
            "zone": {
                "name": "Home",
                "latitude": 32.8773367,
                "longitude": -117.2494053,
                "radius": 250,
                "icon": "mdi:home",
            }
        },
    )

    # create input_boolean "mode_ete" -- https://www.home-assistant.io/integrations/input_boolean/
    await setup.async_setup_component(
        hass,
        "input_boolean",
        {
            "input_boolean": {
                "mode_ete": {},
            }
        },
    )

    start = make_testtime(4, 0)
    end = make_testtime(14, 0)
    stored_overrides = ScheduleStateExtraStoredData(
        [
            Override(
                "my-stored-id",
                "some-state",
                start.time(),
                end.time(),
                end + timedelta(seconds=3450),
                None,
                {},
            ),
            {
                "id": None,
                "state": "on",
                "start": "19:05:00",
                "end": "20:05:00",
                "expires": "2023-12-19T20:05:30-05:00",
                "icon": None,
            },
        ],
    )
    with patch(
        "homeassistant.helpers.restore_state.RestoreEntity.async_get_last_extra_data",
        return_value=stored_overrides,
    ):
        await setup_test_entities(
            hass,
            config[0],
        )

        sensor = [e for e in hass.data["sensor"].entities][-1]

    now = make_testtime(19, 22)
    await check_state_at_time(hass, sensor, now, "on")

    now = make_testtime(8, 0)
    with patch(TIME_FUNCTION_PATH, return_value=now) as p:
        await sensor.async_update_ha_state(force_refresh=True)

    now = make_testtime(16, 0)
    with patch(TIME_FUNCTION_PATH, return_value=now) as p:
        await hass.services.async_call(
            "input_boolean",
            "toggle",
            blocking=True,
            target={
                "entity_id": "input_boolean.mode_ete",
            },
        )
        await hass.async_block_till_done()
