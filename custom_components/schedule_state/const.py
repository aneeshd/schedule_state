"""Constants for schedule_state integration"""

from datetime import timedelta

from homeassistant.const import (
    ATTR_ENTITY_ID,
    CONF_CONDITION,
    CONF_ICON,
    CONF_NAME,
    CONF_STATE,
)

DOMAIN = "schedule_state"

PLATFORMS = ["sensor"]

DEFAULT_NAME = "Schedule State Sensor"
DEFAULT_STATE = "default"

CONF_EVENTS = "events"
CONF_START = "start"
CONF_START_TEMPLATE = "start_template"
CONF_END = "end"
CONF_END_TEMPLATE = "end_template"
CONF_DEFAULT_STATE = "default_state"
CONF_REFRESH = "refresh"
CONF_COMMENT = "comment"
CONF_DURATION = "duration"
CONF_ERROR_ICON = "error_icon"
