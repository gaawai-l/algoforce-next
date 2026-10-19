"""Test isolation shared by every test."""

from pathlib import Path

import pytest

from wheelhouse_service import settings


@pytest.fixture(autouse=True)
def no_coinalyze_key(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """No test reads a developer's real Coinalyze key, from the environment or the repo's .env.

    An empty variable counts as a missing key and keeps `Settings.from_env` from reading the
    file at all; DOTENV is pointed at a file that does not exist as well, in case a test
    removes the variable.
    """
    monkeypatch.setenv(settings.COINALYZE_KEY, "")
    monkeypatch.setattr(settings, "DOTENV", tmp_path / "no-such.env")
