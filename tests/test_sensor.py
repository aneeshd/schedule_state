"""Tests the schedule_state sensor."""
from datetime import timedelta, datetime, timezone, date
from unittest.mock import patch

import yaml

from typing import Any

from homeassistant import setup

from homeassistant.components.sensor import DOMAIN as SENSOR
from homeassistant.core import HomeAssistant
from homeassistant.components import input_boolean

from custom_components.schedule_state.const import *

import logging

_LOGGER = logging.getLogger(__name__)

TIME_FUNCTION_PATH = "custom_components.schedule_state.sensor.dt_now"

DATE_FUNCTION_PATH = "homeassistant.components.workday.binary_sensor.get_date"


async def setup_test_entities(hass: HomeAssistant, config_dict: dict[str, Any]) -> None:
    """Set up a test schedule_state sensor entity."""
    ret = await setup.async_setup_component(
        hass,
        SENSOR,
        {
            SENSOR: [
                {**config_dict},
            ]
        },
    )
    await hass.async_block_till_done()
    assert ret


async def test_blank_setup(hass: HomeAssistant) -> None:
    await setup_test_entities(hass, {"platform": DOMAIN})


async def test_basic_setup(hass: HomeAssistant) -> None:
    """Test basic schedule_state setup."""
    now = make_testtime(4, 0)

    with patch(TIME_FUNCTION_PATH, return_value=now) as p:
        await setup_test_entities(
            hass,
            {
                "platform": DOMAIN,
                CONF_NAME: "Sleep Schedule",
                CONF_REFRESH: "1:00:00",
                CONF_EVENTS: [
                    {
                        CONF_END: "5:30",
                        CONF_STATE: "asleep",
                    },
                    {
                        CONF_START: "5:30",
                        CONF_END: "22:30",
                        CONF_STATE: "awake",
                    },
                    {
                        CONF_START: "22:30",
                        CONF_STATE: "asleep",
                    },
                ],
            },
        )

        assert p.called
        assert p.return_value == now

    # get the "Sleep Schedule" sensor
    sensor = [e for e in hass.data["sensor"].entities][-1]

    now += timedelta(minutes=10)  # 4:10
    with patch(TIME_FUNCTION_PATH, return_value=now) as p:
        await sensor.async_update_ha_state(force_refresh=True)

        entity_state = check_state(hass, "sensor.sleep_schedule", "asleep", p, now)
        assert entity_state.attributes["friendly_name"] == "Sleep Schedule"

    now += timedelta(hours=16)  # 20:10
    await check_state_at_time(hass, sensor, now, "awake")

    # add an override
    now += timedelta(minutes=10)  # 20:20
    await set_override(hass, "sensor.sleep_schedule", now, "drowsy", duration=15)

    # check that override state is en effect
    now += timedelta(minutes=10)  # 20:30
    await check_state_at_time(hass, sensor, now, "drowsy")

    # check that override has expired
    now += timedelta(minutes=10)  # 20:40
    await check_state_at_time(hass, sensor, now, "awake")

    # check that we have reverted back to normal schedule
    now += timedelta(hours=2)  # 22:40
    await check_state_at_time(hass, sensor, now, "asleep")


def schedule_modified_by_template(configfile: str):
    async def fn(hass: HomeAssistant, configfile=configfile) -> None:

        mode_switch = "input_boolean.mode"
        assert await setup.async_setup_component(
            hass, input_boolean.DOMAIN, {"input_boolean": {"mode": None}}
        )

        with open(configfile, "r") as f:
            config = yaml.safe_load(f)

        now = make_testtime(4, 0)
        with patch(TIME_FUNCTION_PATH, return_value=now) as p:
            await setup_test_entities(
                hass,
                config[0],
            )

            sensor = [e for e in hass.data["sensor"].entities][-1]
            check_state(hass, "sensor.lights", "off", p, now)

        hass.states.async_set(mode_switch, "on")
        await hass.async_block_till_done()

        now += timedelta(hours=8, minutes=1)  # 12:01
        await check_state_at_time(hass, sensor, now, "on")

        hass.states.async_set(mode_switch, "off")
        await hass.async_block_till_done()

        await check_state_at_time(hass, sensor, now, "off")

        now += timedelta(hours=2)  # 14:01
        await check_state_at_time(hass, sensor, now, "off")

    return fn


test_schedule_modified_by_template1 = schedule_modified_by_template(
    "tests/test001.yaml"
)

test_schedule_modified_by_template2 = schedule_modified_by_template(
    "tests/test002.yaml"
)

test_schedule_modified_by_template3 = schedule_modified_by_template(
    "tests/test003.yaml"
)


async def test_schedule_using_condition(hass: HomeAssistant):
    workday = "binary_sensor.workday_sensor"

    configfile = "tests/test011.yaml"
    with open(configfile, "r") as f:
        config = yaml.safe_load(f)

    # no workday sensor, not a holiday, early morning
    now = make_testtime(4, 0)
    with patch(TIME_FUNCTION_PATH, return_value=now) as p:
        await setup_test_entities(
            hass,
            config[0],
        )

        sensor = [e for e in hass.data["sensor"].entities][-1]
        check_state(hass, "sensor.heating_schedule", "nighttime", p, now)

    with patch(DATE_FUNCTION_PATH, return_value=date(2021, 11, 19)) as p:
        # now install workday sensor
        await setup.async_setup_component(
            hass,
            "binary_sensor",
            {
                "binary_sensor": {
                    "platform": "workday",
                    "country": "CA",
                    # "province": "ON",
                }
            },
        )
        await hass.async_block_till_done()
        await sensor.async_update_ha_state(force_refresh=True)

        assert p.called

        workday_sensor = [e for e in hass.data["binary_sensor"].entities][-1]
        _LOGGER.warn("workday sensor is %r", workday_sensor)

        check_state(hass, workday, "on")

        now += timedelta(minutes=10)  # 4:10
        await check_state_at_time(hass, sensor, now, "nighttime")

        now += timedelta(hours=3)  # 7:10
        await check_state_at_time(hass, sensor, now, "daybreak")

        now += timedelta(hours=3)  # 10:10
        await check_state_at_time(hass, sensor, now, "working")

        now += timedelta(hours=6)  # 16:10
        await check_state_at_time(hass, sensor, now, "afternoon")

    with patch(DATE_FUNCTION_PATH, return_value=date(2021, 12, 25)) as p:
        await hass.async_block_till_done()
        await workday_sensor.async_update_ha_state(force_refresh=True)

        assert p.called

        check_state(hass, workday, "off")

        now = make_testtime(4, 0)
        await check_state_at_time(hass, sensor, now, "nighttime")

        now += timedelta(hours=3)  # 7:00
        await check_state_at_time(hass, sensor, now, "nighttime")

        now += timedelta(hours=2)  # 9:00
        await check_state_at_time(hass, sensor, now, "daybreak")

        now += timedelta(hours=13, minutes=28)  # 22:28
        await check_state_at_time(hass, sensor, now, "evening")


async def check_state_at_time(hass, sensor, now, value):
    with patch(TIME_FUNCTION_PATH, return_value=now) as p:
        await sensor.async_update_ha_state(force_refresh=True)
        check_state(hass, sensor.entity_id, value, p, now)


def check_state(hass, name, value, p=None, now=None):
    _LOGGER.debug("check state of %s", name)
    entity_state = hass.states.get(name)
    assert entity_state
    if p is not None:
        assert p.called
        if now is not None:
            assert p.return_value == now
    assert entity_state.state == value
    return entity_state


async def set_override(hass, target, now, state, start=None, end=None, duration=None):
    data = {CONF_STATE: state}
    if start is not None:
        data[CONF_START] = start
    if end is not None:
        data[CONF_END] = end
    if duration is not None:
        data[CONF_DURATION] = duration

    with patch(TIME_FUNCTION_PATH, return_value=now) as p:
        await hass.services.async_call(
            DOMAIN,
            "set_override",
            service_data=data,
            blocking=True,
            target={
                "entity_id": target,
            },
        )

        assert p.called
        assert p.return_value == now


def make_testtime(h: int, m: int):
    return datetime(2021, 11, 20, h, m, tzinfo=timezone.utc)
