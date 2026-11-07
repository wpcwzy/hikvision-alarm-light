"""Shared pytest fixtures for the alarm-light tests."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Make the custom integration discoverable in every test."""
    yield


import pytest as _pytest

from tests.fakes import FakeAlertReader, FakeHikvisionClient


@_pytest.fixture(autouse=True)
def reset_fakes():
    """Reset shared fake state between tests."""
    FakeHikvisionClient.reset()
    FakeAlertReader.reset()
    yield
