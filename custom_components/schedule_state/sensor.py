"""
A sensor that returns a string based on a defined schedule.
"""
from datetime import time, timedelta, datetime
import logging
from pprint import pformat
import asyncio

from homeassistant.components.sensor import PLATFORM_SCHEMA, SensorEntity
from homeassistant.const import CONF_CONDITION, CONF_NAME, CONF_STATE, ATTR_ENTITY_ID
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
CONF_COMMENT = "comment"
CONF_DURATION = "duration"

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
                vol.Optional(CONF_COMMENT): cv.string,
                vol.Optional(CONF_CONDITION): _CONDITION_SCHEMA,
            }
        ],
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
        vol.Optional(CONF_DEFAULT_STATE, default=DEFAULT_STATE): cv.string,
        vol.Optional(CONF_REFRESH, default="6:00:00"): cv.time_period_str,
    }
)

RECALCULATE_SERVICE_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_ENTITY_ID): cv.entity_ids,
    }
)

OVERRIDE_SERVICE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ENTITY_ID): cv.entity_ids,
        vol.Required(CONF_STATE): cv.string,
        vol.Optional(CONF_DURATION): cv.positive_int,
        vol.Optional(CONF_START): cv.time,
        vol.Optional(CONF_END): cv.time,
    }
)

CLEAR_OVERRIDES_SERVICE_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_ENTITY_ID): cv.entity_ids,
    }
)


class Override(dict):
    def __init__(self, state, start, end, expires):
        self["state"] = state
        self["start"] = start
        self["end"] = end
        self["expires"] = expires


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType = None,
) -> None:
    """Set up the Schedule Sensor."""

    await async_setup_reload_service(hass, DOMAIN, PLATFORMS)

    events = config.get(CONF_EVENTS, [])
    name = config.get(CONF_NAME)
    refresh = config.get(CONF_REFRESH)
    data = ScheduleSensorData(name, hass, events, refresh)
    await data.process_events()

    def get_target_devices(service):
        if entity_ids := service.data.get(ATTR_ENTITY_ID):
            target_devices = [
                dev
                for dev in hass.data["sensor"].entities
                if dev.entity_id in entity_ids
            ]
        else:
            target_devices = [e for e in hass.data["sensor"].entities]

        return target_devices

    async def async_recalculate_service_handler(service):
        target_devices = get_target_devices(service)
        update_tasks = []
        for target_device in target_devices:
            await target_device.async_recalculate()
            update_tasks.append(target_device.async_update_ha_state(True))

        if update_tasks:
            await asyncio.wait(update_tasks)

    async def async_set_override_service_handler(service):
        target_devices = get_target_devices(service)
        update_tasks = []
        for target_device in target_devices:
            await target_device.async_set_override(
                service.data["state"],
                service.data.get("start", None),
                service.data.get("end", None),
                service.data.get("duration", None),
            )
            update_tasks.append(target_device.async_update_ha_state(True))

        if update_tasks:
            await asyncio.wait(update_tasks)

    async def async_clear_overrides_service_handler(service):
        target_devices = get_target_devices(service)
        update_tasks = []
        for target_device in target_devices:
            await target_device.async_clear_overrides()
            update_tasks.append(target_device.async_update_ha_state(True))

        if update_tasks:
            await asyncio.wait(update_tasks)

    hass.services.async_register(
        DOMAIN,
        "recalculate",
        async_recalculate_service_handler,
        schema=RECALCULATE_SERVICE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        "set_override",
        async_set_override_service_handler,
        schema=OVERRIDE_SERVICE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        "clear_overrides",
        async_clear_overrides_service_handler,
        schema=CLEAR_OVERRIDES_SERVICE_SCHEMA,
    )

    default_state = config.get(CONF_DEFAULT_STATE)
    async_add_entities([ScheduleSensor(hass, data, name, default_state)], True)


class ScheduleSensor(SensorEntity):
    """Representation of a sensor that returns a state name based on a predefined schedule."""

    def __init__(self, hass, data, name, default_state):
        """Initialize the sensor."""
        self._hass = hass
        self.data = data
        self._attributes = {}
        self._name = name
        self._state = None
        self._default_state = default_state

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
            value = self._default_state
        self._state = value
        self._attributes["states"] = self.data.known_states

    async def async_recalculate(self):
        """Recalculate schedule state."""
        _LOGGER.info(f"{self._name}: recalculate")
        await self.data.process_events()

    async def async_set_override(self, state: str, start, end, duration):
        """Set override state."""
        _LOGGER.info(f"{self._name}: override to {state} for {start} {end} {duration}")
        if self.data.add_override(state, start, end, duration):
            await self.data.process_events()

    async def async_clear_overrides(self):
        """Clear overrides, if any."""
        _LOGGER.info(f"{self._name}: clear overrides")
        if self.data.clear_overrides():
            await self.data.process_events()


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
        self.overrides = []
        self.known_states = set()

    async def process_events(self):
        """Process the list of events and derive the schedule for the day."""
        states = {}

        for event in self.events + self.overrides:
            _LOGGER.debug(f"{self.name}: processing event {event}")
            state = event.get("state", "default")
            cond = event.get("condition", None)
            self.known_states.add(state)

            variables = {}
            if cond is not None:
                cond_func = await _async_process_if(self.hass, self.name, cond)
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

        self.overrides = [o for o in self.overrides if o["expires"] > now]
        for o in self.overrides:
            _LOGGER.debug(
                f"{self.name}: override = {o['start']} - {o['end']} == {o['state']} [expires {o['expires']}]"
            )

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

    def add_override(self, state, start, end, duration):
        now = dt.as_local(dt.now())
        allow_split = True

        if start is None and end is None and duration is None:
            _LOGGER.error(
                "override failed: you have to provide one of start/end/duration"
            )
            return False
        elif start is not None and end is not None and duration is not None:
            _LOGGER.error(
                "override failed: you cannot provide start+end+duration together"
            )
            return False
        elif start is None and end is None:
            start = simple_time(now)
            end = start + timedelta(minutes=duration)
        elif start is not None and end is None and duration is not None:
            start = next_time(now, start)
            end = start + timedelta(minutes=duration)
        elif start is None and end is not None and duration is not None:
            end = next_time(now, end)
            start = end - timedelta(minutes=duration)
        elif start is not None and end is not None and duration is None:
            # don't try to fix wraparounds in this case, where both start and end times were provided
            start = next_time(now, start)
            end = next_time(now, end)
            allow_split = False
        else:
            _LOGGER.error("override failed: no duration provided")
            return False

        if start > end:
            if allow_split:
                # split into two overrides if there is a wraparound (eg: 23:55 to 00:10)
                ev = Override(state, start.time(), time.max, start_of_next_day(now))
                self.overrides.append(ev)
                start = time.min
            else:
                _LOGGER.error(f"override failed: start ({start}) > end ({end})")
                return False

        ev = Override(state, start.time(), end.time(), end + timedelta(seconds=30))
        self.overrides.append(ev)
        return True

    def clear_overrides(self):
        if len(self.overrides):
            self.overrides = []
            return True
        return False


def simple_time(n: datetime) -> datetime:
    """return n with seconds/microseconds removed"""
    return datetime(
        year=n.year,
        month=n.month,
        day=n.day,
        hour=n.hour,
        minute=n.minute,
        tzinfo=n.tzinfo,
    )


def next_time(now: datetime, t: time) -> datetime:
    '''what is the next datetime that the given time occurs, relative to "now"'''
    if now.hour > t.hour:
        # we have passed the time t, so we need it for tomorrow
        v = start_of_next_day(now)
        return datetime(v.year, v.month, v.day, t.hour, t.minute)
    else:
        # later today
        return datetime(now.year, now.month, now.day, t.hour, t.minute)


def start_of_next_day(d: datetime) -> datetime:
    v = d + timedelta(1)
    return datetime(v.year, v.month, v.day)


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
