"""Tests the schedule_state sensor."""
from datetime import timedelta, datetime, timezone
from unittest.mock import patch

import pytest
import voluptuous as vol

from typing import Any
from unittest.mock import patch

from homeassistant import setup
from homeassistant.components.sensor import DOMAIN
from homeassistant.core import HomeAssistant

import logging

_LOGGER = logging.getLogger(__name__)

# FUNCTION_PATH = "homeassistant.util.dt.utcnow"
FUNCTION_PATH = "custom_components.schedule_state.sensor.dt_now"


async def setup_test_entities(hass: HomeAssistant, config_dict: dict[str, Any]) -> None:
    """Set up a test schedule_state sensor entity."""
    assert await setup.async_setup_component(
        hass,
        DOMAIN,
        {
            DOMAIN: [
                {
                    "platform": "schedule_state",
                },
                {**config_dict},
            ]
        },
    )
    await hass.async_block_till_done()


async def test_setup(hass: HomeAssistant) -> None:
    """Test sensor setup."""
    now = datetime(2021, 11, 20, 4, 0, tzinfo=timezone.utc)

    with patch(
        FUNCTION_PATH,
        return_value=now,
    ) as p:
        await setup_test_entities(
            hass,
            {
                "platform": "schedule_state",
                "name": "Sleep Schedule",
                "refresh": "1:00:00",
                "events": [
                    {
                        "end": "5:30",
                        "state": "asleep",
                    },
                    {
                        "start": "5:30",
                        "end": "22:30",
                        "state": "awake",
                    },
                    {
                        "start": "22:30",
                        "state": "asleep",
                    },
                ],
            },
        )

        assert p.called
        assert p.return_value == now

    # get the "Sleep Schedule" sensor
    sensor = [e for e in hass.data["sensor"].entities][-1]

    now += timedelta(minutes=10)
    with patch(
        FUNCTION_PATH,
        return_value=now,
    ) as p:
        await sensor.async_update_ha_state(force_refresh=True)

        entity_state = hass.states.get("sensor.sleep_schedule")
        assert entity_state
        assert p.called
        assert p.return_value == now
        assert entity_state.attributes["friendly_name"] == "Sleep Schedule"
        assert entity_state.state == "asleep"

    now += timedelta(hours=16)
    with patch(
        FUNCTION_PATH,
        return_value=now,
    ) as p:
        await sensor.async_update_ha_state(force_refresh=True)

        entity_state = hass.states.get("sensor.sleep_schedule")
        assert p.called
        assert p.return_value == now
        assert entity_state.state == "awake"


async def test_some_other_test(hass: HomeAssistant) -> None:
    assert 1 == 1
