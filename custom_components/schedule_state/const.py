"""Constants for schedule_state integration"""

DOMAIN = "schedule_state"

PLATFORMS = ["sensor"]

DEFAULT_NAME = "Schedule State Sensor"
DEFAULT_STATE = "default"
DEFAULT_ICON = "mdi:calendar-check"
DEFAULT_ERROR_ICON = "mdi:calendar-alert"

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
CONF_MINUTES_TO_REFRESH_ON_ERROR = "minutes_to_refresh_on_error"
CONF_EXTRA_ATTRIBUTES = "extra_attributes"
