"""
A sensor that returns a string based on a defined schedule.
Modified to add enriched attributes for schedule-state-card compatibility.
"""

import asyncio
from collections import OrderedDict
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, time, timedelta
import hashlib
import locale
import logging
from pprint import pformat
from typing import Any, NamedTuple, Optional

from homeassistant.components.sensor import PLATFORM_SCHEMA, SensorEntity
from homeassistant.const import (
    ATTR_ENTITY_ID,
    CONF_CONDITION,
    CONF_ICON,
    CONF_ID,
    CONF_NAME,
    CONF_STATE,
    EVENT_HOMEASSISTANT_START,
    MATCH_ALL,
    SERVICE_TOGGLE,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_OFF,
    STATE_ON,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import (
    ConditionError,
    ConditionErrorContainer,
    ConditionErrorIndex,
    HomeAssistantError,
    TemplateError,
)
from homeassistant.helpers import condition
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.reload import async_setup_reload_service
from homeassistant.helpers.restore_state import ExtraStoredData, RestoreEntity
from homeassistant.helpers.template import Template
from homeassistant.helpers.trace import trace_path
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.util import dt
import portion as P
import voluptuous as vol
import yaml

from .const import (
    CONF_ALLOW_WRAP,
    CONF_COMMENT,
    CONF_DEFAULT_STATE,
    CONF_DURATION,
    CONF_END,
    CONF_END_OFFSET,
    CONF_ERROR_ICON,
    CONF_EVENTS,
    CONF_EXTRA_ATTRIBUTES,
    CONF_MINUTES_TO_REFRESH_ON_ERROR,
    CONF_REFRESH,
    CONF_START,
    CONF_START_OFFSET,
    DEFAULT_ERROR_ICON,
    DEFAULT_ICON,
    DEFAULT_NAME,
    DEFAULT_STATE,
    DOMAIN,
    PLATFORMS,
)

_LOGGER = logging.getLogger(__name__)

_CONDITION_SCHEMA = vol.All(cv.ensure_list, [cv.CONDITION_SCHEMA])


# FIXME not sure how to accept templates for icons
# IconSchema = vol.Any(
#     vol.Coerce(cv.icon),
#     cv.template,
# )
IconSchema = cv.icon

TimeSchema = vol.Any(vol.Coerce(cv.time), cv.template)


class TemplateResult(NamedTuple):
    template: Optional[str]
    result: Any
    success: bool


def AnyData(x):
    return x


PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Optional(CONF_EVENTS): [
            vol.All(
                {
                    vol.Optional(CONF_START): TimeSchema,
                    vol.Optional(CONF_START_OFFSET): vol.Any(cv.template, float),
                    vol.Optional(CONF_END): TimeSchema,
                    vol.Optional(CONF_END_OFFSET): vol.Any(cv.template, float),
                    vol.Optional(CONF_STATE): vol.Any(cv.template, cv.string),
                    vol.Optional(CONF_COMMENT): cv.string,
                    vol.Optional(CONF_CONDITION): _CONDITION_SCHEMA,
                    vol.Optional(CONF_ICON): IconSchema,
                    vol.Optional(CONF_ALLOW_WRAP): cv.boolean,
                    # allow extra keys - for extra attributes
                    vol.Optional(str): vol.Any(cv.template, AnyData),
                },
            )
        ],
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
        vol.Optional(CONF_DEFAULT_STATE): vol.Any(cv.template, cv.string),
        vol.Optional(CONF_REFRESH, default="6:00:00"): cv.time_period_str,
        vol.Optional(CONF_ICON): IconSchema,
        vol.Optional(CONF_ERROR_ICON, default=DEFAULT_ERROR_ICON): IconSchema,
        vol.Optional(CONF_MINUTES_TO_REFRESH_ON_ERROR, default=5): cv.positive_int,
        vol.Optional(CONF_ALLOW_WRAP, default=False): cv.boolean,
        vol.Optional(CONF_EXTRA_ATTRIBUTES): {cv.string: vol.Any(cv.template, AnyData)},
    },
)

RECALCULATE_SERVICE_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_ENTITY_ID): cv.entity_ids,
    }
)

SET_OVERRIDE_SERVICE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ENTITY_ID): cv.entity_ids,
        vol.Optional(CONF_ID): cv.string,
        vol.Required(CONF_STATE): cv.string,
        vol.Optional(CONF_DURATION): cv.positive_int,
        vol.Optional(CONF_START): cv.time,
        vol.Optional(CONF_END): cv.time,
        vol.Optional(CONF_ICON): cv.icon,
        vol.Optional(CONF_EXTRA_ATTRIBUTES): {cv.string: AnyData},
    }
)

REMOVE_OVERRIDE_SERVICE_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_ENTITY_ID): cv.entity_ids,
        vol.Required(CONF_ID): cv.string,
    }
)


CLEAR_OVERRIDES_SERVICE_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_ENTITY_ID): cv.entity_ids,
    }
)


ON_OFF_TOGGLE_SERVICE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ENTITY_ID): cv.entity_ids,
        vol.Optional(CONF_DURATION): cv.positive_int,
    }
)


class Override(dict):
    KNOWN_ATTRS = ["id", "state", "start", "end", "expires", "icon"]

    def __init__(self, id, state, start, end, expires, icon, extra_attributes):
        self["id"] = id
        self["state"] = state
        self["start"] = start
        self["end"] = end
        self["expires"] = expires
        self["icon"] = icon
        for attr in extra_attributes:
            self[attr] = extra_attributes[attr]

    @classmethod
    def from_dict(cls, d: dict):  # -> Override | None:
        """Reconstruct a saved override from a dict"""
        try:
            extra = {k: d[k] for k in d if k not in cls.KNOWN_ATTRS}

            x = Override(
                d.get("id"),
                d.get("state"),
                # start/end are datetime.time's - no need to parse - see #166
                d.get("start"),
                d.get("end"),
                # this is quite confusing, because this gets converted to a string and needs to be parsed - see #188
                dt.parse_datetime(d.get("expires")),
                d.get("icon"),
                extra,
            )
            return x

        except (ValueError, KeyError, TypeError):
            _LOGGER.error(f"could not reconstruct saved override: {d}")
            return None


@dataclass
class ScheduleStateExtraStoredData(ExtraStoredData):
    """This is used by the RestoreEntity framework to store schedule_state-specific data"""

    overrides: list[Override]

    def as_dict(self) -> dict[str, Any]:
        return dict(overrides=self.overrides)

    @classmethod
    def from_dict(
        cls, restored: dict[str, Any]
    ):  # -> ScheduleStateExtraStoredData | None:
        try:
            overrides = restored["overrides"]
        except KeyError:
            return None
        return cls(overrides)


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType = None,
) -> None:
    """Set up the Schedule Sensor."""

    await async_setup_reload_service(hass, DOMAIN, PLATFORMS)
    await async_setup_services(hass)

    data = ScheduleSensorData(hass, config)
    await data.process_events()

    name = config.get(CONF_NAME)
    entity = ScheduleSensor(hass, name, data, config)
    async_add_entities([entity], True)


async def async_setup_services(hass: HomeAssistant):
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

        _ = [await asyncio.create_task(coro) for coro in update_tasks]

    async def async_set_override_service_handler(service):
        target_devices = get_target_devices(service)
        update_tasks = []
        for target_device in target_devices:
            await target_device.async_set_override(
                service.data.get(CONF_ID, None),
                service.data[CONF_STATE],
                service.data.get(CONF_START, None),
                service.data.get(CONF_END, None),
                service.data.get(CONF_DURATION, None),
                service.data.get(CONF_ICON, None),
                service.data.get(CONF_EXTRA_ATTRIBUTES, None),
            )
            update_tasks.append(target_device.async_update_ha_state(True))

        _ = [await asyncio.create_task(coro) for coro in update_tasks]

    async def async_remove_override_service_handler(service):
        target_devices = get_target_devices(service)
        update_tasks = []
        for target_device in target_devices:
            await target_device.async_remove_override(
                service.data[CONF_ID],
            )
            update_tasks.append(target_device.async_update_ha_state(True))

        _ = [await asyncio.create_task(coro) for coro in update_tasks]

    async def async_clear_overrides_service_handler(service):
        target_devices = get_target_devices(service)
        update_tasks = []
        for target_device in target_devices:
            await target_device.async_clear_overrides()
            update_tasks.append(target_device.async_update_ha_state(True))

        _ = [await asyncio.create_task(coro) for coro in update_tasks]

    async def async_turn_on_handler(service):
        target_devices = get_target_devices(service)
        update_tasks = []
        for target_device in target_devices:
            if STATE_ON in target_device.data.known_states:
                await target_device.async_set_override(
                    "turn_on_off",
                    STATE_ON,
                    None,  # start
                    None,  # end
                    service.data.get(CONF_DURATION, 30),
                    None,  # icon
                    None,  # extra attributes
                )
                update_tasks.append(target_device.async_update_ha_state(True))

        _ = [await asyncio.create_task(coro) for coro in update_tasks]

    async def async_turn_off_handler(service):
        target_devices = get_target_devices(service)
        update_tasks = []
        for target_device in target_devices:
            if STATE_OFF in target_device.data.known_states:
                await target_device.async_set_override(
                    "turn_on_off",
                    STATE_OFF,
                    None,  # start
                    None,  # end
                    service.data.get(CONF_DURATION, 30),
                    None,  # icon
                    None,  # extra attributes
                )
                update_tasks.append(target_device.async_update_ha_state(True))

        _ = [await asyncio.create_task(coro) for coro in update_tasks]

    async def async_toggle_handler(service):
        target_devices = get_target_devices(service)
        update_tasks = []
        for target_device in target_devices:
            if (
                STATE_OFF in target_device.data.known_states
                and STATE_ON in target_device.data.known_states
            ):
                new_state = None
                if target_device.native_value == STATE_ON:
                    new_state = STATE_OFF
                elif target_device.native_value == STATE_OFF:
                    new_state = STATE_ON

                if new_state is not None:
                    await target_device.async_set_override(
                        "turn_on_off",
                        new_state,
                        None,  # start
                        None,  # end
                        service.data.get(CONF_DURATION, 30),
                        None,  # icon
                        None,  # extra attributes
                    )
                    update_tasks.append(target_device.async_update_ha_state(True))

        _ = [await asyncio.create_task(coro) for coro in update_tasks]

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
        schema=SET_OVERRIDE_SERVICE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        "remove_override",
        async_remove_override_service_handler,
        schema=REMOVE_OVERRIDE_SERVICE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        "clear_overrides",
        async_clear_overrides_service_handler,
        schema=CLEAR_OVERRIDES_SERVICE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_TURN_ON,
        async_turn_on_handler,
        schema=ON_OFF_TOGGLE_SERVICE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_TURN_OFF,
        async_turn_off_handler,
        schema=ON_OFF_TOGGLE_SERVICE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_TOGGLE,
        async_toggle_handler,
        schema=ON_OFF_TOGGLE_SERVICE_SCHEMA,
    )


class ScheduleSensor(SensorEntity, RestoreEntity):
    """Representation of a sensor that returns a state name based on a predefined schedule."""

    _unrecorded_attributes = frozenset({MATCH_ALL})

    def __init__(self, hass, name, data, config):
        """Initialize the sensor."""
        self.data = data
        self._attributes = {}
        self._name = name
        self._state = None

        unique_id = hashlib.sha3_512(name.encode("utf-8")).hexdigest()
        self._attr_unique_id = unique_id

    async def async_added_to_hass(self):
        """Handle added to Hass."""
        await super().async_added_to_hass()

        # reload saved overrides, if any
        state = await self.async_get_last_extra_data()
        if state is not None:
            overrides = state.as_dict()["overrides"]

            if self.hass.is_running:
                await self.async_update_config(overrides)
            else:

                async def schedule_start_hass(now):
                    await self.async_update_config(overrides)

                self.hass.bus.async_listen_once(
                    EVENT_HOMEASSISTANT_START, schedule_start_hass
                )

        @callback
        async def recalc_callback(*args):
            _LOGGER.debug(f"{self.data.name}: something changed {args}")
            old_state = self._state
            old_attrs = self.data.extra_attributes
            await self.data.process_events()
            await self.async_update()
            if self._state != old_state or self.data.extra_attributes != old_attrs:
                self.schedule_update_ha_state(force_refresh=True)

        if len(self.data.entities):
            _LOGGER.info(
                f"{self.data.name}: installing callback to trigger on changes to {self.data.entities}"
            )
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass, self.data.entities, recalc_callback
                )
            )

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
            value = self.data.default_state
        self._state = value
        self._attributes["states"] = self.data.known_states
        self._attributes["next_state"] = self.data.attributes.get("next_state", None)
        self._attributes["start"] = self.data.attributes.get("start", None)
        self._attributes["end"] = self.data.attributes.get("end", None)
        self._attributes["friendly_start"] = friendly_time(
            self.data.attributes.get("start", None)
        )
        self._attributes["friendly_end"] = friendly_time(
            self.data.attributes.get("end", None)
        )
        self._attributes["errors"] = self.data.error_states

        # NEW ATTRIBUTES - Added for schedule-state-card compatibility
        self._attributes["layers"] = self.data.layers_by_day
        self._attributes["events"] = self.data.events_list
        self._attributes["total_events"] = self.data.total_events_count
        self._attributes["last_update"] = self.data.last_update_time
        self._attributes["default_state"] = self.data.default_state

        if len(self.data.error_states):
            self._attr_icon = self.data.error_icon
        else:
            self._attr_icon = (
                self.data.attributes.get("icon", None) or self.data.default_icon
            )

        # fetch extra attributes
        for key in self.data.extra_attributes.keys():
            self._attributes[key] = self.data.attributes.get(key, None)

    async def async_recalculate(self):
        """Recalculate schedule state."""
        _LOGGER.info(f"{self._name}: recalculate")
        await self.data.process_events()

    async def async_set_override(
        self, id, state: str, start, end, duration, icon, extra_attributes
    ):
        """Set override state."""
        _LOGGER.info(
            f"{self._name}: override to {state} for id={id} s={start} e={end} d={duration} ea={extra_attributes}"
        )
        if self.data.set_override(
            id, state, start, end, duration, icon, extra_attributes
        ):
            await self.data.process_events()
            return True

        return False

    async def async_remove_override(
        self,
        id: str,
    ):
        """Remove override state."""
        _LOGGER.info(f"{self._name}: remove override {id}")
        if self.data.remove_override(id):
            await self.data.process_events()
            return True

        return False

    async def async_clear_overrides(self):
        """Clear overrides, if any."""
        _LOGGER.info(f"{self._name}: clear overrides")
        if self.data.clear_overrides():
            await self.data.process_events()
            return True

        return False

    @property
    def extra_restore_state_data(self) -> ScheduleStateExtraStoredData:
        """This is periodically called by RestoreEntity to save dynamic data"""
        # overrides are only saved every 15 minutes
        # see STATE_DUMP_INTERVAL in restore_state.py -- is there any way to force this when an override is added/removed?
        _LOGGER.debug(f"{self.name}: extra_restore_state_data = {self.data.overrides}")
        # note: self.data.overrides is saved in native format, without any explicit conversions, but HA is still converting it to text somewhere
        # this is not what the pytest-homeassistant-custom-component does...
        return ScheduleStateExtraStoredData(self.data.overrides)

    async def async_update_config(self, override_list: list[Override]) -> None:
        """Called by async_added_to_hass with a list of previously-saved overrides"""
        _LOGGER.debug(f"{self._name}: async_update_config {override_list}")

        overrides = []
        for override_data in override_list:
            override = Override.from_dict(override_data)
            if override is not None:
                overrides.append(override)

        # update the schedule if any overrides were found
        if len(overrides):
            self.data.overrides = overrides
            await self.data.process_events()
            await self.async_update()


class ScheduleSensorData:
    """The class for handling the state computation."""

    def __init__(self, hass, config):
        """Initialize the data object."""
        self.name = config.get(CONF_NAME)
        self.value = None
        self.hass = hass
        self.events = config.get(CONF_EVENTS, [])
        self.refresh = config.get(CONF_REFRESH)
        self.minutes_to_refresh_on_error = config.get(CONF_MINUTES_TO_REFRESH_ON_ERROR)
        self.default_state = None
        self.default_icon = None
        self.error_icon = None
        self.config = config
        self._states = {}
        self._refresh_time = None
        self.overrides = []
        self.known_states = set()
        self.error_states = set()
        self.attributes = {}
        self.entities = set()
        self.force_refresh = None
        self.icon_map = {}
        self.extra_attributes = config.get(CONF_EXTRA_ATTRIBUTES, {})
        self._custom_attributes = {}

        # NEW ATTRIBUTES - For enriched data export
        self.layers_by_day = {}  # Layer structure by day
        self.events_list = []  # Raw list of events
        self.total_events_count = 0  # Total event counter
        self.last_update_time = None  # Update timestamp
        self.room_name = config.get(CONF_NAME)  # Room/zone name

    async def process_events(self):
        """Process the list of events and derive the schedule for the day."""

        # keep track of known states and report them in the attributes
        self.known_states = set()

        # keep track of the states with errors and report them in the attributes
        self.error_states = set()

        # FIXME templates not currently supported - see IconSchema above
        self.default_icon = self.evaluate_template(
            self.config,
            CONF_ICON,
            default=DEFAULT_ICON,
        ).result

        # FIXME templates not currently supported
        self.error_icon = self.evaluate_template(
            self.config,
            CONF_ERROR_ICON,
            default=DEFAULT_ERROR_ICON,
        ).result

        self.default_state = self.evaluate_template(
            self.config,
            CONF_DEFAULT_STATE,
            default=DEFAULT_STATE,
        ).result
        self.known_states.add(self.default_state)

        allow_wrap_global = self.config.get(CONF_ALLOW_WRAP, False)

        # TODO we should handle 'icon' the same as other extra attributes
        self._attr_keys = [k for k in self.extra_attributes.keys()]
        states = P.IntervalDict()
        attrs = {k: P.IntervalDict() for k in self._attr_keys}

        # add an interval for the default state and attributes
        interval = P.closedopen(time.min, time.max)
        self._add_interval(
            states, attrs, self.extra_attributes, self.default_state, interval
        )

        # now process all defined events and overrides
        for event in self.events + self.overrides:
            _LOGGER.debug(f"{self.name}: processing event {event}")
            state_eval = self.evaluate_template(
                event,
                CONF_STATE,
                default=self.default_state,
            )
            if not state_eval.success:
                # error evaluating template - skip this event
                continue

            state = state_eval.result
            self.known_states.add(state)

            cond = event.get(CONF_CONDITION, None)

            # Calculate new refresh time to be used if there was a problem evaluating the template or condition.
            # This can happen if the things that the template is dependent on have not been started up by HA yet...
            # or it could be a problem with the template/condition definition, it doesn't seem possible to know which.
            new_refresh_time = dt.as_local(dt_now()) + timedelta(
                minutes=self.minutes_to_refresh_on_error
            )
            if self.force_refresh is not None:
                force_refresh = min(self.force_refresh, new_refresh_time)
            else:
                force_refresh = new_refresh_time

            cond_result = await _async_process_cond(
                self.hass, self.name, cond, self.entities
            )
            if cond_result is False:
                _LOGGER.debug(
                    f"{self.name}: {state}: condition was not satisfied - skipping"
                )
                continue
            elif cond_result is None:
                # There was a problem evaluating the condition - force a refresh
                self.force_refresh = force_refresh
                self.error_states.add(state)
                _LOGGER.error(
                    f"{self.name}: {state}: error evaluating condition - skipping, will try again in {self.minutes_to_refresh_on_error} minutes"
                )
                continue

            start = await self.get_start(event)
            end = None if start is None else await self.get_end(event)
            if None in (start, end):
                # There was a problem evaluating the template - force a refresh
                self.force_refresh = force_refresh
                self.error_states.add(state)
                _LOGGER.error(
                    f"{self.name}: {state}: error with start/end definition - skipping, will try again in {self.minutes_to_refresh_on_error} minutes"
                )
                continue

            # apply start/end offsets, if any - these can be templates
            start_offset = None
            end_offset = None
            offset_eval = self.evaluate_template(event, CONF_START_OFFSET, default=0)
            if offset_eval.success:
                with suppress(ValueError):
                    start_offset = float(offset_eval.result)

            offset_eval = self.evaluate_template(event, CONF_END_OFFSET, default=0)
            if offset_eval.success:
                with suppress(ValueError):
                    end_offset = float(offset_eval.result)

            if None in (start_offset, end_offset):
                # There was a problem evaluating the template - force a refresh
                self.force_refresh = force_refresh
                self.error_states.add(state)
                _LOGGER.error(
                    f"{self.name}: {state}: error with offset definition - skipping, will try again in {self.minutes_to_refresh_on_error} minutes"
                )
                continue

            start = self.apply_offset(start, start_offset)
            end = self.apply_offset(end, end_offset)

            # is wrapping allowed for this event? (default it the global setting)
            allow_wrap = event.get(CONF_ALLOW_WRAP, allow_wrap_global)

            # get the interval(s) for this event
            intervals, error = self._get_intervals(start, end, allow_wrap)

            if error is not None:
                self.error_states.add(state)
                _LOGGER.error(f"{self.name}: {state}: {error} - skipping")
                continue

            icon = self.evaluate_template(
                event,
                CONF_ICON,
            )
            if icon.success:
                self.icon_map[state] = icon.result

            # Layer on the new intervals to the schedule
            self._add_interval(states, attrs, event, state, intervals)

        _LOGGER.info(f"{self.name}:\n{pformat(states)}\n{pformat(attrs)}")
        self._states = states
        self._custom_attributes = attrs
        self._refresh_time = dt.as_local(dt_now())

        # NEW: Build enriched attributes
        self.layers_by_day = await self._build_layers_structure()
        self.events_list = await self._serialize_events_list()
        self.total_events_count = sum(
            len(layers) for layers in self.layers_by_day.values()
        )
        self.last_update_time = dt.as_local(dt_now()).isoformat()

    # NEW METHOD: Serialize events list
    async def _serialize_events_list(self):
        """Serialize events list to JSON-compatible format."""
        serialized_events = []
        for event in self.events + self.overrides:
            serialized_event = {}
            for key, value in event.items():
                if isinstance(value, Template):
                    # Convert Template to string representation
                    serialized_event[key] = (
                        str(value.template)
                        if hasattr(value, "template")
                        else str(value)
                    )
                elif isinstance(value, time):
                    # Convert time to string
                    serialized_event[key] = value.isoformat()
                elif isinstance(value, datetime):
                    # Convert datetime to ISO format
                    serialized_event[key] = value.isoformat()
                elif isinstance(value, list):
                    # Recursively serialize lists
                    serialized_event[key] = self._serialize_list(value)
                elif isinstance(value, dict):
                    # Recursively serialize dicts
                    serialized_event[key] = self._serialize_dict(value)
                elif isinstance(value, (str, int, float, bool, type(None))):
                    # Already JSON serializable primitives
                    serialized_event[key] = value
                else:
                    # Convert any other type to string
                    serialized_event[key] = str(value)
            serialized_events.append(serialized_event)
        return serialized_events

    def _serialize_list(self, lst):
        """Recursively serialize a list to JSON-compatible format."""
        serialized = []
        for item in lst:
            if isinstance(item, Template):
                serialized.append(
                    str(item.template) if hasattr(item, "template") else str(item)
                )
            elif isinstance(item, (time, datetime)):
                serialized.append(item.isoformat())
            elif isinstance(item, list):
                serialized.append(self._serialize_list(item))
            elif isinstance(item, dict):
                serialized.append(self._serialize_dict(item))
            elif isinstance(item, (str, int, float, bool, type(None))):
                serialized.append(item)
            else:
                serialized.append(str(item))
        return serialized

    def _serialize_dict(self, dct):
        """Recursively serialize a dict to JSON-compatible format."""
        serialized = {}
        for key, value in dct.items():
            if isinstance(value, (Template, time, datetime)):
                serialized[key] = (
                    self._serialize_template(value)
                    if isinstance(value, Template)
                    else value.isoformat()
                )
            elif isinstance(value, (list, dict)):
                serialized[key] = (
                    self._serialize_list(value)
                    if isinstance(value, list)
                    else self._serialize_dict(value)
                )
            elif isinstance(value, (str, int, float, bool, type(None))):
                serialized[key] = value
            else:
                serialized[key] = str(value)
        return serialized

    # NEW METHOD: Serialize template to string
    def _serialize_template(self, template_obj):
        """Convert Template object to serializable string."""
        if template_obj is None:
            return ""

        if isinstance(template_obj, Template):
            # Extract the template string
            if hasattr(template_obj, "template"):
                return str(template_obj.template)
            else:
                # Fallback: try to get a reasonable string representation
                template_str = str(template_obj)
                # Remove the non-serializable wrapper text
                if "Template<template=" in template_str:
                    # Extract just the template part
                    return (
                        template_str.split("template=")[1]
                        .split(" renders=")[0]
                        .strip("()")
                    )
                return template_str

        return str(template_obj)

    # NEW METHOD: Build layers structure
    async def _build_layers_structure(self):
        """Build layers structure organized by day."""
        days = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
        layers_by_day = {}
        for day in days:
            layers_by_day[day] = await self._build_layers_for_day(day)
        return layers_by_day

    # NEW METHOD: Build layers for a specific day
    async def _build_layers_for_day(self, day):
        """Build event layers for a given day, grouped by identical conditions."""
        groups = OrderedDict()

        for event_idx, event in enumerate(self.events + self.overrides):
            conditions = event.get(CONF_CONDITION, []) or []
            if not isinstance(conditions, list):
                conditions = [conditions] if conditions else []

            # Extract months from event and add to conditions
            months = event.get("months", None) or event.get("month", None)
            if months is not None:
                month_condition = {"condition": "time", "month": months}
                conditions.append(month_condition)

            # Filter by weekday
            weekdays = self._get_weekdays_from_condition(conditions)
            if day not in weekdays:
                continue

            # Evaluate state
            state_eval = self.evaluate_template(
                event, CONF_STATE, default=self.default_state
            )
            if not state_eval.success:
                continue

            state = state_eval.result

            # Get start/end times
            start = await self.get_start(event)
            end = await self.get_end(event)
            if None in (start, end):
                continue

            # Apply offsets if any
            start_offset = 0
            end_offset = 0
            offset_eval = self.evaluate_template(event, CONF_START_OFFSET, default=0)
            if offset_eval.success:
                with suppress(ValueError):
                    start_offset = float(offset_eval.result)

            offset_eval = self.evaluate_template(event, CONF_END_OFFSET, default=0)
            if offset_eval.success:
                with suppress(ValueError):
                    end_offset = float(offset_eval.result)

            start = self.apply_offset(start, start_offset)
            end = self.apply_offset(end, end_offset)

            # Check if wrapping is allowed
            allow_wrap_global = self.config.get(CONF_ALLOW_WRAP, False)
            allow_wrap = event.get(CONF_ALLOW_WRAP, allow_wrap_global)

            # Detect wrapping
            wraps = start > end

            # Create condition key for grouping
            try:
                condition_key = self._serialize_conditions(conditions)
            except TypeError:
                condition_key = "default"

            if condition_key not in groups:
                groups[condition_key] = []

            # Store original times for display
            original_start = start.strftime("%H:%M")
            original_end = end.strftime("%H:%M")

            # If wrapping, create TWO blocks: one for each day
            if wraps and allow_wrap:
                # Block 1: start -> 23:59 (current day ends)
                block1 = {
                    "event_idx": event_idx,
                    "start": start.strftime("%H:%M"),
                    "end": "00:00",  # Midnight
                    "original_start": original_start,
                    "original_end": original_end,
                    "wraps_start": False,
                    "wraps_end": True,  # This block wraps to next day
                    "state_value": state,
                    "raw_state_template": self._serialize_template(
                        event.get(CONF_STATE)
                    ),
                    "unit": event.get("unit", ""),
                    "raw_conditions": conditions,
                    "condition_text": self._format_conditions(conditions),
                    "tooltip": event.get("tooltip", ""),
                    "description": event.get(CONF_COMMENT, ""),
                    "icon": event.get(CONF_ICON, "mdi:calendar"),
                    "is_default_bg": False,
                    "z_index": 2,
                    "is_dynamic_color": self._is_dynamic_value(state),
                }
                groups[condition_key].append(block1)

                # Block 2: 00:00 -> end (next day starts)
                block2 = {
                    "event_idx": event_idx,
                    "start": "00:00",
                    "end": end.strftime("%H:%M"),
                    "original_start": original_start,
                    "original_end": original_end,
                    "wraps_start": True,  # This block wraps from previous day
                    "wraps_end": False,
                    "state_value": state,
                    "raw_state_template": self._serialize_template(
                        event.get(CONF_STATE)
                    ),
                    "unit": event.get("unit", ""),
                    "raw_conditions": conditions,
                    "condition_text": self._format_conditions(conditions),
                    "tooltip": event.get("tooltip", ""),
                    "description": event.get(CONF_COMMENT, ""),
                    "icon": event.get(CONF_ICON, "mdi:calendar"),
                    "is_default_bg": False,
                    "z_index": 2,
                    "is_dynamic_color": self._is_dynamic_value(state),
                }
                groups[condition_key].append(block2)
            else:
                # Normal block (no wrapping)
                block = {
                    "event_idx": event_idx,
                    "start": start.strftime("%H:%M"),
                    "end": end.strftime("%H:%M"),
                    "original_start": original_start,
                    "original_end": original_end,
                    "wraps_start": False,
                    "wraps_end": False,
                    "state_value": state,
                    "raw_state_template": self._serialize_template(
                        event.get(CONF_STATE)
                    ),
                    "unit": event.get("unit", ""),
                    "raw_conditions": conditions,
                    "condition_text": self._format_conditions(conditions),
                    "tooltip": event.get("tooltip", ""),
                    "description": event.get(CONF_COMMENT, ""),
                    "icon": event.get(CONF_ICON, "mdi:calendar"),
                    "is_default_bg": False,
                    "z_index": 2,
                    "is_dynamic_color": self._is_dynamic_value(state),
                }
                groups[condition_key].append(block)

        # Convert groups to layers
        layers = []
        for condition_key, blocks in groups.items():
            blocks.sort(key=lambda b: b["start"])
            layers.append(
                {
                    "condition_key": condition_key,
                    "condition_text": blocks[0]["condition_text"] if blocks else "",
                    "blocks": blocks,
                    "is_default_layer": False,
                }
            )

        # Add default layer
        layers.append(self._create_default_layer())
        return layers

    # NEW METHOD: Create default layer
    def _create_default_layer(self):
        """Create the default layer (background)."""
        return {
            "condition_key": "default",
            "condition_text": "default",
            "blocks": [
                {
                    "start": "00:00",
                    "end": "23:59",
                    "original_start": "00:00",
                    "original_end": "23:59",
                    "wraps_start": False,
                    "wraps_end": False,
                    "state_value": self.default_state,
                    "raw_state_template": self._serialize_template(
                        self.config.get(CONF_DEFAULT_STATE)
                    ),
                    "unit": "",
                    "raw_conditions": [],
                    "condition_text": "default",
                    "tooltip": "Default state",
                    "description": "",
                    "icon": self.default_icon,
                    "is_default_bg": True,
                    "z_index": 1,
                    "is_dynamic_color": self._is_dynamic_value(self.default_state),
                }
            ],
            "is_default_layer": True,
        }

    # NEW METHOD: Extract weekdays from conditions
    def _get_weekdays_from_condition(self, conditions):
        """Extract weekdays from time conditions."""
        all_days = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
        if not conditions:
            return all_days

        weekdays = []
        for cond in conditions:
            if (
                isinstance(cond, dict)
                and cond.get("condition") == "time"
                and "weekday" in cond
            ):
                wd = cond["weekday"]
                if isinstance(wd, list):
                    weekdays.extend(wd)
                elif isinstance(wd, str):
                    weekdays.append(wd)

        return weekdays or all_days

    # NEW METHOD: Serialize conditions
    def _serialize_conditions(self, conditions):
        """Serialize conditions to create a unique group key."""
        clean_conditions = []
        for cond in conditions:
            if cond.get("condition") == "time" and "month" in cond:
                clean_conditions.append(cond)
            elif cond.get("condition") != "time":
                clean_conditions.append(cond)

        return (
            yaml.dump(clean_conditions, default_flow_style=False, sort_keys=True)
            if clean_conditions
            else "default"
        )

    # NEW METHOD: Format conditions as readable text with nested support
    def _format_conditions(self, conditions):
        """Format conditions into readable text with support for nested AND/OR/NOT."""
        if not conditions:
            return ""

        def format_single_condition(cond):
            """Format a single condition."""
            if not isinstance(cond, dict):
                return ""

            cond_type = cond.get("condition")

            if cond_type == "state":
                entity_id = cond.get("entity_id", "")
                if isinstance(entity_id, list):
                    entity_id = entity_id[0] if entity_id else ""
                state_value = cond.get("state", "")
                return f"{entity_id} == {state_value}"

            elif cond_type == "numeric_state":
                entity_id = cond.get("entity_id", "")
                conds = []
                if "above" in cond:
                    conds.append(f"> {cond['above']}")
                if "below" in cond:
                    conds.append(f"< {cond['below']}")
                return f"{entity_id} {' AND '.join(conds)}"

            elif cond_type == "time":
                time_parts = []
                if "weekday" in cond:
                    weekdays = cond["weekday"]
                    if isinstance(weekdays, list):
                        abbrs = []
                        for wd in weekdays:
                            abbrs.append(wd.capitalize()[:3])
                        time_parts.append(f"Days: {', '.join(abbrs)}")
                    else:
                        time_parts.append(f"Days: {weekdays.capitalize()[:3]}")
                if "month" in cond:
                    months = cond["month"]
                    if isinstance(months, list):
                        time_parts.append(f"Month: {', '.join(map(str, months))}")
                    else:
                        time_parts.append(f"Month: {months}")

                # IMPORTANT: Return joined parts, not with AND between them
                # Because weekday and month in the same time condition are separate constraints
                return " ".join(time_parts) if time_parts else ""

            elif cond_type == "and":
                sub_conds = cond.get("conditions", [])
                if not sub_conds:
                    return ""
                formatted = [format_single_condition(c) for c in sub_conds]
                formatted = [f for f in formatted if f]
                if len(formatted) == 1:
                    return formatted[0]
                return f"({' AND '.join(formatted)})"

            elif cond_type == "or":
                sub_conds = cond.get("conditions", [])
                if not sub_conds:
                    return ""
                formatted = [format_single_condition(c) for c in sub_conds]
                formatted = [f for f in formatted if f]
                if len(formatted) == 1:
                    return formatted[0]
                return f"({' OR '.join(formatted)})"

            elif cond_type == "not":
                sub_cond = cond.get("condition", None)
                if sub_cond:
                    formatted = format_single_condition(sub_cond)
                    return f"NOT {formatted}" if formatted else ""
                sub_conds = cond.get("conditions", [])
                if sub_conds:
                    formatted = format_single_condition(sub_conds[0])
                    return f"NOT {formatted}" if formatted else ""
                return ""

            return ""

        # Process all conditions
        parts = []
        for cond in conditions:
            formatted = format_single_condition(cond)
            if formatted:
                parts.append(formatted)

        if len(parts) == 0:
            return ""
        elif len(parts) == 1:
            return parts[0]
        else:
            return " AND ".join(parts)

    # NEW METHOD: Detect dynamic values
    def _is_dynamic_value(self, value):
        """Detect if value is dynamic (template or entity reference)."""
        if not value or not isinstance(value, str):
            return False

        value_str = str(value).strip()
        return (
            "states(" in value_str
            or "state_attr(" in value_str
            or "{{" in value_str
            or "{%" in value_str
        )

    def _get_intervals(self, start, end, allow_wrap):
        ret = P.Interval()
        error = None

        if start < end:
            ret = ret.union(P.closedopen(start, end))
        elif start == end:
            pass
        elif allow_wrap:
            ret = ret.union(P.closedopen(start, time.max))
            ret = ret.union(P.closedopen(time.min, end))
        else:
            error = f"error with event definition - start:{start} > end:{end}"

        return ret, error

    def _add_interval(self, states, attrs, event, state, interval) -> None:
        states[interval] = state

        # process custom attributes
        for xattr in self._attr_keys:
            attr_val = event.get(xattr, None)

            # figure out the attribute value
            val = None
            if attr_val is not None:
                attr_eval = self.evaluate_template(
                    {xattr: attr_val},
                    xattr,
                    default=None,
                )
                if attr_eval.success:
                    val = attr_eval.result

            if val is None:
                # no value specified or template evaluation failed; get the default value
                # the default here if the template evaluation fails is the "template" itself - YMMV
                dv = self.extra_attributes[xattr]
                val = self.evaluate_template(
                    {xattr: dv},
                    xattr,
                    default=dv,
                ).result

            if val is not None:
                attrs[xattr][interval] = val

    async def get_start(self, event) -> time:
        template_eval = self.evaluate_template(
            event,
            CONF_START,
            time.min,
        )
        if not template_eval.success:
            return None

        inferred_time = self.guess_value(template_eval.result)
        if inferred_time is None:
            _LOGGER.error(
                f"{self.name}: FAILED - could not parse '{template_eval.template}'"
            )
        return inferred_time

    async def get_end(self, event) -> time:
        template_eval = self.evaluate_template(
            event,
            CONF_END,
            time.max,
        )
        if not template_eval.success:
            return None

        inferred_time = self.guess_value(template_eval.result)
        if inferred_time is None:
            _LOGGER.error(
                f"{self.name}: FAILED - could not parse '{template_eval.template}'"
            )
        return inferred_time

    def apply_offset(self, t: time, offset: int):
        # constant gymnastics between datetime and time. yuck.
        d = datetime_from_time(t)
        d += timedelta(minutes=offset)
        return d.time()

    def evaluate_template(
        self,
        obj,
        prefix: str,
        default=None,
        track_entities: bool = True,
    ) -> TemplateResult:
        value = obj.get(prefix, None)

        debugmsg = ""

        if value is None:
            debugmsg = "(default)"
            ret = TemplateResult(value, default, True)

        elif not isinstance(value, Template):
            debugmsg = "(value)"
            ret = TemplateResult(None, value, True)

        else:
            value.hass = self.hass
            try:
                info = value.async_render_to_info(None, parse_result=False)
            except (ValueError, TypeError, TemplateError) as e:
                _LOGGER.error(
                    f"{self.name}: ... >> {prefix}: failed[1] to evaluate: {e}"
                )
                ret = TemplateResult(value, default, False)
            else:
                try:
                    ret = TemplateResult(value, info.result(), True)
                except Exception as e:
                    _LOGGER.error(
                        f"{self.name}: ... >> {prefix}: failed[2] to evaluate: {e}"
                    )
                    ret = TemplateResult(value, default, False)

            if ret.success and track_entities:
                if len(info.entities):
                    debugmsg += f" -- entities used: {info.entities}"
                for e in info.entities:
                    self.entities.add(e)

        if ret.success:
            _LOGGER.debug(f"{self.name}: >> {prefix}: {ret.result} {debugmsg}")
        return ret

    def guess_value(self, value) -> time | None:
        """After evaluating a template, try to figure out what the resulting value means.
        We are looking for a time value. Dates don't matter."""

        if not isinstance(value, str):
            return value

        with suppress((ValueError, TypeError)):
            date = dt.parse_datetime(value)
            if date is not None:
                _LOGGER.debug(f"{self.name}: ...... found datetime: {date}")
                tme = dt.as_local(date).time()
                return tme

        with suppress((ValueError, TypeError)):
            date = datetime.fromisoformat(value)
            _LOGGER.debug(f"{self.name}: ...... found isoformat date: {date}")
            tme = dt.as_local(date).time()
            return tme

        with suppress((ValueError, TypeError)):
            tme = dt.parse_time(value)
            if tme is not None:
                _LOGGER.debug(f"{self.name}: ...... found time: {tme}")
                return localtime_from_time(tme)

        with suppress((ValueError, TypeError)):
            tme = time.fromisoformat(value)
            if tme is not None:
                _LOGGER.debug(f"{self.name}: ...... found isoformat time: {tme}")
                return localtime_from_time(tme)

        try:
            date = dt.utc_from_timestamp(int(float(value)))
            _LOGGER.debug(f"{self.name}: ...... found timestamp: {date}")
            tme = dt.as_local(date).time()
            return tme
        except:  # noqa: E722
            pass

        return None

    async def update(self):
        """Get the latest state based on the event schedule."""
        now = dt.as_local(dt_now())
        nu = time(now.hour, now.minute)

        # clear out overrides that have expired
        self.overrides = [o for o in self.overrides if dt.as_local(o["expires"]) > now]
        for o in self.overrides:
            _LOGGER.debug(
                f"{self.name}: override = {o['start']} - {o['end']} == {o['state']} [expires {o['expires']}]"
            )

        # periodically re-evaluate (refresh) the schedule
        self.attributes = {}
        time_since_refresh = now - self._refresh_time
        if time_since_refresh.total_seconds() >= self.refresh.total_seconds() or (
            self.force_refresh is not None and now > self.force_refresh
        ):
            await self.process_events()
            self.force_refresh = None

        # find the state and interval that matches the current time
        state, interval = self.find_interval(self._states, nu)

        _LOGGER.debug(f"{self.name}: current state is {state} ({nu})")
        self.value = state
        self.attributes["start"] = interval.lower
        self.attributes["end"] = interval.upper
        self.attributes["icon"] = self.icon_map.get(state, None)

        look_for_next_state = True
        next_nu = (datetime.combine(now, interval.upper) + timedelta(seconds=1)).time()

        if interval.upper == time.max:
            # If the interval ends at midnight, peek ahead to the next day.
            # This won't necessarily be right, because the schedule could be recalculated
            # the next day, but it is arguably more useful.
            next_state, next_i = self.find_interval(self._states, time.min)
            if next_state == state:
                self.attributes["end"] = next_i.upper
                next_nu = (
                    datetime.combine(now, next_i.upper) + timedelta(seconds=1)
                ).time()
            else:
                self.attributes["next_state"] = next_state
                look_for_next_state = False

        if look_for_next_state:
            next_state, next_i = self.find_interval(self._states, next_nu)
            self.attributes["next_state"] = next_state

        # process extra attributes
        for attr in self._attr_keys:
            # find an event in which the attribute is defined
            val, _ = self.find_interval(self._custom_attributes[attr], nu)
            self.attributes[attr] = val

    def find_interval(self, states, nu):
        for k, v in states.items():
            for interval in k._intervals:
                if nu >= interval.lower and nu < interval.upper:
                    return v, interval

        _LOGGER.error(f"{nu} not in {states}")
        return None, None

    def set_override(self, id, state, start, end, duration, icon, extra_attributes):
        now = dt.as_local(dt_now())

        # Unlike standard events, overrides do not have an "allow_wrap" attribute.
        # Wrapping is generally permitted by default for overrides, unless both
        # start and end are provided, in which case the global "allow_wrap" setting
        # for the sensor is used.
        allow_wrap = True

        # You could end up with weird/unexpected results if the duration wrapped more than
        # one day, which is why the maximum is set to 1439 minutes (24 hours minus 1 minute).

        # FIXME weed out invalid cases using Voluptuous schema
        if start is None and end is None and duration is None:
            # 000
            _LOGGER.error("override failed: must provide one of start/end/duration")
            return False
        elif start is not None and end is not None and duration is not None:
            # 111
            _LOGGER.error("override failed: cannot provide start+end+duration together")
            return False
        elif start is None and end is None and duration is not None:
            # 001 --> now to now+d
            start = simple_time(now)
            end = start + timedelta(minutes=duration)
        elif start is not None and end is None and duration is not None:
            # 101 --> start to start+d
            start = next_time(now, start)
            end = start + timedelta(minutes=duration)
        elif start is None and end is not None and duration is not None:
            # 011 --> end-d to end
            end = next_time(now, end)
            start = end - timedelta(minutes=duration)
        elif start is None and end is not None and duration is None:
            # 010 --> now to end
            start = next_time(now, now)
            end = next_time(now, end)
        elif start is not None and end is not None and duration is None:
            # 110 --> start to end
            # don't try to fix wraparounds in this case, where both start and end times were provided
            start = next_time(now, start)
            end = next_time(now, end)
            allow_wrap = self.config.get(CONF_ALLOW_WRAP, False)
        else:
            # 100 --> start to ???
            _LOGGER.error("override failed: no duration provided")
            return False

        start = start.time()
        expires = end + timedelta(seconds=30)
        end = end.time()

        # filter extra_attributes passed in by the service call and issue warnings for unknown attributes
        if extra_attributes is not None:
            ex_attrs = {}
            for attr in self._attr_keys:
                v = extra_attributes.get(attr, None)
                if v is not None:
                    ex_attrs[attr] = v
                else:
                    _LOGGER.debug(f"skipping {attr} because value = {v}")

            for attr in extra_attributes.keys():
                if attr not in self._attr_keys:
                    _LOGGER.error(
                        f"{self.name}: ignoring unknown attribute '{attr}' in service call"
                    )

            extra_attributes = ex_attrs

        else:
            extra_attributes = {}

        if end > start or (allow_wrap and start > end):
            ev = Override(id, state, start, end, expires, icon, extra_attributes)
            self._add_or_edit_override(id, ev)
            if allow_wrap:
                ev[CONF_ALLOW_WRAP] = True
        else:
            _LOGGER.error(f"override failed: start ({start}) & end ({end})")
            return False

        return True

    def remove_override(self, id: str):
        # find and delete overrides with id
        idxs = self._find_override_by_id(id)
        if idxs is None:
            _LOGGER.warning(f"{self.name}: remove_override id={id} not found")
            return False
        for idx in reversed(sorted(idxs)):
            self.overrides.pop(idx)
        return True

    def _add_or_edit_override(
        self, id: str, ev: Override, expect_duplicate_id: bool = False
    ):
        # search for an override with id; if it exists, modify it, else add a new one
        idxs = self._find_override_by_id(id)
        if idxs is None or expect_duplicate_id:
            self.overrides.append(ev)
        else:
            idxs = [idx for idx in sorted(idxs)]
            idx = idxs.pop(0)
            self.overrides[idx] = ev
            for idx in reversed(sorted(idxs)):
                self.overrides.pop(idx)

    def _find_override_by_id(self, id: str):
        if id is None:
            return None
        idx = [idx for idx, el in enumerate(self.overrides) if el["id"] == id]
        if len(idx):
            return idx
        else:
            return None

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
    v = d + timedelta(days=1)
    return datetime(v.year, v.month, v.day)


def localtime_from_time(tme: time) -> time:
    return datetime_from_time(tme).time()


def datetime_from_time(tme: time) -> datetime:
    date = dt_now()
    date = datetime.combine(date, tme, date.tzinfo)
    return dt.as_local(date)


def friendly_time(t):
    """Simple time formatting so that you don't have to do it in Lovelace everywhere.
    For more advanced uses, you can use the start/end attributes instead of the friendly versions.
    """
    # TODO translations...
    if t is None:
        return "-"
    elif t == time.max:
        return "midnight"
    return t.strftime(locale.nl_langinfo(locale.T_FMT))


async def _async_process_cond(hass, name, cond, entities):
    if cond is None:
        # no condition provided - always evaluates to True
        return True

    _LOGGER.debug(f"{name}: condition {cond}")
    variables = {}
    cond_func = await _async_process_if(hass, name, cond)
    for conf in cond_func.config:
        referenced = condition.async_extract_entities(conf)
        if len(referenced):
            _LOGGER.debug(f"{name}: ... entities used: {referenced}")
        entities.update(referenced)

    cond_result = cond_func(variables)
    return cond_result


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
                with trace_path(["condition", str(index)]):
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
            return None

        return True

    if_action.config = if_configs

    return if_action


def dt_now():
    """Return now(). Tests will override the return value."""
    return dt.now()
