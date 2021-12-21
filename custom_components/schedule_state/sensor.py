"""
A sensor that returns a string based on a defined schedule.
"""
from datetime import time, timedelta, datetime
import logging
from pprint import pformat

from homeassistant.components.sensor import PLATFORM_SCHEMA, SensorEntity
from homeassistant.const import CONF_CONDITION, CONF_NAME, CONF_STATE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import (
    ConditionError,
    ConditionErrorContainer,
    ConditionErrorIndex,
    HomeAssistantError,
)
from homeassistant.helpers import condition
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.reload import async_setup_reload_service
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.util import dt
import portion as P
import voluptuous as vol

from .const import *

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor"]

DEFAULT_NAME = "Schedule State Sensor"
DEFAULT_STATE = "default"

SCAN_INTERVAL = timedelta(seconds=60)

CONF_EVENTS = "events"
CONF_START = "start"
CONF_START_TEMPLATE = "start_template"
CONF_END = "end"
CONF_END_TEMPLATE = "end_template"
CONF_DEFAULT_STATE = "default_state"
CONF_REFRESH = "refresh"

_CONDITION_SCHEMA = vol.All(cv.ensure_list, [cv.CONDITION_SCHEMA])

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Optional(CONF_EVENTS): [
            {
                vol.Optional(CONF_START): cv.time,
                vol.Optional(CONF_START_TEMPLATE): cv.template,
                vol.Optional(CONF_END): cv.time,
                vol.Optional(CONF_END_TEMPLATE): cv.template,
                vol.Required(CONF_STATE, default=DEFAULT_STATE): cv.string,
                vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
                vol.Optional(CONF_CONDITION): _CONDITION_SCHEMA,
            }
        ],
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
        vol.Optional(CONF_DEFAULT_STATE, default=DEFAULT_STATE): cv.string,
        vol.Optional(CONF_REFRESH, default="6:00:00"): cv.time_period_str,
    }
)


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType = None,
) -> None:
    """Set up the Schedule Sensor."""

    await async_setup_reload_service(hass, DOMAIN, PLATFORMS)

    events = config.get(CONF_EVENTS)
    name = config.get(CONF_NAME)
    refresh = config.get(CONF_REFRESH)
    data = ScheduleSensorData(name, hass, events, refresh)
    await data.process_events()

    async_add_entities([ScheduleSensor(hass, data, name)], True)


class ScheduleSensor(SensorEntity):
    """Representation of a sensor that returns a state name based on a predefined schedule."""

    def __init__(self, hass, data, name):
        """Initialize the sensor."""
        self._hass = hass
        self.data = data
        self._attributes = None
        self._name = name
        self._state = None

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._name

    @property
    def native_value(self):
        """Return the state of the device."""
        return self._state

    @property
    def extra_state_attributes(self):
        """Return the state attributes."""
        return self._attributes

    async def async_update(self) -> None:
        """Get the latest data and updates the state."""
        await self.data.update()
        value = self.data.value

        if value is None:
            value = DEFAULT_STATE
        self._state = value


class ScheduleSensorData:
    """The class for handling the state computation."""

    def __init__(self, name, hass, events, refresh):
        """Initialize the data object."""
        self.name = name
        self.value = None
        self.hass = hass
        self.events = events
        self.refresh = refresh
        self.states = {}
        self.refresh_time = None

    async def process_events(self):
        """Process the list of events and derive the schedule for the day."""
        events = self.events
        states = {}

        for event in events:
            _LOGGER.debug(f"{self.name}: processing event {event}")
            state = event.get("state", "default")
            cond = event.get("condition", None)

            variables = {}
            if cond is not None:
                cond_func = await _async_process_if(self.hass, event.get("name"), cond)
                if not cond_func(variables):
                    _LOGGER.debug(
                        f"{self.name}: {state}: condition was not satisfied, skipping {event}"
                    )
                    continue

            start = await self.get_start(event)
            end = await self.get_end(event)
            if start > end:
                _LOGGER.error(
                    f"{self.name}: {state}: error with event - start:{start} > end:{end}"
                )
                continue

            i = P.closedopen(start, end)
            for xstate in states:
                if xstate == state:
                    continue
                overlap = i & states[xstate]
                if i.overlaps(states[xstate]):
                    _LOGGER.debug(
                        f"{self.name}: {state} overlaps with existing {xstate}: {overlap}"
                    )
                    states[xstate] -= overlap
                    _LOGGER.debug(
                        f"{self.name}: ... reducing {xstate} to {states[xstate]}"
                    )

            if state not in states:
                states[state] = i
            else:
                states[state] = states[state] | i

        _LOGGER.info(f"{self.name}:\n{pformat(states)}")
        self.states = states
        self.refresh_time = dt.as_local(dt.now())

    async def get_start(self, event):
        return self.evaluate_template(event, "start", time.min)

    async def get_end(self, event):
        return self.evaluate_template(event, "end", time.max)

    def evaluate_template(self, event, prefix, default):
        s = event.get(prefix, None)
        st = event.get(prefix + "_template", None)

        if s is None and st is None:
            _LOGGER.debug(f"{self.name}: ... no {prefix} provided, using default")
            ret = default

        elif s is not None:
            if st is not None:
                _LOGGER.debug(
                    f"{self.name}: ... ignoring {prefix}_template since {prefix} was provided"
                )
            ret = s

        else:
            st.hass = self.hass
            temp = st.async_render_with_possible_json_value(st, time.min)
            _LOGGER.debug(f"{self.name}: ... {prefix}_template text: {temp}")
            ret = self.guess_value(temp)

        if ret is None:
            ret = default

        _LOGGER.debug(f"{self.name}: ... >> {prefix} time: {ret}")
        return ret

    def guess_value(self, text):
        try:
            date = dt.parse_datetime(text)
            if date is not None:
                _LOGGER.debug(f"{self.name}: ...... found datetime: {date}")
                tme = dt.as_local(date).time()
                return tme
        except ValueError:
            pass

        try:
            date = datetime.fromisoformat(text)
            _LOGGER.debug(f"{self.name}: ...... found isoformat date: {date}")
            tme = dt.as_local(date).time()
            return tme
        except ValueError:
            pass

        try:
            tme = dt.parse_time(text)
            if tme is not None:
                _LOGGER.debug(f"{self.name}: ...... found time: {tme}")
                return dt.as_local(tme)
        except ValueError:
            pass

        try:
            tme = time.fromisoformat(text)
            _LOGGER.debug(f"{self.name}: ...... found isoformat time: {tme}")
            return dt.as_local(tme)
        except ValueError:
            pass

        try:
            date = dt.utc_from_timestamp(int(float(text)))
            _LOGGER.debug(f"{self.name}: ...... found timestamp: {date}")
            tme = dt.as_local(date).time()
            return tme
        except:
            pass

        return None

    async def update(self):
        """Get the latest state based on the event schedule."""
        now = dt.as_local(dt.now())
        nu = time(now.hour, now.minute)

        time_since_refresh = now - self.refresh_time
        if time_since_refresh.total_seconds() >= self.refresh.total_seconds():
            await self.process_events()

        for state in self.states:
            if nu in self.states[state]:
                _LOGGER.debug(f"{self.name}: current state is {state} ({nu})")
                self.value = state
                return
        _LOGGER.info(f"{self.name}: current state not found ({nu})")
        self.value = None


async def _async_process_if(hass, name, if_configs):
    """Process if checks."""
    checks = []
    for if_config in if_configs:
        try:
            checks.append(await condition.async_from_config(hass, if_config))
        except HomeAssistantError as ex:
            _LOGGER.warning("Invalid condition: %s", ex)
            return None

    def if_action(variables=None):
        """AND all conditions."""
        errors = []
        for index, check in enumerate(checks):
            try:
                # with trace_path(["condition", str(index)]):
                #     if not check(hass, variables):
                #         return False
                if not check(hass, variables):
                    return False
            except ConditionError as ex:
                errors.append(
                    ConditionErrorIndex(
                        "condition", index=index, total=len(checks), error=ex
                    )
                )

        if errors:
            _LOGGER.warning(
                "Error evaluating condition in '%s':\n%s",
                name,
                ConditionErrorContainer("condition", errors=errors),
            )
            return False

        return True

    if_action.config = if_configs

    return if_action
