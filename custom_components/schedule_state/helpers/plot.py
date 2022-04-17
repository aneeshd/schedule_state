"""Helper to convert a schedule to an SVG representation"""

from datetime import time
import urllib.parse
from .colormaps import *

# import logging

# _LOGGER = logging.getLogger(__name__)

RIBBON_HEIGHT = 40
GAP = 5
RULER_HEIGHT = 6
RULER_Y = 0
SCHEDULE_HEIGHT = RIBBON_HEIGHT - RULER_HEIGHT - GAP
SCHEDULE_Y = RULER_HEIGHT + GAP


def draw_schedule_as_svg(states, total_states=0, palette_name="viridis"):
    """Draw the schedule. Widths are in mintes. Heights are controlled by the contants above.
    Colormap currently hard-coded to Viridis (https://cran.r-project.org/web/packages/viridis/vignettes/intro-to-viridis.html)"""

    SVG_START = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="1440" height="{RIBBON_HEIGHT}">'
    )
    SVG_END = "</svg>"

    # create a ruler along the top, alternating colors for each hour
    RULER_COLORS = ["rgb(26,73,205)", "rgb(12,36,100)"]
    ruler = ""
    for i in range(24):
        ruler += f'<rect x="{i*60}" y="{RULER_Y}" width="60" height="{RULER_HEIGHT}" style="fill:{RULER_COLORS[i%2]};stroke-width:0" />'

    # generate the palette of colors to be used for the schedule events
    palette_data = viridis_data
    palette_idx = gen_idx(len(palette_data), total_states or len(states))
    state_color = {}
    stroke_color = {}
    for idx, state in zip(palette_idx, sorted(states.keys())):
        d = [int(x * 256) for x in palette_data[idx]]
        state_color[state] = f"rgb({d[0]},{d[1]},{d[2]})"
        # make a darker version for the outline - there are probably smarter ways to do this
        d = [int(x * 224) for x in palette_data[idx]]
        stroke_color[state] = f"rgb({d[0]},{d[1]},{d[2]})"

    # plot the schedule events
    def to_minutes(x):
        """helper to convert a portion bound to minute of the day"""
        if isinstance(x, time):
            return x.hour * 60 + x.minute
        elif x < 0:  # -inf
            return 0
        else:  # +inf
            return 24 * 60

    schedule = ""
    for state in states:
        for i in states[state]._intervals:
            x1 = to_minutes(i.lower)
            x2 = to_minutes(i.upper)
            width = x2 - x1
            schedule += f'<rect x="{x1}" y="{SCHEDULE_Y}" width="{width}" height="{SCHEDULE_HEIGHT}" style="fill:{state_color[state]};stroke-width:4;stroke:{stroke_color[state]}">'
            schedule += f"<title>{state}</title></rect>"

    # assemble and encode
    data = SVG_START + ruler + schedule + SVG_END
    data = urllib.parse.quote(data.strip())
    PREFIX = "data:image/svg+xml,"
    return PREFIX + data


def gen_idx(total, num):
    """Generate equidistant palette indices"""
    upper = total + 1
    num -= 1
    return [0] + [x * (upper // num) for x in range(1, num)] + [total - 1]
