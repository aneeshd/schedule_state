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

SVG_START = (
    f'<svg xmlns="http://www.w3.org/2000/svg" width="1440" height="{RIBBON_HEIGHT}">'
)
SVG_END = "</svg>"
PREFIX = "data:image/svg+xml,"

RULER_COLORS = ["rgb(26,73,205)", "rgb(12,36,100)"]

START_OF_DAY = 0
END_OF_DAY = 24 * 60


def draw_schedule_as_svg(states, total_states, palette_name="viridis"):
    """Draw the schedule. Widths are in mintes. Heights are controlled by the contants above.
    Colormap currently hard-coded to Viridis (https://cran.r-project.org/web/packages/viridis/vignettes/intro-to-viridis.html)"""

    # create a ruler along the top, alternating colors for each hour
    ruler = ""
    for i in range(24):
        ruler += f'<rect x="{i*60}" y="{RULER_Y}" width="60" height="{RULER_HEIGHT}" style="fill:{RULER_COLORS[i%2]};stroke-width:0">'
        ruler += f"<title>{i}h</title></rect>"

    # generate the palette of colors to be used for the schedule events
    palette_data = viridis_data
    palette_idx = gen_idx(len(palette_data), total_states)
    state_color = {}
    stroke_color = {}
    for idx, state in zip(palette_idx, sorted(states.keys())):
        d = [int(x * 256) for x in palette_data[idx]]
        state_color[state] = f"rgb({d[0]},{d[1]},{d[2]})"
        # make a darker version for the outline - there are probably smarter ways to do this
        d = [int(x * 224) for x in palette_data[idx]]
        stroke_color[state] = f"rgb({d[0]},{d[1]},{d[2]})"

    # plot the schedule events
    schedule = ""
    for state in states:
        for i in states[state]._intervals:
            x1 = to_minutes(i.lower)
            x2 = to_minutes(i.upper)
            if x2 != END_OF_DAY:
                x2 -= 1

            if x2 > x1:
                width = x2 - x1
                schedule += f'<rect x="{x1}" y="{SCHEDULE_Y}" width="{width}" height="{SCHEDULE_HEIGHT}" style="fill:{state_color[state]};stroke-width:4;stroke:{stroke_color[state]}">'
                schedule += f"<title>{state}</title></rect>"
                # text becomes squished due to x-scaling
                # schedule += f'<text x="{(x1+x2)/2}" y="{SCHEDULE_Y+SCHEDULE_HEIGHT/2}">{state}</text>'
            # _LOGGER.info(f"{state}: {x1} - {x2}")

    data = (SVG_START + ruler + schedule + SVG_END).strip()
    encoded = PREFIX + urllib.parse.quote(data)
    return encoded, data


#     # assemble and encode
#     data = ruler + schedule
#     return data


# DELETE: seems to flicker, doesn't look great
# def update_svg(data, now):
#     """Add a marker to indicate current time of day. Encode and return."""
#     minutes = to_minutes(now)
#     x1 = minutes - 10
#     width = 20
#     marker = f'<rect x="{x1}" y="{SCHEDULE_Y-5}" width="{width}" height="{SCHEDULE_HEIGHT+10}" style="fill:none;stroke-width:10;stroke:black"/>'
#     data = (SVG_START + data + marker + SVG_END).strip()
#     encoded = PREFIX + urllib.parse.quote(data)
#     return encoded, data


def gen_idx(total, num):
    """Generate equidistant palette indices"""
    upper = total + 1
    num -= 1
    return [0] + [x * (upper // num) for x in range(1, num)] + [total - 1]


def to_minutes(x):
    """helper to convert a portion bound to minute of the day"""
    if isinstance(x, time):
        return round(x.hour * 60 + x.minute + x.second / 60)
    elif x < 0:  # -inf
        return START_OF_DAY
    else:  # +inf
        return END_OF_DAY
