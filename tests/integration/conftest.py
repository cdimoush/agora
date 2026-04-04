"""Conftest for live integration tests."""

import pytest


def pytest_addoption(parser):
    parser.addoption("--live", action="store_true", default=False, help="Run live Discord tests")


def pytest_collection_modifyitems(config, items):
    if not config.getoption("--live"):
        skip = pytest.mark.skip(reason="Live tests require --live flag")
        for item in items:
            if "integration" in str(item.fspath):
                item.add_marker(skip)
