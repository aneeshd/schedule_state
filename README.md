# Schedule State for Home Assistant

A custom component for Home Assistant that simplifies the creation of schedule-based automations.

It takes a very different approach from other projects of this type, because it only provides
scheduling functionality. It does not try to replace the powerful [automations](https://www.home-assistant.io/docs/automation/)
framework that Home Assistant provides.

Instead, it separates the concepts of *when* you want something done,
and *what* to do when that state arrives. Use `schedule_state` to handle the *when*,
and standard Home Assistant tools to handle the *what*.

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

Using HACS:

1. Go to the HACS integration page
2. Add `https://github.com/aneeshd/schedule_state` as a custom repository

## Configuration

Configuration is done via YAML files. It seems safer to keep your custom
configuration in a separate file, so add an entry in `configuration.yaml`:

```
sensor: !include sensors.yaml
```

Put configuration for `schedule_state`, and any other custom sensors, in `sensors.yaml`.

Create a `schedule_state` sensor:

```
  - platform: schedule_state
    name: Some descriptive name
    refresh: "6:00:00"       # this is the default
    default_state: default   # this is the default
```

By default, the sensor returns the name provided as the `default_state`. Configuration is built up in layers of events.
Events have a `start` time and `end` time, and cause the sensor to report a new `state` name.

All times are interpreted as belonging to the local timezone.

This simple configuration will cause the sensor to report `sleep` or `awake` depending on the time of day.
You can create automations that trigger on the sensor state. Or, you can use the value of the sensor state as a
condition in your automations.

```
    events:
      - start: "0:00"
        end: "5:30"
        state: sleep
      - start: "5:30"
        end: "22:30"
        state: awake
      - start: "22:30"
        state: sleep
```

If `start` is not provided, it defaults to the start of the day, and if `end` is not provided, it defaults to the end of the day.

![schedule1][schedule1img]

Events can be defined in any order. If an event is created that overlaps with existing events, the existing events are re-sized to
accommodate the new event.

To continue the previous example:

```
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

```
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

## Templates

Start and/or end times can be specified using [templates](https://www.home-assistant.io/docs/configuration/templating/).

Use the attributes `start_template`/`end_template` instead of `start`/`end`.

The template value must evaluate to one of these data types:

| Format    | Comments                     |
|-----------|------------------------------|
| datetime  | A string that HA or Python can understand as a `datetime`. Only the time portion is used. |
| time      | A string that HA or Python can understand as a `time`. |
| timestamp | A number that will be interpreted as a timestamp. This will be converted to a `datetime` and only the time portion is used. |

All times are converted to the local timezone.

This is an example of a sensor that provides `day` or `night` states based on data from
the [sun integration](https://www.home-assistant.io/integrations/sun/).

```
    events:
      - state: night
      - start_template: "{{ states.sun.sun.attributes.next_rising }}"
        end_template: "{{ states.sun.sun.attributes.next_setting }}"
        state: day
```

Template values are refreshed at every `refresh` interval.

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
[releases-shield]: https://img.shields.io/github/release/custom-components/blueprint.svg
[releases]: https://github.com/aneeshd/schedule_state/releases
[issues]: https://github.com/aneeshd/schedule_state/issues
[schedule1img]: https://raw.githubusercontent.com/aneeshd/schedule_state/main/docs/schedule1.png
[schedule2img]: https://raw.githubusercontent.com/aneeshd/schedule_state/main/docs/schedule2.png
