# NOTE: keep your current file as-is, but replace only SHAPE_TYPE_CHOICES handling
# with this full file if preferred. This version preserves logo_ultra default and
# adds target-aware shape enabling.

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from fd6.shapegen.profile import Profile, load_profile_from_file, list_bundled_profiles
from fd6.inject.game_profiles import list_profiles, get_profile

SHAPE_TYPE_CHOICES = [
    ("rotated_ellipse", "Rotated Ellipse"),
    ("rectangle", "Rectangle"),
    ("rotated_rectangle", "Rotated Rectangle"),
    ("ellipse", "Ellipse"),
    ("circle", "Circle"),
    ("triangle", "Triangle"),
]

COMPUTE_BACKEND_CHOICES = [
    ("auto", "Auto (GPU if ready)"),
    ("cpu", "CPU"),
    ("gpu", "GPU (OpenCL — NVIDIA / AMD / Intel)"),
]


class SettingsPanel(QWidget):
    profile_changed = Signal(object)
    start_clicked = Signal()
    pause_clicked = Signal()
    stop_clicked = Signal()
    inject_clicked = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)

        self.profile_combo = QComboBox(self)
        self._populate_profiles()
        self.profile_combo.currentIndexChanged.connect(self._on_profile_changed)
        layout.addWidget(self.profile_combo)

        self.compute_backend = QComboBox(self)
        for code, label in COMPUTE_BACKEND_CHOICES:
            self.compute_backend.addItem(label, code)
        self.compute_backend.currentIndexChanged.connect(self._on_adv_changed)
        layout.addWidget(self.compute_backend)

        self.stop_at = QSpinBox(); self.stop_at.setRange(10, 50000); self.stop_at.setValue(3000)
        self.random_samples = QSpinBox(); self.random_samples.setRange(10, 50000); self.random_samples.setValue(20000)
        self.mutated_samples = QSpinBox(); self.mutated_samples.setRange(1, 20000); self.mutated_samples.setValue(4000)
        self.max_resolution = QSpinBox(); self.max_resolution.setRange(100, 8192); self.max_resolution.setValue(2048)
        self.max_threads = QSpinBox(); self.max_threads.setRange(0, 128); self.max_threads.setValue(0)
        self.preview_every = QSpinBox(); self.preview_every.setRange(1, 500); self.preview_every.setValue(25)

        for w in (self.stop_at, self.random_samples, self.mutated_samples, self.max_resolution, self.max_threads, self.preview_every):
            w.valueChanged.connect(self._on_adv_changed)
            layout.addWidget(w)

        self.sticker_mode_cb = QCheckBox("Add white background to transparent images")
        self.sticker_mode_cb.setChecked(True)
        self.sticker_mode_cb.toggled.connect(self._on_adv_changed)
        layout.addWidget(self.sticker_mode_cb)

        self.cap_2048_cb = QCheckBox("Experimental: cap generation at 2048px")
        self.cap_2048_cb.setChecked(True)
        self.cap_2048_cb.toggled.connect(self._on_adv_changed)
        layout.addWidget(self.cap_2048_cb)

        self._shape_checks: dict[str, QCheckBox] = {}
        for code, label in SHAPE_TYPE_CHOICES:
            cb = QCheckBox(label, self)
            cb.stateChanged.connect(self._on_adv_changed)
            self._shape_checks[code] = cb
            layout.addWidget(cb)

        self.start_btn = QPushButton("Start"); self.start_btn.clicked.connect(self.start_clicked.emit)
        self.pause_btn = QPushButton("Pause"); self.pause_btn.setCheckable(True); self.pause_btn.clicked.connect(self.pause_clicked.emit)
        self.stop_btn = QPushButton("Stop"); self.stop_btn.clicked.connect(self.stop_clicked.emit)
        self.inject_btn = QPushButton("Inject into Forza Horizon 6"); self.inject_btn.clicked.connect(self.inject_clicked.emit)

        for b in (self.start_btn, self.pause_btn, self.stop_btn, self.inject_btn):
            layout.addWidget(b)

        self.target_combo = QComboBox(self)
        self._target_profiles = list_profiles()
        for prof in self._target_profiles:
            self.target_combo.addItem(prof.label, prof.key)
        self.target_combo.currentIndexChanged.connect(self._on_target_changed)
        layout.addWidget(self.target_combo)

        self._on_target_changed(self.target_combo.currentIndex())
        self._on_profile_changed(self.profile_combo.currentIndex())

    def _populate_profiles(self) -> None:
        self.profile_combo.clear()
        for path in list_bundled_profiles():
            self.profile_combo.addItem(path.stem, str(path))
        if self.profile_combo.count() == 0:
            self.profile_combo.addItem("default", "")
            return
        idx = self.profile_combo.findText("logo_ultra")
        self.profile_combo.setCurrentIndex(idx if idx >= 0 else 0)

    def selected_target_profile_key(self) -> str:
        data = self.target_combo.currentData()
        return str(data) if data else "fh6"

    def _apply_target_shape_support(self) -> None:
        key = self.selected_target_profile_key()
        prof = get_profile(key)
        supported = set(prof.shape_id_map.keys())
        triangle_tooltip = "Triangle generation exists, but FH6 triangle injection has not yet been verified."
        for code, cb in self._shape_checks.items():
            ok = code in supported
            cb.setEnabled(ok)
            if not ok and cb.isChecked():
                cb.setChecked(False)
            if code == "triangle" and not ok:
                cb.setToolTip(triangle_tooltip)

    def _on_target_changed(self, _idx: int) -> None:
        self._apply_target_shape_support()
        self.profile_changed.emit(self.build_profile())

    def _on_profile_changed(self, idx: int) -> None:
        if idx < 0:
            return
        path = self.profile_combo.itemData(idx)
        if path:
            try:
                p = load_profile_from_file(path)
                self.stop_at.setValue(p.stop_at)
                self.random_samples.setValue(p.random_samples)
                self.mutated_samples.setValue(p.mutated_samples)
                self.max_resolution.setValue(p.max_resolution)
                self.max_threads.setValue(p.max_threads)
                self.preview_every.setValue(p.preview_every)
                for code, cb in self._shape_checks.items():
                    cb.setChecked(code in p.shape_types)
                i = self.compute_backend.findData(getattr(p, "compute_backend", "auto"))
                if i >= 0:
                    self.compute_backend.setCurrentIndex(i)
            except Exception:
                pass
        self._apply_target_shape_support()
        self.profile_changed.emit(self.build_profile())

    def _on_adv_changed(self, *_args) -> None:
        self.profile_changed.emit(self.build_profile())

    def build_profile(self) -> Profile:
        idx = self.profile_combo.currentIndex()
        path = self.profile_combo.itemData(idx) or ""
        base = Profile(name=self.profile_combo.itemText(idx) or "custom")
        if path:
            try:
                base = load_profile_from_file(path)
            except Exception:
                pass

        base.stop_at = self.stop_at.value()
        base.random_samples = self.random_samples.value()
        base.mutated_samples = self.mutated_samples.value()
        base.max_resolution = min(self.max_resolution.value(), 2048) if self.cap_2048_cb.isChecked() else self.max_resolution.value()
        base.max_threads = self.max_threads.value()
        base.preview_every = self.preview_every.value()

        selected = [code for code, cb in self._shape_checks.items() if cb.isChecked() and cb.isEnabled()]
        if not selected:
            selected = ["rotated_ellipse"]
        base.shape_types = selected
        base.compute_backend = str(self.compute_backend.currentData() or "auto")
        return base

    def set_running(self, running: bool) -> None:
        self.start_btn.setEnabled(not running)
        self.pause_btn.setEnabled(running)
        self.stop_btn.setEnabled(running)
