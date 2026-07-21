"""Background music player for FD6.

Loops 3 OpenSource MP3 tracks at a configurable volume. Controlled via the
View menu (play/pause, mute, next, volume slider). State (volume, muted, paused)
persists via QSettings across launches.

Audio is MUTED by default (v0.5.5) — the splash video and music both start
silent until the user unmutes via View > Music. A one-time migration also
mutes pre-0.5.5 installs whose saved state predates the muted default; after
that the user's own choice always wins.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QObject, QSettings, QUrl, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer


# Track filenames (bundled next to the EXE / repo root). Order = play order.
TRACKS = ["Song1OpenSource.mp3", "Song2OpenSource.mp3", "Song3OpenSource.mp3"]

DEFAULT_VOLUME = 0.30          # 0.0 - 1.0
DEFAULT_MUTED = True           # v0.5.5: audio starts MUTED; enable via View > Music
SETTINGS_GROUP = "music"
# One-time flag: force-mutes users who installed before muted-by-default existed,
# then never overrides their choice again.
MUTE_MIGRATION_KEY = "mute_default_applied"


def startup_audio_state(settings: QSettings | None = None) -> tuple[bool, float]:
    """Return (muted, volume) to use at app startup, applying the one-time
    'muted by default' migration.

    Pre-0.5.5 installs persisted muted=False, so changing the default alone
    would not silence them. The first launch after this version force-mutes
    once and sets MUTE_MIGRATION_KEY; after that the user's own mute/unmute
    choice always wins. Both the splash video and the music player must call
    this (or read the same keys) so no audio path can blast at startup.
    """
    if settings is None:
        settings = QSettings("FD6", "ForzaDesigner6")
    settings.beginGroup(SETTINGS_GROUP)
    try:
        volume = float(settings.value("volume", DEFAULT_VOLUME))
    except (TypeError, ValueError):
        volume = DEFAULT_VOLUME
    volume = max(0.0, min(1.0, volume))
    muted = settings.value("muted", DEFAULT_MUTED, type=bool)
    if not settings.value(MUTE_MIGRATION_KEY, False, type=bool):
        muted = True
        settings.setValue("muted", True)
        settings.setValue(MUTE_MIGRATION_KEY, True)
    settings.endGroup()
    settings.sync()
    return muted, volume


def _bundle_root() -> Path:
    """Return the directory where bundled resources live.

    - When frozen by PyInstaller: sys._MEIPASS (temp extract dir)
    - When running from source: the FD6 project root (two levels up from this file)
    """
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent.parent.parent


class MusicPlayer(QObject):
    """Auto-looping multi-track player. Emits signals when state changes so UI can update."""

    track_changed = Signal(str)        # filename of the now-playing track
    state_changed = Signal(bool)       # True = playing, False = paused
    volume_changed = Signal(float)     # 0.0 - 1.0
    muted_changed = Signal(bool)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._settings = QSettings("FD6", "ForzaDesigner6")
        self._settings.beginGroup(SETTINGS_GROUP)

        self._audio = QAudioOutput(self)
        self._player = QMediaPlayer(self)
        self._player.setAudioOutput(self._audio)
        self._player.mediaStatusChanged.connect(self._on_media_status)

        self._settings.endGroup()
        # Load persisted state. startup_audio_state() also applies the one-time
        # muted-by-default migration for pre-0.5.5 installs.
        self._muted, self._volume = startup_audio_state(self._settings)
        self._settings.beginGroup(SETTINGS_GROUP)
        self._was_playing = self._settings.value("playing", True, type=bool)
        self._index = int(self._settings.value("index", 0))
        self._settings.endGroup()

        self._audio.setVolume(self._volume)
        self._audio.setMuted(self._muted)

        self._tracks: list[Path] = self._discover_tracks()

    def _discover_tracks(self) -> list[Path]:
        root = _bundle_root()
        found = []
        for name in TRACKS:
            p = root / name
            if p.exists():
                found.append(p)
        return found

    def has_tracks(self) -> bool:
        return bool(self._tracks)

    def start(self) -> None:
        """Begin playback if we have tracks and prior state says playing."""
        if not self._tracks:
            return
        self._index = max(0, min(self._index, len(self._tracks) - 1))
        self._load_current()
        if self._was_playing:
            self._player.play()
            self.state_changed.emit(True)
        else:
            self.state_changed.emit(False)

    def _load_current(self) -> None:
        track = self._tracks[self._index]
        self._player.setSource(QUrl.fromLocalFile(str(track)))
        self.track_changed.emit(track.name)

    def _on_media_status(self, status) -> None:
        # Advance to next track when current ends (auto-loop the playlist)
        if status == QMediaPlayer.EndOfMedia and self._tracks:
            self._index = (self._index + 1) % len(self._tracks)
            self._load_current()
            self._player.play()

    # ---- public controls --------------------------------------------------

    def toggle_play(self) -> bool:
        """Return new playing state."""
        if not self._tracks:
            return False
        if self._player.playbackState() == QMediaPlayer.PlayingState:
            self._player.pause()
            self._was_playing = False
            self._persist("playing", False)
            self.state_changed.emit(False)
            return False
        self._player.play()
        self._was_playing = True
        self._persist("playing", True)
        self.state_changed.emit(True)
        return True

    def next_track(self) -> None:
        if not self._tracks:
            return
        self._index = (self._index + 1) % len(self._tracks)
        self._persist("index", self._index)
        self._load_current()
        if self._was_playing:
            self._player.play()

    def set_volume(self, vol: float) -> None:
        vol = max(0.0, min(1.0, vol))
        self._volume = vol
        self._audio.setVolume(vol)
        self._persist("volume", vol)
        self.volume_changed.emit(vol)

    def set_muted(self, muted: bool) -> None:
        self._muted = bool(muted)
        self._audio.setMuted(self._muted)
        self._persist("muted", self._muted)
        self.muted_changed.emit(self._muted)

    def toggle_mute(self) -> bool:
        self.set_muted(not self._muted)
        return self._muted

    def is_playing(self) -> bool:
        return self._player.playbackState() == QMediaPlayer.PlayingState

    def volume(self) -> float:
        return self._volume

    def muted(self) -> bool:
        return self._muted

    def current_track_name(self) -> str:
        if not self._tracks:
            return ""
        return self._tracks[self._index].name

    def _persist(self, key: str, value) -> None:
        self._settings.beginGroup(SETTINGS_GROUP)
        self._settings.setValue(key, value)
        self._settings.endGroup()
