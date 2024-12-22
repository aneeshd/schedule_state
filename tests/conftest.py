"""Global fixtures for schedule_state integration."""

# Fixtures allow you to replace functions with a Mock object. You can perform
# many options via the Mock to reflect a particular behavior from the original
# function that you want to see without going through the function's actual logic.
# Fixtures can either be passed into tests as parameters, or if autouse=True, they
# will automatically be used across all tests.
#
# Fixtures that are defined in conftest.py are available across all tests. You can also
# define fixtures within a particular test file to scope them locally.
#
# pytest_homeassistant_custom_component provides some fixtures that are provided by
# Home Assistant core. You can find those fixture definitions here:
# https://github.com/MatthewFlamm/pytest-homeassistant-custom-component/blob/master/pytest_homeassistant_custom_component/common.py
#
# See here for more info: https://docs.pytest.org/en/latest/fixture.html (note that
# pytest includes fixtures OOB which you can use as defined on this page)
from collections.abc import Generator
import os
from unittest.mock import AsyncMock, patch

from homeassistant.const import BASE_PLATFORMS
import pytest
import pytest_asyncio

pytest_plugins = "pytest_homeassistant_custom_component"


# This fixture enables loading custom integrations in all tests.
# Remove to enable selective use of this fixture
@pytest_asyncio.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


# This fixture is used to prevent HomeAssistant from attempting to create and dismiss persistent
# notifications. These calls would fail without this fixture since the persistent_notification
# integration is never loaded during a test.
@pytest.fixture(name="skip_notifications", autouse=True)
def skip_notifications_fixture():
    """Skip notification calls."""
    with (
        patch("homeassistant.components.persistent_notification.async_create"),
        patch("homeassistant.components.persistent_notification.async_dismiss"),
    ):
        yield


@pytest.fixture
def mock_setup_entry() -> Generator[AsyncMock]:
    """Mock setting up a config entry."""
    with patch(
        "homeassistant.components.workday.async_setup_entry", return_value=True
    ) as mock_setup:
        yield mock_setup


# https://github.com/home-assistant/core/blob/dev/tests/conftest.py
@pytest.fixture(autouse=True)
def expected_lingering_tasks() -> bool:
    """Temporary ability to bypass test failures.

    Parametrize to True to bypass the pytest failure.
    @pytest.mark.parametrize("expected_lingering_tasks", [True])

    This should be removed when all lingering tasks have been cleaned up.
    """
    return False


# https://github.com/home-assistant/core/blob/dev/tests/conftest.py
@pytest.fixture(autouse=True)
def expected_lingering_timers() -> bool:
    """Temporary ability to bypass test failures.

    Parametrize to True to bypass the pytest failure.
    @pytest.mark.parametrize("expected_lingering_timers", [True])

    This should be removed when all lingering timers have been cleaned up.
    """
    current_test = os.getenv("PYTEST_CURRENT_TEST")
    if (
        current_test
        and current_test.startswith("tests/components/")
        and current_test.split("/")[2] not in BASE_PLATFORMS
    ):
        # As a starting point, we ignore non-platform components
        return True
    return False
