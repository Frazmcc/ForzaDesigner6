from __future__ import annotations

from pathlib import Path
import sys

import numpy as np
from PIL import Image
from PySide6.QtCore import QObject, QThread, Signal

from fd6.shapegen.engine import Engine, EngineConfig
from fd6.shapegen.inline_engine import InlineEngine
from fd6.shapegen.profile import Profile
from fd6.io.exporter import save_json
from fd6.io.json_schema import FD6Document


class GenerationWorker(QObject):
    """Wraps Engine.run() in a QThread-friendly object. Emits Qt signals for the GUI."""

    progress = Signal(int, int, float)  # shape_count, total, rms
    preview = Signal(object)            # np.ndarray (H,W,3) uint8
    finished = Signal(str)              # final json output path
    error = Signal(str)
    checkpoint_written = Signal(str)    # checkpoint json path
    backend_ready = Signal(str)         # compute backend label ("GPU (CUDA)" / "CPU")

    def __init__(self, image_path: Path, profile: Profile, output_dir: Path | None = None, sticker_mode: bool = False) -> None:
        super().__init__()
        self.image_path = Path(image_path)
        self.profile = profile
        self.output_dir = Path(output_dir) if output_dir else self.image_path.parent / self.image_path.stem
        self.sticker_mode = sticker_mode  # When True, keep source alpha and skip transparent areas
        self._engine: Engine | None = None
        self._paused = False

    def stop(self) -> None:
        if self._engine:
            self._engine.request_stop()

    def set_pause(self, paused: bool) -> None:
        self._paused = paused
        if self._engine:
            self._engine.set_pause(paused)

    @staticmethod
    def _engine_class() -> type[Engine]:
        """Choose a CPU implementation safe for the current runtime.

        PyInstaller one-file Windows builds occasionally re-enter the GUI when
        ProcessPoolExecutor starts a child process. Generation already runs in a
        dedicated QThread, so the frozen build can safely perform its CPU search
        inline in that worker thread instead. Source/development runs retain the
        normal multiprocessing Engine.

        An explicit ``Threads = 1`` also selects the inline path, which gives us
        a deterministic no-child-process diagnostic mode outside PyInstaller.
        """
        if getattr(sys, "frozen", False):
            return InlineEngine
        return Engine

    def run(self) -> None:
        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            img = Image.open(self.image_path)
            alpha_mask: np.ndarray | None = None
            has_alpha = img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)
            if has_alpha:
                rgba = img.convert("RGBA")
                if self.sticker_mode:
                    arr_rgba = np.asarray(rgba, dtype=np.uint8)
                    img = Image.fromarray(arr_rgba[:, :, :3], "RGB")
                    alpha_mask = arr_rgba[:, :, 3].copy()
                else:
                    bg = Image.new("RGB", rgba.size, (255, 255, 255))
                    bg.paste(rgba, mask=rgba.split()[3])
                    img = bg
            else:
                img = img.convert("RGB")

            if not self.sticker_mode and img.size[0] != img.size[1]:
                side = max(img.size)
                square = Image.new("RGB", (side, side), (255, 255, 255))
                offset = ((side - img.size[0]) // 2, (side - img.size[1]) // 2)
                square.paste(img, offset)
                img = square

            BUFFER_FRAC = 0.08
            pad_px = max(8, int(round(max(img.size) * BUFFER_FRAC)))
            src_w, src_h = img.size
            new_w = src_w + 2 * pad_px
            new_h = src_h + 2 * pad_px

            if alpha_mask is None:
                alpha_mask = np.full((src_h, src_w), 255, dtype=np.uint8)
            padded_alpha = np.zeros((new_h, new_w), dtype=np.uint8)
            ah, aw = alpha_mask.shape[:2]
            padded_alpha[pad_px:pad_px + ah, pad_px:pad_px + aw] = alpha_mask
            alpha_mask = padded_alpha

            buffered = Image.new("RGB", (new_w, new_h), (255, 255, 255))
            buffered.paste(img, (pad_px, pad_px))
            img = buffered

            # Downscale to profile.max_resolution along the longer side.
            # RGB gets high-quality LANCZOS resampling, but the sticker alpha
            # mask is a HARD geometry boundary. LANCZOS can create faint nonzero
            # halos outside a transparent edge, which would incorrectly make
            # those pixels legal for Forza primitives. NEAREST preserves the
            # original alpha support without inventing new non-transparent
            # pixels around the silhouette.
            mr = self.profile.max_resolution
            if max(img.size) > mr:
                scale = mr / max(img.size)
                new_size = (max(1, int(img.size[0] * scale)), max(1, int(img.size[1] * scale)))
                img = img.resize(new_size, Image.LANCZOS)
                if alpha_mask is not None:
                    am_img = Image.fromarray(alpha_mask, "L").resize(new_size, Image.NEAREST)
                    alpha_mask = np.asarray(am_img, dtype=np.uint8)
            target = np.asarray(img, dtype=np.uint8)

            engine_cls = self._engine_class()
            self._engine = engine_cls(target, EngineConfig(profile=self.profile), alpha_mask=alpha_mask)
            stem = self.image_path.stem
            final_path = self.output_dir / f"{stem}.json"

            for event in self._engine.run():
                if event.kind == "shape_committed":
                    self.progress.emit(event.shape_count, self.profile.stop_at, event.rms)
                elif event.kind == "backend":
                    label = event.message
                    if engine_cls is InlineEngine and "CPU" in label.upper():
                        label += " (safe inline mode)"
                    self.backend_ready.emit(label)
                elif event.kind == "preview" and event.canvas is not None:
                    self.preview.emit(event.canvas)
                elif event.kind == "checkpoint":
                    cp_path = self.output_dir / f"{stem}_{event.shape_count}.json"
                    doc = FD6Document.from_engine(
                        source_image=self.image_path.name,
                        image_size=(target.shape[1], target.shape[0]),
                        shapes=self._engine.shapes,
                        profile_name=self.profile.name,
                        sticker_mode=self.sticker_mode,
                    )
                    save_json(doc, cp_path)
                    self.checkpoint_written.emit(str(cp_path))
                elif event.kind == "error":
                    self.error.emit(event.message)
                    return
                elif event.kind == "done":
                    doc = FD6Document.from_engine(
                        source_image=self.image_path.name,
                        image_size=(target.shape[1], target.shape[0]),
                        shapes=self._engine.shapes,
                        profile_name=self.profile.name,
                        sticker_mode=self.sticker_mode,
                    )
                    save_json(doc, final_path)
                    self.finished.emit(str(final_path))
                    return
        except Exception as exc:
            self.error.emit(f"{type(exc).__name__}: {exc}")
