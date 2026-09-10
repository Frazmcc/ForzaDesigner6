from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from fd6.shapegen.profile import (
    Profile,
    list_available_profiles,
    list_bundled_profiles,
    load_profile_from_file,
    user_profiles_dir,
)
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

# Layer presets deliberately scale both shape count and search/detail budget.
# They do NOT change the physical size of the vinyl in Forza; the higher
# resolution/search budget simply lets larger or more detailed source artwork
# survive reduction better.
LAYER_PRESETS = {
    500: {
        "label": "500 — Small / simple logo",
        "max_preview_size": 600,
        "max_resolution": 900,
        "random_samples": 3000,
        "mutated_samples": 600,
        "posterize_levels": 64,
        "redundant_check_every": 250,
        "preview_every": 10,
        "save_every": 50,
    },
    1000: {
        "label": "1000 — Small/medium, more detail",
        "max_preview_size": 700,
        "max_resolution": 1100,
        "random_samples": 4000,
        "mutated_samples": 750,
        "posterize_levels": 96,
        "redundant_check_every": 250,
        "preview_every": 10,
        "save_every": 50,
    },
    1500: {
        "label": "1500 — Medium / detailed logo",
        "max_preview_size": 750,
        "max_resolution": 1200,
        "random_samples": 4500,
        "mutated_samples": 850,
        "posterize_levels": 128,
        "redundant_check_every": 250,
        "preview_every": 10,
        "save_every": 50,
    },
    2000: {
        "label": "2000 — High detail / larger artwork",
        "max_preview_size": 800,
        "max_resolution": 1400,
        "random_samples": 5000,
        "mutated_samples": 1000,
        "posterize_levels": 160,
        "redundant_check_every": 250,
        "preview_every": 10,
        "save_every": 50,
    },
    2500: {
        "label": "2500 — Maximum practical detail",
        "max_preview_size": 900,
        "max_resolution": 1536,
        "random_samples": 6000,
        "mutated_samples": 1200,
        "posterize_levels": 192,
        "redundant_check_every": 250,
        "preview_every": 10,
        "save_every": 50,
    },
}


class SettingsPanel(QWidget):
    """Forza generation settings with full labels, profiles, and layer presets."""

    profile_changed = Signal(object)
    start_clicked = Signal()
    pause_clicked = Signal()
    stop_clicked = Signal()
    inject_clicked = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._loading_profile = False
        self._applying_layer_preset = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        # Profile picker — restores the labelled presentation from the original UI.
        profile_group = QGroupBox("Profile", self)
        pg = QVBoxLayout(profile_group)
        prof_row = QHBoxLayout()
        prof_label = QLabel("Profile:", profile_group)
        prof_label.setToolTip(
            "Saved generation settings. Bundled profiles ship with FD6; user INIs "
            "are stored separately so they survive app updates."
        )
        prof_row.addWidget(prof_label)
        self.profile_combo = QComboBox(profile_group)
        self.profile_combo.setToolTip(prof_label.toolTip())
        self._populate_profiles()
        self.profile_combo.currentIndexChanged.connect(self._on_profile_changed)
        prof_row.addWidget(self.profile_combo, 1)
        pg.addLayout(prof_row)

        profile_btns = QHBoxLayout()
        self.import_profile_btn = QPushButton("Import INI…", profile_group)
        self.import_profile_btn.setToolTip("Import your own .ini profile into FD6's persistent user profile folder.")
        self.import_profile_btn.clicked.connect(self._import_profile)
        self.save_profile_btn = QPushButton("Save Current…", profile_group)
        self.save_profile_btn.setToolTip("Save the settings currently shown as your own reusable .ini profile.")
        self.save_profile_btn.clicked.connect(self._save_current_profile)
        self.open_profiles_btn = QPushButton("Profiles Folder", profile_group)
        self.open_profiles_btn.setToolTip("Open the folder where your custom INI profiles are stored.")
        self.open_profiles_btn.clicked.connect(self._open_profiles_folder)
        profile_btns.addWidget(self.import_profile_btn)
        profile_btns.addWidget(self.save_profile_btn)
        profile_btns.addWidget(self.open_profiles_btn)
        pg.addLayout(profile_btns)
        layout.addWidget(profile_group)

        # Layer/detail presets requested for the actual vinyl-group sizes in use.
        layer_group = QGroupBox("Layer / detail preset", self)
        layer_form = QFormLayout(layer_group)
        self.layer_preset_combo = QComboBox(layer_group)
        self.layer_preset_combo.addItem("Custom — use values below", 0)
        for layers, cfg in LAYER_PRESETS.items():
            self.layer_preset_combo.addItem(cfg["label"], layers)
        self.layer_preset_combo.setToolTip(
            "Sets the target layer count AND scales the generation detail budget. "
            "500 is faster and best for small/simple logos; 2500 uses higher "
            "resolution and more search/refinement work for maximum detail. "
            "This does not directly resize the in-game vinyl."
        )
        self.layer_preset_combo.currentIndexChanged.connect(self._on_layer_preset_changed)
        layer_form.addRow("Layers / detail", self.layer_preset_combo)
        self.layer_preset_help = QLabel(
            "More layers = more available geometry and a larger detail budget. "
            "You can select a preset, then fine-tune any value below.",
            layer_group,
        )
        self.layer_preset_help.setWordWrap(True)
        layer_form.addRow(self.layer_preset_help)
        layout.addWidget(layer_group)

        # Compute backend.
        compute_row = QHBoxLayout()
        compute_label = QLabel("Compute:", self)
        compute_tip = (
            "Auto uses the GPU when supported and otherwise CPU. CPU is the safe "
            "choice for mixed shape types in the packaged Windows build."
        )
        compute_label.setToolTip(compute_tip)
        compute_row.addWidget(compute_label)
        self.compute_backend = QComboBox(self)
        for code, label in COMPUTE_BACKEND_CHOICES:
            self.compute_backend.addItem(label, code)
        self.compute_backend.setToolTip(compute_tip)
        self.compute_backend.currentIndexChanged.connect(self._on_adv_changed)
        compute_row.addWidget(self.compute_backend, 1)
        layout.addLayout(compute_row)

        # Full advanced settings. These labels mirror the original FD6 wording.
        adv = QGroupBox("Advanced", self)
        form = QFormLayout(adv)

        self.stop_at = QSpinBox(adv); self.stop_at.setRange(10, 50000); self.stop_at.setValue(3000)
        self.stop_at.setToolTip(
            "How many shapes/layers to generate before stopping. This must not "
            "exceed the number of usable layers in the target vinyl group."
        )
        self.random_samples = QSpinBox(adv); self.random_samples.setRange(10, 50000); self.random_samples.setValue(1000)
        self.random_samples.setToolTip("Random candidates tried per shape. Higher can improve quality but is slower.")
        self.mutated_samples = QSpinBox(adv); self.mutated_samples.setRange(1, 20000); self.mutated_samples.setValue(200)
        self.mutated_samples.setToolTip("Refinement mutations tried after the random-search winner is found.")
        self.max_resolution = QSpinBox(adv); self.max_resolution.setRange(100, 8192); self.max_resolution.setValue(1200)
        self.max_resolution.setToolTip("Maximum processing resolution on the image's longest side.")
        self.max_preview_size = QSpinBox(adv); self.max_preview_size.setRange(100, 4096); self.max_preview_size.setValue(500)
        self.max_preview_size.setToolTip("Maximum size of generated preview imagery. Does not alter Forza layer geometry.")
        self.posterize_levels = QSpinBox(adv); self.posterize_levels.setRange(2, 256); self.posterize_levels.setValue(256)
        self.posterize_levels.setToolTip("Colour quantisation levels. Lower values simplify colour detail; higher values preserve more colour variation.")
        self.max_threads = QSpinBox(adv); self.max_threads.setRange(0, 128); self.max_threads.setValue(0)
        self.max_threads.setToolTip("CPU worker count. 0 = automatic. Packaged safe-inline generation may effectively use one worker.")
        self.preview_every = QSpinBox(adv); self.preview_every.setRange(1, 500); self.preview_every.setValue(25)
        self.preview_every.setToolTip("Refresh the live preview every N committed shapes. Does not affect final output quality.")
        self.redundant_check_every = QSpinBox(adv); self.redundant_check_every.setRange(1, 10000); self.redundant_check_every.setValue(500)
        self.redundant_check_every.setToolTip("How often FD6 checks for/removes redundant geometry where supported.")
        self.save_every = QSpinBox(adv); self.save_every.setRange(1, 10000); self.save_every.setValue(100)
        self.save_every.setToolTip("Write a rolling checkpoint every N shapes.")
        self.save_at_edit = QLineEdit(adv)
        self.save_at_edit.setText("500,1000,1500,2000,2500,3000")
        self.save_at_edit.setToolTip("Comma-separated exact layer counts at which FD6 writes named checkpoint JSON files.")

        fields = (
            ("Stop at shapes", self.stop_at),
            ("Random samples", self.random_samples),
            ("Mutated samples", self.mutated_samples),
            ("Max resolution (px)", self.max_resolution),
            ("Max preview size (px)", self.max_preview_size),
            ("Posterize levels", self.posterize_levels),
            ("Threads (0=auto)", self.max_threads),
            ("Preview every N", self.preview_every),
            ("Redundant check every N", self.redundant_check_every),
            ("Save every N", self.save_every),
            ("Save at shapes", self.save_at_edit),
        )
        for label_text, field in fields:
            row_label = QLabel(label_text, adv)
            row_label.setToolTip(field.toolTip())
            form.addRow(row_label, field)
            if isinstance(field, QSpinBox):
                field.valueChanged.connect(self._on_adv_changed)
            else:
                field.editingFinished.connect(self._on_adv_changed)
        layout.addWidget(adv)

        # Image/transparency options. Keep the old hidden checkbox as a
        # compatibility bridge because MainWindow currently interprets it as
        # "add white background". The user-facing control is now positive and clear.
        image_group = QGroupBox("Image / transparency options", self)
        ig = QVBoxLayout(image_group)
        self.preserve_transparency_cb = QCheckBox(
            "Preserve transparency (Sticker mode — hard outer boundary)",
            image_group,
        )
        self.preserve_transparency_cb.setToolTip(
            "For transparent PNGs, keep transparent pixels empty. In the current "
            "hard-boundary generator, candidate geometry that crosses into fully "
            "transparent source pixels is rejected. Use this for logos/stickers."
        )
        self.preserve_transparency_cb.toggled.connect(self._on_preserve_transparency_changed)
        ig.addWidget(self.preserve_transparency_cb)

        self.add_white_info = QLabel(
            "OFF = transparent PNGs are flattened onto white. ON = transparent "
            "areas remain empty and define the protected silhouette.",
            image_group,
        )
        self.add_white_info.setWordWrap(True)
        ig.addWidget(self.add_white_info)

        # Compatibility checkbox: checked means "add white". Keep hidden from UI.
        self.sticker_mode_cb = QCheckBox(image_group)
        self.sticker_mode_cb.setChecked(True)
        self.sticker_mode_cb.setVisible(False)

        self.cap_2048_cb = QCheckBox("Experimental: cap generation at 2048px", image_group)
        self.cap_2048_cb.setToolTip(
            "When ON, the effective Max resolution is limited to 2048px even if "
            "the profile asks for more."
        )
        self.cap_2048_cb.toggled.connect(self._on_adv_changed)
        ig.addWidget(self.cap_2048_cb)
        layout.addWidget(image_group)

        # Shape types — target-aware support remains enforced.
        types_group = QGroupBox("Shape types", self)
        tg = QVBoxLayout(types_group)
        self._shape_checks: dict[str, QCheckBox] = {}
        for code, label in SHAPE_TYPE_CHOICES:
            cb = QCheckBox(label, types_group)
            cb.stateChanged.connect(self._on_adv_changed)
            self._shape_checks[code] = cb
            tg.addWidget(cb)
        layout.addWidget(types_group)

        # Actions.
        btn_row = QHBoxLayout()
        self.start_btn = QPushButton("Start", self); self.start_btn.setMinimumHeight(36)
        self.pause_btn = QPushButton("Pause", self); self.pause_btn.setCheckable(True); self.pause_btn.setEnabled(False)
        self.stop_btn = QPushButton("Stop", self); self.stop_btn.setEnabled(False)
        self.start_btn.clicked.connect(self.start_clicked.emit)
        self.pause_btn.clicked.connect(self.pause_clicked.emit)
        self.stop_btn.clicked.connect(self.stop_clicked.emit)
        btn_row.addWidget(self.start_btn)
        btn_row.addWidget(self.pause_btn)
        btn_row.addWidget(self.stop_btn)
        layout.addLayout(btn_row)

        self.inject_btn = QPushButton("Inject into Forza Horizon 6", self)
        self.inject_btn.clicked.connect(self.inject_clicked.emit)
        layout.addWidget(self.inject_btn)

        target_row = QHBoxLayout()
        target_label = QLabel("Target:", self)
        target_row.addWidget(target_label)
        self.target_combo = QComboBox(self)
        self._target_profiles = list_profiles()
        for prof in self._target_profiles:
            self.target_combo.addItem(prof.label, prof.key)
        self.target_combo.currentIndexChanged.connect(self._on_target_changed)
        target_row.addWidget(self.target_combo, 1)
        layout.addLayout(target_row)

        layout.addStretch()

        self._on_target_changed(self.target_combo.currentIndex())
        self._on_profile_changed(self.profile_combo.currentIndex())

    # ------------------------------------------------------------------ profiles
    def _populate_profiles(self, select_path: str | None = None) -> None:
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        bundled = {str(p.resolve()) for p in list_bundled_profiles()}
        for path in list_available_profiles():
            resolved = str(path.resolve())
            suffix = "" if resolved in bundled else " (user)"
            self.profile_combo.addItem(path.stem + suffix, str(path))
        if self.profile_combo.count() == 0:
            self.profile_combo.addItem("default", "")
        selected = -1
        if select_path:
            wanted = str(Path(select_path).resolve())
            for i in range(self.profile_combo.count()):
                data = self.profile_combo.itemData(i)
                if data and str(Path(data).resolve()) == wanted:
                    selected = i
                    break
        if selected < 0:
            for i in range(self.profile_combo.count()):
                if self.profile_combo.itemText(i).replace(" (user)", "") == "logo_ultra":
                    selected = i
                    break
        self.profile_combo.setCurrentIndex(selected if selected >= 0 else 0)
        self.profile_combo.blockSignals(False)

    def _import_profile(self) -> None:
        src, _ = QFileDialog.getOpenFileName(self, "Import FD6 profile", "", "INI profiles (*.ini);;All files (*)")
        if not src:
            return
        src_path = Path(src)
        try:
            load_profile_from_file(src_path)  # validate before copying
            dest_dir = user_profiles_dir()
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / src_path.name
            if dest.exists():
                answer = QMessageBox.question(
                    self,
                    "Replace profile?",
                    f"{dest.name} already exists in your profile folder. Replace it?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                if answer != QMessageBox.Yes:
                    return
            shutil.copy2(src_path, dest)
            self._populate_profiles(str(dest))
            self._on_profile_changed(self.profile_combo.currentIndex())
            QMessageBox.information(self, "Profile imported", f"Imported {dest.name}")
        except Exception as exc:
            QMessageBox.critical(self, "Could not import profile", f"{type(exc).__name__}: {exc}")

    def _save_current_profile(self) -> None:
        dest_dir = user_profiles_dir()
        dest_dir.mkdir(parents=True, exist_ok=True)
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Save FD6 profile",
            str(dest_dir / "custom.ini"),
            "INI profiles (*.ini)",
        )
        if not filename:
            return
        path = Path(filename)
        if path.suffix.lower() != ".ini":
            path = path.with_suffix(".ini")
        try:
            profile = self.build_profile()
            profile.name = path.stem
            path.write_text(profile.to_ini(), encoding="utf-8")
            self._populate_profiles(str(path))
            QMessageBox.information(self, "Profile saved", f"Saved {path.name}")
        except Exception as exc:
            QMessageBox.critical(self, "Could not save profile", f"{type(exc).__name__}: {exc}")

    def _open_profiles_folder(self) -> None:
        folder = user_profiles_dir()
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    # --------------------------------------------------------------- layer presets
    def _on_layer_preset_changed(self, _idx: int) -> None:
        if self._loading_profile:
            return
        layers = int(self.layer_preset_combo.currentData() or 0)
        if layers not in LAYER_PRESETS:
            return
        cfg = LAYER_PRESETS[layers]
        self._applying_layer_preset = True
        widgets = [
            self.stop_at, self.max_preview_size, self.max_resolution,
            self.random_samples, self.mutated_samples, self.posterize_levels,
            self.redundant_check_every, self.preview_every, self.save_every,
        ]
        for widget in widgets:
            widget.blockSignals(True)
        try:
            self.stop_at.setValue(layers)
            self.max_preview_size.setValue(cfg["max_preview_size"])
            self.max_resolution.setValue(cfg["max_resolution"])
            self.random_samples.setValue(cfg["random_samples"])
            self.mutated_samples.setValue(cfg["mutated_samples"])
            self.posterize_levels.setValue(cfg["posterize_levels"])
            self.redundant_check_every.setValue(cfg["redundant_check_every"])
            self.preview_every.setValue(cfg["preview_every"])
            self.save_every.setValue(cfg["save_every"])
            self.save_at_edit.setText(",".join(str(n) for n in range(500, layers + 1, 500)))
        finally:
            for widget in widgets:
                widget.blockSignals(False)
            self._applying_layer_preset = False
        self.profile_changed.emit(self.build_profile())

    def _set_layer_preset_from_profile(self, p: Profile) -> None:
        match = 0
        cfg = LAYER_PRESETS.get(p.stop_at)
        if cfg:
            expected_save_at = list(range(500, p.stop_at + 1, 500))
            if (
                p.max_preview_size == cfg["max_preview_size"]
                and p.max_resolution == cfg["max_resolution"]
                and p.random_samples == cfg["random_samples"]
                and p.mutated_samples == cfg["mutated_samples"]
                and p.posterize_levels == cfg["posterize_levels"]
                and p.redundant_check_every == cfg["redundant_check_every"]
                and p.preview_every == cfg["preview_every"]
                and p.save_every == cfg["save_every"]
                and p.save_at == expected_save_at
            ):
                match = p.stop_at
        idx = self.layer_preset_combo.findData(match)
        self.layer_preset_combo.setCurrentIndex(idx if idx >= 0 else 0)

    # ------------------------------------------------------------- target / profile
    def selected_target_profile_key(self) -> str:
        data = self.target_combo.currentData()
        return str(data) if data else "fh6"

    def _apply_target_shape_support(self) -> None:
        key = self.selected_target_profile_key()
        prof = get_profile(key)
        supported = set(prof.shape_id_map.keys())
        triangle_tooltip = "Triangle generation exists, but triangle injection has not yet been verified for this target."
        for code, cb in self._shape_checks.items():
            ok = code in supported
            cb.setEnabled(ok)
            if not ok and cb.isChecked():
                cb.setChecked(False)
            if code == "triangle" and not ok:
                cb.setToolTip(triangle_tooltip)

    def _on_target_changed(self, _idx: int) -> None:
        if not hasattr(self, "_shape_checks"):
            return
        self._apply_target_shape_support()
        self.profile_changed.emit(self.build_profile())

    def _on_profile_changed(self, idx: int) -> None:
        if idx < 0:
            return
        path = self.profile_combo.itemData(idx)
        if not path:
            return
        try:
            p = load_profile_from_file(path)
        except Exception as exc:
            QMessageBox.warning(self, "Profile load failed", f"{type(exc).__name__}: {exc}")
            return

        self._loading_profile = True
        try:
            widgets = (
                self.stop_at, self.random_samples, self.mutated_samples,
                self.max_resolution, self.max_preview_size, self.posterize_levels,
                self.max_threads, self.preview_every, self.redundant_check_every,
                self.save_every,
            )
            for w in widgets:
                w.blockSignals(True)
            self.stop_at.setValue(p.stop_at)
            self.random_samples.setValue(p.random_samples)
            self.mutated_samples.setValue(p.mutated_samples)
            self.max_resolution.setValue(p.max_resolution)
            self.max_preview_size.setValue(p.max_preview_size)
            self.posterize_levels.setValue(p.posterize_levels)
            self.max_threads.setValue(p.max_threads)
            self.preview_every.setValue(p.preview_every)
            self.redundant_check_every.setValue(p.redundant_check_every)
            self.save_every.setValue(p.save_every)
            self.save_at_edit.setText(",".join(str(v) for v in p.save_at))
            for w in widgets:
                w.blockSignals(False)

            for code, cb in self._shape_checks.items():
                cb.blockSignals(True)
                cb.setChecked(code in p.shape_types)
                cb.blockSignals(False)

            i = self.compute_backend.findData(getattr(p, "compute_backend", "auto"))
            if i >= 0:
                self.compute_backend.setCurrentIndex(i)

            self.preserve_transparency_cb.blockSignals(True)
            self.preserve_transparency_cb.setChecked(bool(getattr(p, "preserve_transparency", False)))
            self.preserve_transparency_cb.blockSignals(False)
            self.sticker_mode_cb.setChecked(not self.preserve_transparency_cb.isChecked())

            self.cap_2048_cb.blockSignals(True)
            self.cap_2048_cb.setChecked(bool(getattr(p, "cap_generation_2048", False)))
            self.cap_2048_cb.blockSignals(False)

            self._set_layer_preset_from_profile(p)
        finally:
            self._loading_profile = False

        self._apply_target_shape_support()
        self.profile_changed.emit(self.build_profile())

    def _on_preserve_transparency_changed(self, checked: bool) -> None:
        # Hidden compatibility checkbox is the inverse: checked means add white.
        self.sticker_mode_cb.setChecked(not checked)
        self._on_adv_changed()

    def _parse_save_at(self) -> list[int]:
        values: list[int] = []
        for piece in self.save_at_edit.text().split(","):
            piece = piece.strip()
            if not piece:
                continue
            try:
                value = int(piece)
            except ValueError:
                continue
            if value > 0 and value not in values:
                values.append(value)
        return sorted(values)

    def _on_adv_changed(self, *_args) -> None:
        if self._loading_profile or self._applying_layer_preset:
            return
        self.profile_changed.emit(self.build_profile())

    def build_profile(self) -> Profile:
        idx = self.profile_combo.currentIndex()
        path = self.profile_combo.itemData(idx) or ""
        base = Profile(name=self.profile_combo.itemText(idx).replace(" (user)", "") or "custom")
        if path:
            try:
                base = load_profile_from_file(path)
            except Exception:
                pass

        base.stop_at = self.stop_at.value()
        base.random_samples = self.random_samples.value()
        base.mutated_samples = self.mutated_samples.value()
        base.max_resolution = min(self.max_resolution.value(), 2048) if self.cap_2048_cb.isChecked() else self.max_resolution.value()
        base.max_preview_size = self.max_preview_size.value()
        base.posterize_levels = self.posterize_levels.value()
        base.max_threads = self.max_threads.value()
        base.preview_every = self.preview_every.value()
        base.redundant_check_every = self.redundant_check_every.value()
        base.save_every = self.save_every.value()
        base.save_at = self._parse_save_at()
        base.preserve_transparency = self.preserve_transparency_cb.isChecked()
        base.cap_generation_2048 = self.cap_2048_cb.isChecked()

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
