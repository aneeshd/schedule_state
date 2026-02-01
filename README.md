# Schedule State for Home Assistant

A custom component for Home Assistant that simplifies the creation of schedule-based automations.

It takes a very different approach from other projects of this type, because it only provides
scheduling functionality. It does not try to replace the powerful [automations](https://www.home-assistant.io/docs/automation/)
framework that Home Assistant provides.

Instead, it separates the concepts of *when* you want something done,
and *what* to do when that state arrives. Use `schedule_state` to handle the *when*,
and standard Home Assistant tools to handle the *what*.

`schedule_state` allows you to create sensors that provide arbitrary values,
based on the time of day and other criteria. Home Assistant can then use the state of these
sensors to trigger other automations.

You should also check out [schedule-state-card](https://github.com/Pulpyyyy/schedule-state-card), which provides a nice
GUI for the sensors defined with `schedule_state`.

***

[![GitHub Release][releases-shield]][releases]
[![GitHub Activity][commits-shield]][commits]
[![GitHub Issues][issues-shield]][issues]
[![License][license-shield]](LICENSE)

[![hacs][hacsbadge]][hacs]
![Project Maintenance][maintenance-shield]
[![BuyMeCoffee][buymecoffeebadge]][buymecoffee]

[![Community Forum][forum-shield]][forum]

***

## Installation

Using [HACS](https://hacs.xyz/):

1. Go to the HACS integration page
2. Click on "Explore & Download Repositories"
3. Search for "Schedule State" and add it
4. Restart Home Assistant

## Configuration

Configuration is done via YAML files. It seems safer to keep your custom
configuration in a separate file, so add an entry in `configuration.yaml`:

```yaml
sensor: !include sensors.yaml
```

Put configuration for `schedule_state`, and any other custom sensors, in `sensors.yaml`.

Create a `schedule_state` sensor:

```yaml
  - platform: schedule_state
    name: Some descriptive name
    # refresh: "6:00:00"                # this is the default
    # default_state: default            # this is the default
    # icon: mdi:calendar-check          # this is the default
    # error_icon: mdi:calendar-alert    # this is the default
    # minutes_to_refresh_on_error: 5    # this is the default
    # allow_wrap: False                 # this is the default
```

By default, the sensor returns the name provided as the `default_state`. Configuration is built up in layers of events.
Events have a `start` time and `end` time, and cause the sensor to report a new `state` name.

All times are interpreted as belonging to the local timezone.

The start and end times can be adjusted with an offset, in minutes, using the `start_offset`/`end_offset` settings.
This helps define events such as "x minutes before sunrise", in a simpler way than using complicated templates.
These offsets can also be specified as templates.

This simple configuration will cause the sensor to report `sleep` or `awake` depending on the time of day.
You can create automations that trigger on the sensor state. Or, you can use the value of the sensor state as a
condition in your automations.

Each state can have a custom icon.
Pick any icon that you can find on [pictogrammers.com](https://pictogrammers.com/library/mdi/) and prefix the name with `mdi:`.

Note: As of 0.20.2, `schedule_state` will use the icon specified in the "active" event. If an icon was not provided, it
will use the first icon specified for that state, defaulting to the default icon for the sensor. This is different from the
previous behaviour, in which the last icon assigned to a state was used for all occurrences of that state.

```yaml
    events:
      - start: "0:00"
        end: "5:30"
        state: sleep
        icon: mdi:sleep
      - start: "5:30"
        end: "22:30"
        state: awake
        icon: mdi:walk
      - start: "22:30"
        state: sleep
```

If `start` is not provided, it defaults to the start of the day, and if `end` is not provided, it defaults to the end of the day.

By default, it is required that end times are larger than start times. However, by setting the `allow_wrap` attribute to True, events
can be made to "wrap" to the next day. This can be a more convenient or intuitive way to specify events that run from evening to morning.

For example, the `sleep` state in the example could be specified as follows:

```yaml
    events:
      - start: "22:30"
        end: "5:30"
        state: sleep
        icon: mdi:sleep
        allow_wrap: True
      - start: "5:30"
        end: "22:30"
        state: awake
        icon: mdi:walk
```

There can be some unexpected behaviour, however, when using conditions and templates in conjunction with this feature (see below).

The `allow_wrap` setting can be specified at either the sensor level or for a particular event.

Note: Make sure that times are quoted!

![schedule1][schedule1img]

Events can be defined in any order. If an event is created that overlaps with existing events, the existing events are re-sized to
accommodate the new event.

To continue the previous example:

```yaml
      - start: "13:30"
        end: "14:30"
        state: sleep
```

This will carve out a 1 hour naptime, and create two `awake` times (5:30-13:30 and 14:30-22:30).

![schedule2][schedule2img]

Finally, events can be [conditional](https://www.home-assistant.io/docs/scripts/conditions/).
Any condition logic supported by Home Assistant can be used.
This makes it easy to make different schedules for
weekends or [holidays](https://www.home-assistant.io/integrations/workday/).

```yaml
      # weekends
      - start: "0:00"
        end: "8:00"
        state: sleep
        condition: &weekend
          condition: time
          weekday:
            - sat
            - sun
```

Note that Home Assistant will evaluate conditions based on the current time of day. In this particular example, the
condition evaluates to true if the current time is between 0:00:00 on Saturday and 23:59:59 on Sunday.
You will need to take this into account if you use the `allow_wrap` feature described above to conditionally
wrap an event from Friday evening to Saturday morning, for example.

Keep in mind that the evaluation order of the events is top-to-bottom, and all of them are evaluated. This means
that if multiple events match the settings, it's the last one that "wins". For example, if you put this as your
_last_ event in your configuration, it can be used to override all the events above it, only by using a `binary_sensor`
(note how there are no `start` and `end` parameters - matching all day if condition passes):

```yaml
      - state: away_mode
        condition:
          - condition: state
            entity_id: binary_sensor.family_at_home
            state: 'off'
```

Conditions are re-evaluated whenever the state of any entities referenced in the condition change.

The icon of the `schedule_state`
sensor will change to an "alert" (`mdi:calendar-alert`) if an error is detected while evaluating the condition.
This indicates that the condition definition may need to be examined.

## Templates

State values, start, and end times can be specified using [templates](https://www.home-assistant.io/docs/configuration/templating/).
Simply use a template for any `state`, `default_state`, `start`, or `end` definition.

The template value must evaluate to one of these data types:

| Format    | Comments                     |
|-----------|------------------------------|
| datetime  | A string that HA or Python can understand as a `datetime`. Only the time portion is used. |
| time      | A string that HA or Python can understand as a `time`. |
| timestamp | A number that will be interpreted as a timestamp. This will be converted to a `datetime` and only the time portion is used. |

All times are converted to the local timezone.

This is an example of a sensor that provides `day` or `night` states based on data from
the [sun integration](https://www.home-assistant.io/integrations/sun/).

```yaml
    events:
      - state: night
      - start: "{{ as_timestamp(state_attr('sun.sun', 'next_rising')) }}"
        end: "{{ as_timestamp(state_attr('sun.sun', 'next_setting')) }}"
        state: day
```

Template values are refreshed at every `refresh` interval, or immediately whenever the state of any entities referenced in the template change.

Sometimes, errors can occur when evaluating valid templates. This is because Home Assistant may not yet have loaded the entities on
which the template depends. `schedule_state`
will re-evaluate the template again in a few minutes to guard against this condition. This gives HA some time to start everything up.

Of course, it is possible that the template is not valid, but `schedule_state` cannot yet differentiate between these two scenarios.
The icon of the `schedule_state` sensor will change to an "alert" (`mdi:calendar-alert`) to indicate that the template definition
may need to be examined. In a future version, this force-refresh strategy may incorporate a timeout.

`schedule_state` will ask Home Assistant to delay loading it until after the following integrations have been loaded:

 - binary_sensor
 - input_boolean
 - input_button
 - input_datetime
 - input_number
 - input_select
 - input_text
 - sun
 - zone


## State and Attributes

### `state`

The `state` contains the current state of the schedule.

### Attributes

These custom attributes are available, in addition to the more common `friendly_name` and `icon` attributes.

| Attribute        | Description                                                               |
| :--------------- | ------------------------------------------------------------------------- |
| `states`         | All states known to the sensor |
| `next_state`     | The state that will occur after the current state |
| `start`          | Start time of current state |
| `end`            | End time of current state |
| `friendly_start` | Start time of current state as a string, formatted using your local conventions |
| `friendly_end`   | End time of current state as a string, formatted using your local conventions |
| `errors`         | List of any events with configuration errors |

`start` and `end` return [`datetime.time`](https://docs.python.org/3/library/datetime.html#time-objects) objects,
allowing templates to access `.hour`, `.minute`, and other attributes of the `time` object.

`friendly_end` will return `'midnight'` if the event ends at the end of the day instead of the less useful
`'23:59:59.999999'` returned by `end` in earlier versions.

### Custom Attributes

`schedule_state` can be configured to publish user-defined attributes with each event.

```yaml
  - platform: schedule_state
    extra_attributes:
      # attributes and their default values can be defined here - templates are allowed for values
      fan_mode: "off"
      swing_mode: "off"
    events:
      - start: "5:00" # intentional overlap
        end: "22:30"
        state: "temp_day"
        fan_mode: "high"
        # swing_mode will use default value ("off")
      - start: "23:19"
        state: "temp_evening"
        # attribute values - templates are allowed for values
        swing_mode: "horizontal"
        fan_mode: "{{ iif(is_state('input_boolean.mode', 'on'), 'mid', 'very-high', 'broken') }}"
```

Attributes are evaluated with the same top-to-bottom logic as states. If an attribute is not
provided for an event, the attribute value reverts to the default.

_Tip:_ You can add Home Assistant-specific attributes too. For example if you schedule target temperature values, this will make it display a graph:

```yaml
    extra_attributes:
      unit_of_measurement: "°C"
      state_class: measurement
```

## Lovelace Ideas

Here is an example of using a Jinja template in Lovelace to display the current state and the time at which it expires:

![chip_with_template][chip_with_template_img]:

```yaml
  - type: custom:mushroom-chips-card
    chips:
      - type: template
        entity: sensor.my_schedule
        content: >-
          ⏱️ {{ states(config.entity) | title }} until {{
          state_attr(config.entity, 'friendly_end') }}
```

This example uses a [Mushroom card with a template chip](https://github.com/piitaya/lovelace-mushroom/blob/main/docs/cards/chips.md#template-chip), but the concept works with any Lovelace card that supports templates.

You should also check out [schedule-state-card](https://github.com/Pulpyyyy/schedule-state-card), which provides a nice
GUI for the sensors defined with `schedule_state`.

## Actions (Services)

### `recalculate`

Forces the schedule to be recalculated. This is useful if you have conditionals or templates
in the schedule definition, and you would like the schedule to be updated based on these changes.

This is cleaner than re-loading, as it prevents the sensor from becoming "unavailable".

Note: `schedule_state` will (should) automatically reload the schedule definition if any
referenced conditionals or templates have been updated. As a result, this service should
not be needed if everything is working properly.

### `set_override`

Temporarily schedule the sensor to report a given value, overriding the schedule definition.

The override can be specified in four different ways:

| Data Provided   | Meaning |
|-----------------|---------|
| duration        | Override for `duration` minutes, starting now. |
| start, duration | Override for `duration` minutes, starting at the next occurrence of `start`. |
| end, duration   | Override for `duration` minutes, ending at the next occurrence of `end`. |
| start, end      | Override from the next occurrence to `start` to the next occurrence of `end`. |

Other data required for this service call:

| Data             | Meaning |
|------------------|---------|
| state            | The state to apply for this override |
| id               | Optionally provide an ID for the override. |
| icon             | Optionally provide an icon for this override |
| extra_attributes | Optionally provide a `dict` of extra attributes for this override |

If ID is provided, and there is already an override with that ID, the override is modified in-place.
This maintains the override's ordering in the evaluation order.

Providing an ID also allows the override to be removed later via a service call.


### `remove_override`

Remove the override with the specified ID.

| Data             | Meaning |
|------------------|---------|
| id               | The override to remove |

### `clear_overrides`

Clears any overrides defined for the schedule.

## Development Notes

There are (at least) 3 modes in which development and testing can be performed.

 - Standalone using pytest, `schedule_state`, and its dependencies
 - Home Assistant [devcontainer](https://developers.home-assistant.io/docs/development_environment)
 - A real Home Assistant instance

This section provides some notes on each type of development environment, mostly as a reminder for me.

### pytest

Use [poetry](https://python-poetry.org/) and the provided `pyproject.toml` to setup the development environment

 - `poetry install`
 - `poetry shell`
 - `pytest tests`

### devcontainer

 - Open `schedule_state` repo in VS Code
 - Re-open in container
 - Use standard [devcontainer](https://developers.home-assistant.io/docs/development_environment) development methods

### On a real HA instance

Code changes require HA to be re-started, so try to get as much fixed as possible using either of the two previous methods.

Enable logging for `schedule_state`:

```yaml
logger:
  default: warning
  logs:
    custom_components.schedule_state: debug
```

## Contributions are welcome!

If you want to contribute to this please read the [Contribution guidelines](CONTRIBUTING.md)

***

[schedule_state]: https://github.com/aneeshd/schedule_state
[issues-shield]: https://img.shields.io/github/issues/aneeshd/schedule_state
[forks-shield]: https://img.shields.io/github/forks/aneeshd/schedule_state
[stars-shield]: https://img.shields.io/github/stars/aneeshd/schedule_state
[commits-shield]: https://img.shields.io/github/commit-activity/y/aneeshd/schedule_state.svg
[commits]: https://github.com/aneeshd/schedule_state/commits/main
[buymecoffee]: https://www.buymeacoffee.com/aneeshd
[buymecoffeebadge]: https://img.shields.io/badge/buy%20me%20a%20coffee-donate-yellow.svg
[hacs]: https://github.com/hacs/integration
[hacsbadge]: https://img.shields.io/badge/HACS-Custom-orange.svg
[forum-shield]: https://img.shields.io/badge/community-forum-brightgreen.svg
[forum]: https://community.home-assistant.io/
[license-shield]: https://img.shields.io/github/license/aneeshd/schedule_state
[maintenance-shield]: https://img.shields.io/badge/maintainer-aneeshd-blue.svg
[releases-shield]: https://img.shields.io/github/v/release/aneeshd/schedule_state.svg
[releases]: https://github.com/aneeshd/schedule_state/releases
[issues]: https://github.com/aneeshd/schedule_state/issues
[schedule1img]: https://raw.githubusercontent.com/aneeshd/schedule_state/main/docs/schedule1.png
[schedule2img]: https://raw.githubusercontent.com/aneeshd/schedule_state/main/docs/schedule2.png
[chip_with_template_img]: https://raw.githubusercontent.com/aneeshd/schedule_state/main/docs/chip_with_template.png
