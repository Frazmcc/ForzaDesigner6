from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from fd6.shapegen.profile import (
    Profile,
    load_profile_from_file,
    list_bundled_profiles,
)


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
    """
    Profile picker and generation settings.

    logo_ultra is selected automatically at startup when the profile exists.
    """

    profile_changed = Signal(object)
    start_clicked = Signal()
    pause_clicked = Signal()
    stop_clicked = Signal()
    inject_clicked = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        # ------------------------------------------------------------
        # Profile
        # ------------------------------------------------------------

        prof_row = QHBoxLayout()

        prof_label = QLabel("Profile:")
        prof_label.setToolTip(
            "A profile is a saved collection of generation settings."
        )

        prof_row.addWidget(prof_label)

        self.profile_combo = QComboBox(self)
        self.profile_combo.setToolTip(prof_label.toolTip())

        self._populate_profiles()

        self.profile_combo.currentIndexChanged.connect(
            self._on_profile_changed
        )

        prof_row.addWidget(self.profile_combo, stretch=1)

        layout.addLayout(prof_row)

        # ------------------------------------------------------------
        # Compute backend
        # ------------------------------------------------------------

        compute_row = QHBoxLayout()

        compute_label = QLabel("Compute:")

        compute_tip = (
            "Which processor runs the shape search.\n\n"
            "Auto: use GPU when supported, otherwise CPU.\n"
            "CPU: always use the CPU generation path.\n"
            "GPU: use the OpenCL GPU path when available.\n\n"
            "Mixed logo shapes such as rectangles and triangles may require "
            "the CPU generation path."
        )

        compute_label.setToolTip(compute_tip)

        compute_row.addWidget(compute_label)

        self.compute_backend = QComboBox(self)

        for code, label in COMPUTE_BACKEND_CHOICES:
            self.compute_backend.addItem(label, code)

        self.compute_backend.setCurrentIndex(0)
        self.compute_backend.setToolTip(compute_tip)

        self.compute_backend.currentIndexChanged.connect(
            self._on_adv_changed
        )

        compute_row.addWidget(
            self.compute_backend,
            stretch=1,
        )

        layout.addLayout(compute_row)

        # ------------------------------------------------------------
        # Advanced generation settings
        # ------------------------------------------------------------

        adv = QGroupBox("Advanced", self)
        form = QFormLayout(adv)

        self.stop_at = QSpinBox()
        self.stop_at.setRange(10, 50000)
        self.stop_at.setValue(3000)

        self.stop_at.setToolTip(
            "Maximum number of shapes generated. "
            "For Forza vinyl groups, 3000 is normally the maximum useful "
            "high-quality target."
        )

        self.random_samples = QSpinBox()
        self.random_samples.setRange(10, 50000)
        self.random_samples.setValue(20000)

        self.random_samples.setToolTip(
            "How many random candidate shapes are tested for each generated "
            "shape. Higher values improve the search but greatly increase "
            "generation time."
        )

        self.mutated_samples = QSpinBox()
        self.mutated_samples.setRange(1, 20000)
        self.mutated_samples.setValue(4000)

        self.mutated_samples.setToolTip(
            "How many refined mutations are tested after selecting a promising "
            "candidate shape."
        )

        self.max_resolution = QSpinBox()
        self.max_resolution.setRange(100, 8192)
        self.max_resolution.setValue(2048)

        self.max_resolution.setToolTip(
            "Maximum processing resolution on the longest side. "
            "2048 is recommended for the Logo Ultra profile."
        )

        self.max_threads = QSpinBox()
        self.max_threads.setRange(0, 128)
        self.max_threads.setValue(0)

        self.max_threads.setToolTip(
            "Maximum CPU thread count. "
            "0 allows FD6 to choose automatically."
        )

        self.preview_every = QSpinBox()
        self.preview_every.setRange(1, 500)
        self.preview_every.setValue(25)

        self.preview_every.setToolTip(
            "How often FD6 refreshes the live preview. "
            "This does not affect final generation quality."
        )

        for label_text, field in (
            ("Stop at shapes", self.stop_at),
            ("Random samples", self.random_samples),
            ("Mutated samples", self.mutated_samples),
            ("Max resolution (px)", self.max_resolution),
            ("Threads (0=auto)", self.max_threads),
            ("Preview every N", self.preview_every),
        ):
            row_label = QLabel(label_text, adv)
            row_label.setToolTip(field.toolTip())

            form.addRow(
                row_label,
                field,
            )

            field.valueChanged.connect(
                self._on_adv_changed
            )

        layout.addWidget(adv)

        # ------------------------------------------------------------
        # Image options
        # ------------------------------------------------------------

        sticker_group = QGroupBox(
            "Image options",
            self,
        )

        sg_layout = QVBoxLayout(
            sticker_group
        )

        self.sticker_mode_cb = QCheckBox(
            "Add white background to transparent images",
            sticker_group,
        )

        self.sticker_mode_cb.setChecked(True)

        self.sticker_mode_cb.setToolTip(
            "ON: transparent image areas become white.\n\n"
            "OFF: transparent areas remain transparent. "
            "This is normally preferable for isolated logos and stickers."
        )

        self.sticker_mode_cb.toggled.connect(
            self._on_adv_changed
        )

        sg_layout.addWidget(
            self.sticker_mode_cb
        )

        self.cap_2048_cb = QCheckBox(
            "Experimental: cap generation at 2048px",
            sticker_group,
        )

        # Enabled by default for the high-quality logo configuration.
        self.cap_2048_cb.setChecked(True)

        self.cap_2048_cb.setToolTip(
            "When enabled, FD6 never processes the source above 2048px "
            "on its longest side."
        )

        self.cap_2048_cb.toggled.connect(
            self._on_adv_changed
        )

        sg_layout.addWidget(
            self.cap_2048_cb
        )

        layout.addWidget(
            sticker_group
        )

        # ------------------------------------------------------------
        # Shape types
        # ------------------------------------------------------------

        supported_codes = {
            "rotated_ellipse",
            "rectangle",
            "rotated_rectangle",
            "ellipse",
            "circle",
            "triangle",
        }

        supported_tooltips = {
            "rotated_ellipse": (
                "Rotatable oval. Good for curves, rounded graphics, "
                "faces and organic artwork."
            ),
            "rectangle": (
                "Axis-aligned rectangle. Useful for horizontal and vertical "
                "logo elements."
            ),
            "rotated_rectangle": (
                "Rotatable rectangle. Excellent for lettering, sharp edges, "
                "stripes and geometric graphics."
            ),
            "ellipse": (
                "Non-rotated ellipse."
            ),
            "circle": (
                "Circle primitive."
            ),
            "triangle": (
                "Triangle primitive. Useful for sharp corners, angular "
                "letters and geometric logos."
            ),
        }

        types_group = QGroupBox(
            "Shape types",
            self,
        )

        types_group.setToolTip(
            "Choose which primitive shapes FD6 may use while recreating "
            "the source image."
        )

        tg_layout = QVBoxLayout(
            types_group
        )

        self._shape_checks: dict[str, QCheckBox] = {}

        for code, label in SHAPE_TYPE_CHOICES:
            cb = QCheckBox(
                label,
                types_group,
            )

            cb.setEnabled(
                code in supported_codes
            )

            cb.setChecked(
                code in {
                    "rotated_ellipse",
                    "rotated_rectangle",
                    "triangle",
                }
            )

            cb.setToolTip(
                supported_tooltips.get(
                    code,
                    "",
                )
            )

            cb.stateChanged.connect(
                self._on_adv_changed
            )

            tg_layout.addWidget(cb)

            self._shape_checks[code] = cb

        layout.addWidget(
            types_group
        )

        # ------------------------------------------------------------
        # Generation buttons
        # ------------------------------------------------------------

        btn_row = QHBoxLayout()

        self.start_btn = QPushButton("Start")
        self.start_btn.setMinimumHeight(36)

        self.start_btn.setToolTip(
            "Begin generating the image."
        )

        self.pause_btn = QPushButton("Pause")
        self.pause_btn.setCheckable(True)
        self.pause_btn.setEnabled(False)

        self.pause_btn.setToolTip(
            "Pause or resume generation."
        )

        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setEnabled(False)

        self.stop_btn.setToolTip(
            "Stop generation early."
        )

        self.start_btn.clicked.connect(
            self.start_clicked.emit
        )

        self.pause_btn.clicked.connect(
            self.pause_clicked.emit
        )

        self.stop_btn.clicked.connect(
            self.stop_clicked.emit
        )

        btn_row.addWidget(
            self.start_btn
        )

        btn_row.addWidget(
            self.pause_btn
        )

        btn_row.addWidget(
            self.stop_btn
        )

        layout.addLayout(
            btn_row
        )

        # ------------------------------------------------------------
        # Target game
        # ------------------------------------------------------------

        from fd6.inject.game_profiles import list_profiles

        target_row = QHBoxLayout()

        target_label = QLabel("Target:")

        target_label.setToolTip(
            "Select the Forza title that should receive the generated vinyl."
        )

        target_row.addWidget(
            target_label
        )

        self.target_combo = QComboBox(self)

        self._target_profiles = list_profiles()

        for prof in self._target_profiles:
            self.target_combo.addItem(
                prof.label,
                prof.key,
            )

        # FH6 remains the default target.
        self.target_combo.setCurrentIndex(0)

        self.target_combo.setToolTip(
            "Forza Horizon 6 is the primary validated target."
        )

        self.target_combo.currentIndexChanged.connect(
            self._on_target_changed
        )

        target_row.addWidget(
            self.target_combo,
            stretch=1,
        )

        layout.addLayout(
            target_row
        )

        # ------------------------------------------------------------
        # Injection button
        # ------------------------------------------------------------

        self.inject_btn = QPushButton(
            "Inject into Forza Horizon 6"
        )

        self.inject_btn.setEnabled(False)

        self.inject_btn.setToolTip(
            "Inject the most recently generated or loaded shape JSON "
            "into the currently open Forza vinyl group."
        )

        self.inject_btn.clicked.connect(
            self.inject_clicked.emit
        )

        layout.addWidget(
            self.inject_btn
        )

        layout.addStretch()

        # Load selected/default profile into controls.
        self._on_profile_changed(
            self.profile_combo.currentIndex()
        )

    # ------------------------------------------------------------
    # Target
    # ------------------------------------------------------------

    def selected_target_profile_key(self) -> str:
        data = self.target_combo.currentData()

        return str(data) if data else "fh6"

    def _on_target_changed(self, idx: int) -> None:
        if idx < 0 or idx >= len(self._target_profiles):
            return

        prof = self._target_profiles[idx]

        clean_label = prof.label.replace(
            " (BETA)",
            "",
        )

        self.inject_btn.setText(
            f"Inject into {clean_label}"
        )

        if prof.beta:
            tooltip = (
                f"BETA target: {prof.label}.\n\n"
                f"{prof.beta_note}\n\n"
                "Make sure the in-game vinyl editor is open before injection."
            )
        else:
            tooltip = (
                "Inject the most recently generated or loaded JSON into the "
                "selected Forza title."
            )

        self.inject_btn.setToolTip(
            tooltip
        )

    # ------------------------------------------------------------
    # Profiles
    # ------------------------------------------------------------

    def _populate_profiles(self) -> None:
        self.profile_combo.clear()

        paths = list_bundled_profiles()

        for path in paths:
            self.profile_combo.addItem(
                path.stem,
                str(path),
            )

        if self.profile_combo.count() == 0:
            self.profile_combo.addItem(
                "default",
                "",
            )

            return

        # --------------------------------------------------------
        # DEFAULT PROFILE
        # --------------------------------------------------------
        #
        # Select logo_ultra automatically whenever it exists.
        #
        # --------------------------------------------------------

        default_index = self.profile_combo.findText(
            "logo_ultra"
        )

        if default_index >= 0:
            self.profile_combo.setCurrentIndex(
                default_index
            )
        else:
            self.profile_combo.setCurrentIndex(0)

    def _on_profile_changed(self, idx: int) -> None:
        if idx < 0:
            return

        path = self.profile_combo.itemData(idx)

        if not path:
            return

        try:
            prof = load_profile_from_file(
                path
            )
        except Exception:
            return

        widgets = (
            self.stop_at,
            self.random_samples,
            self.mutated_samples,
            self.max_resolution,
            self.max_threads,
            self.preview_every,
        )

        for widget in widgets:
            widget.blockSignals(True)

        self.stop_at.setValue(
            prof.stop_at
        )

        self.random_samples.setValue(
            prof.random_samples
        )

        self.mutated_samples.setValue(
            prof.mutated_samples
        )

        self.max_resolution.setValue(
            prof.max_resolution
        )

        self.max_threads.setValue(
            prof.max_threads
        )

        self.preview_every.setValue(
            prof.preview_every
        )

        for widget in widgets:
            widget.blockSignals(False)

        # --------------------------------------------------------
        # Shape types
        # --------------------------------------------------------

        for code, cb in self._shape_checks.items():
            cb.blockSignals(True)

            cb.setChecked(
                code in prof.shape_types
            )

            cb.blockSignals(False)

        # --------------------------------------------------------
        # Compute backend
        # --------------------------------------------------------

        wanted_backend = getattr(
            prof,
            "compute_backend",
            "auto",
        )

        compute_index = self.compute_backend.findData(
            wanted_backend
        )

        if compute_index >= 0:
            self.compute_backend.blockSignals(True)

            self.compute_backend.setCurrentIndex(
                compute_index
            )

            self.compute_backend.blockSignals(False)

        self.profile_changed.emit(
            self.build_profile()
        )

    # ------------------------------------------------------------
    # Advanced controls
    # ------------------------------------------------------------

    def _on_adv_changed(self, *_args) -> None:
        self.profile_changed.emit(
            self.build_profile()
        )

    # ------------------------------------------------------------
    # Build current profile
    # ------------------------------------------------------------

    def build_profile(self) -> Profile:
        idx = self.profile_combo.currentIndex()

        path = self.profile_combo.itemData(idx) or ""

        base = Profile(
            name=self.profile_combo.itemText(idx) or "custom"
        )

        if path:
            try:
                base = load_profile_from_file(
                    path
                )
            except Exception:
                pass

        base.stop_at = self.stop_at.value()

        base.random_samples = self.random_samples.value()

        base.mutated_samples = self.mutated_samples.value()

        base.max_resolution = self.max_resolution.value()

        if self.cap_2048_cb.isChecked():
            base.max_resolution = min(
                base.max_resolution,
                2048,
            )

        base.max_threads = self.max_threads.value()

        base.preview_every = self.preview_every.value()

        selected_shapes = [
            code
            for code, cb in self._shape_checks.items()
            if cb.isChecked()
        ]

        if not selected_shapes:
            selected_shapes = [
                "rotated_ellipse"
            ]

        base.shape_types = selected_shapes

        base.compute_backend = str(
            self.compute_backend.currentData()
            or "auto"
        )

        return base

    # ------------------------------------------------------------
    # Running state
    # ------------------------------------------------------------

    def set_running(self, running: bool) -> None:
        self.start_btn.setEnabled(
            not running
        )

        self.pause_btn.setEnabled(
            running
        )

        self.stop_btn.setEnabled(
            running
        )
