"""Constants for schedule_state integration"""

from homeassistant.const import CONF_CONDITION, CONF_NAME, CONF_STATE, ATTR_ENTITY_ID
from datetime import timedelta

DOMAIN = "schedule_state"

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
