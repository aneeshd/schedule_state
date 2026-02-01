import logging
from pprint import pformat

from homeassistant.core import HomeAssistant

from .test_schedule import load_config

_LOGGER = logging.getLogger(__name__)


async def test_thermostat(hass: HomeAssistant):
    await load_config(hass, "tests/../config/schedules/thermostat.yaml")

    sensor = [e for e in hass.data["sensor"].entities][-1]
    day = "mon"
    day_layer = sensor.data.layers_by_day[day]

    dump_sched(sensor, day_layer)

    hass.states.async_set("input_boolean.vacation_mode", "on")
    await hass.async_block_till_done()

    day_layer = sensor.data.layers_by_day[day]
    dump_sched(sensor, day_layer)


def dump_sched(sensor, layers):
    text = "\n"
    for layer in layers:
        text += (layer["condition_text"] or "(no condition)") + "\n"
        is_default_layer = layer["is_default_layer"]
        default = " * " if is_default_layer else "   "
        for block in layer["blocks"]:
            event_idx = str(block["event_idx"]) if not is_default_layer else "-"
            text += f"{event_idx:4s}{default}{block['state_value']:20s}{block['start']:6s} - {block['end']:6s}\n"
    _LOGGER.info(text)
    _LOGGER.info("\n" + pformat(list(sensor.data._states.items())))
