"""Startup-audio defaults: muted by default + the one-time pre-0.5.5 migration.

Uses file-backed QSettings (no audio device / QMediaPlayer needed) so these
run headless. The invariant under test: no combination of prior persisted
state may produce audible audio on the FIRST launch after updating, and after
that first launch the user's own mute/unmute choice is always respected.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QSettings

from fd6.gui.music import (
    DEFAULT_VOLUME,
    MUTE_MIGRATION_KEY,
    SETTINGS_GROUP,
    startup_audio_state,
)


@pytest.fixture()
def settings(tmp_path):
    s = QSettings(str(tmp_path / "fd6_test.ini"), QSettings.IniFormat)
    yield s
    s.sync()


def _set(settings: QSettings, key: str, value) -> None:
    settings.beginGroup(SETTINGS_GROUP)
    settings.setValue(key, value)
    settings.endGroup()


def test_fresh_install_starts_muted(settings):
    muted, volume = startup_audio_state(settings)
    assert muted is True
    assert volume == pytest.approx(DEFAULT_VOLUME)


def test_pre_055_unmuted_install_is_force_muted_once(settings):
    # Simulate a pre-0.5.5 install: user never touched audio, muted=False saved.
    _set(settings, "muted", False)
    _set(settings, "volume", 0.8)
    muted, volume = startup_audio_state(settings)
    assert muted is True            # migration silences the update's first launch
    assert volume == pytest.approx(0.8)  # volume choice is preserved


def test_user_unmute_after_migration_sticks(settings):
    startup_audio_state(settings)   # first launch applies the migration
    _set(settings, "muted", False)  # user unmutes via View > Music
    muted, _ = startup_audio_state(settings)
    assert muted is False           # never force-muted again


def test_migration_flag_persisted(settings):
    startup_audio_state(settings)
    settings.beginGroup(SETTINGS_GROUP)
    applied = settings.value(MUTE_MIGRATION_KEY, False, type=bool)
    muted = settings.value("muted", False, type=bool)
    settings.endGroup()
    assert applied is True
    assert muted is True


def test_garbage_volume_falls_back_to_default(settings):
    _set(settings, "volume", "not-a-number")
    muted, volume = startup_audio_state(settings)
    assert muted is True
    assert volume == pytest.approx(DEFAULT_VOLUME)
