from __future__ import annotations

import ctypes
import json
import math
import struct
from dataclasses import dataclass
from ctypes import wintypes
from pathlib import Path
from collections import Counter

from fd6.inject import Injector, VinylGroupHandle, InjectResult
from fd6.inject.game_profiles import GameProfile, default_profile
from fd6.inject.patterns_io import DEFAULT_PATTERNS_PATH
from fd6.inject.rtti_locator import find_livery_group_candidates as rtti_find_candidates
from fd6.inject.win_process import ProcessHandle, find_process_id

PATTERNS_FILE = DEFAULT_PATTERNS_PATH
FH6_TARGET_BUILD = "364.933"

COUNT_OFF = 0x5A
TABLE_OFF = 0x78
LAYER_POS_OFF = 0x18
LAYER_SCALE_OFF = 0x28
LAYER_ROT_OFF = 0x50
LAYER_COLOR_OFF = 0x74
LAYER_MASK_OFF = 0x78
LAYER_SHAPE_ID_OFF = 0x7A

SCALE_DIVISOR_ELLIPSE = 63.0
SCALE_DIVISOR_OTHER = 127.0
SHAPE_ID_ELLIPSE = 102
SHAPE_ID_OTHER = 101


@dataclass
class LayerGeometry:
    supported: bool
    source_type: str
    forza_shape_id: int | None = None
    x: float | None = None
    y: float | None = None
    width: float | None = None
    height: float | None = None
    angle: float | None = None
    color: tuple[int, int, int, int] | None = None
    reason: str | None = None


def _coerce_finite_float(v, field_name: str) -> float:
    try:
        out = float(v)
    except (TypeError, ValueError):
        raise ValueError(f"missing/invalid '{field_name}'")
    if not math.isfinite(out):
        raise ValueError(f"non-finite '{field_name}'")
    return out


def _coerce_color_rgba_255(shape_dict: dict) -> tuple[int, int, int, int]:
    color = shape_dict.get("color")
    if not isinstance(color, (list, tuple)) or len(color) < 3:
        raise ValueError("missing/invalid 'color'")
    r = int(color[0]) & 0xFF
    g = int(color[1]) & 0xFF
    b = int(color[2]) & 0xFF
    return (r, g, b, 255)


def shape_to_forza_layer_geometry(shape_dict: dict, game_profile: GameProfile) -> LayerGeometry:
    st = str(shape_dict.get("type", "")).strip()
    if not st:
        return LayerGeometry(False, source_type="unknown", reason="missing shape 'type'")

    sid = game_profile.shape_id_map.get(st)
    if sid is None:
        if st == "triangle":
            return LayerGeometry(
                False, source_type=st,
                reason="Triangle generation exists, but no verified Forza triangle primitive mapping is available."
            )
        return LayerGeometry(False, source_type=st, reason=f"unsupported shape type for target: {st}")

    try:
        color = _coerce_color_rgba_255(shape_dict)

        if st == "rotated_ellipse":
            x = _coerce_finite_float(shape_dict.get("x"), "x")
            y = _coerce_finite_float(shape_dict.get("y"), "y")
            rx = _coerce_finite_float(shape_dict.get("rx"), "rx")
            ry = _coerce_finite_float(shape_dict.get("ry"), "ry")
            angle = _coerce_finite_float(shape_dict.get("angle"), "angle")
            if rx <= 0 or ry <= 0:
                raise ValueError("rx/ry must be > 0")
            return LayerGeometry(True, st, sid, x, y, rx * 2.0, ry * 2.0, angle, color, None)

        if st == "ellipse":
            x = _coerce_finite_float(shape_dict.get("x"), "x")
            y = _coerce_finite_float(shape_dict.get("y"), "y")
            rx = _coerce_finite_float(shape_dict.get("rx"), "rx")
            ry = _coerce_finite_float(shape_dict.get("ry"), "ry")
            if rx <= 0 or ry <= 0:
                raise ValueError("rx/ry must be > 0")
            return LayerGeometry(True, st, sid, x, y, rx * 2.0, ry * 2.0, 0.0, color, None)

        if st == "circle":
            x = _coerce_finite_float(shape_dict.get("x"), "x")
            y = _coerce_finite_float(shape_dict.get("y"), "y")
            r = _coerce_finite_float(shape_dict.get("r"), "r")
            if r <= 0:
                raise ValueError("r must be > 0")
            return LayerGeometry(True, st, sid, x, y, r * 2.0, r * 2.0, 0.0, color, None)

        if st == "rectangle":
            x = _coerce_finite_float(shape_dict.get("x"), "x")
            y = _coerce_finite_float(shape_dict.get("y"), "y")
            hw = _coerce_finite_float(shape_dict.get("hw"), "hw")
            hh = _coerce_finite_float(shape_dict.get("hh"), "hh")
            if hw <= 0 or hh <= 0:
                raise ValueError("hw/hh must be > 0")
            return LayerGeometry(True, st, sid, x, y, hw * 2.0, hh * 2.0, 0.0, color, None)

        if st == "rotated_rectangle":
            x = _coerce_finite_float(shape_dict.get("x"), "x")
            y = _coerce_finite_float(shape_dict.get("y"), "y")
            hw = _coerce_finite_float(shape_dict.get("hw"), "hw")
            hh = _coerce_finite_float(shape_dict.get("hh"), "hh")
            angle = _coerce_finite_float(shape_dict.get("angle"), "angle")
            if hw <= 0 or hh <= 0:
                raise ValueError("hw/hh must be > 0")
            return LayerGeometry(True, st, sid, x, y, hw * 2.0, hh * 2.0, angle, color, None)

        return LayerGeometry(False, source_type=st, reason=f"unsupported shape type for target: {st}")

    except ValueError as exc:
        return LayerGeometry(False, source_type=st, reason=str(exc))


def patterns_are_populated() -> bool:
    return True


def _is_user_ptr(val: int) -> bool:
    return 0x000001000000 < val < 0x800000000000


def _pack_color(shape_dict: dict) -> bytes:
    try:
        r, g, b, a = _coerce_color_rgba_255(shape_dict)
        return bytes([r, g, b, a])
    except Exception:
        return bytes([255, 255, 255, 255])


class FH6Injector(Injector):
    def __init__(self, pid: int | None = None, patterns_path: Path | str = PATTERNS_FILE,
                 profile: GameProfile | None = None) -> None:
        self.pid = pid
        self.patterns_path = Path(patterns_path)
        self.profile = profile or default_profile()
        self._proc: ProcessHandle | None = None

    @property
    def game_label(self) -> str:
        return self.profile.label

    def attach(self) -> None:
        if self.pid is None:
            for name in self.profile.process_names:
                self.pid = find_process_id(name)
                if self.pid is not None:
                    break
            if self.pid is None:
                names = " / ".join(self.profile.process_names)
                raise RuntimeError(f"Game process not found (looked for: {names})")
        self._proc = ProcessHandle(self.pid)
        self._proc.open()

    def detach(self) -> None:
        if self._proc:
            self._proc.close()
            self._proc = None

    def find_active_vinyl_group(self, progress_cb=None, layer_count: int | None = None, color_progress_cb=None, status_cb=None) -> VinylGroupHandle:
        raise NotImplementedError("Use existing project implementation for locator logic.")

    def inject(self, shapes: list, group: VinylGroupHandle, progress_cb=None,
               image_size: tuple[int, int] | None = None, coord_scale: float = 1.0) -> InjectResult:
        if not self._proc:
            raise RuntimeError("Injector not attached.")

        layer_addrs: list[int] = (group.meta or {}).get("layer_addrs") or []
        if not layer_addrs:
            return InjectResult(success=False, message="No layer addresses cached. Call find_active_vinyl_group first.")

        # Normalize to dicts
        shape_dicts: list[dict] = []
        for s in shapes:
            if hasattr(s, "to_json"):
                shape_dicts.append(s.to_json())
            elif isinstance(s, dict):
                shape_dicts.append(s)
            else:
                return InjectResult(success=False, message=f"Unsupported shape object: {type(s)!r}")

        # PRE-WRITE VALIDATION: all shapes must normalize successfully first.
        normalized: list[LayerGeometry] = []
        bad: list[LayerGeometry] = []
        for sd in shape_dicts:
            g = shape_to_forza_layer_geometry(sd, self.profile)
            if not g.supported:
                bad.append(g)
            normalized.append(g)

        if bad:
            counts = Counter(b.source_type for b in bad)
            reason_counts = Counter((b.reason or "invalid") for b in bad)
            types_line = ", ".join(f"{k}: {v}" for k, v in sorted(counts.items()))
            reasons_line = "; ".join(f"{k} ({v})" for k, v in sorted(reason_counts.items()))
            return InjectResult(
                success=False,
                shapes_written=0,
                message=(
                    "Cannot inject this vinyl.\n\n"
                    "Unsupported or invalid shape types:\n"
                    f"{types_line}\n\n"
                    f"Details: {reasons_line}\n\n"
                    "No layers were written."
                ),
            )

        if len(normalized) > len(layer_addrs):
            return InjectResult(
                success=False,
                shapes_written=0,
                message=(
                    f"Template has {len(layer_addrs)} layer slots, but JSON has {len(normalized)} shapes. "
                    "Load a larger template vinyl group."
                ),
            )

        written = 0
        bytes_total = 0

        for i, geom in enumerate(normalized):
            lptr = layer_addrs[i]
            if not _is_user_ptr(lptr):
                return InjectResult(success=False, shapes_written=written, message="Unsafe layer pointer encountered. Aborting.")

            # Stage 2: no silent fallbacks; geometry guaranteed validated above.
            assert geom.forza_shape_id is not None
            assert geom.x is not None and geom.y is not None
            assert geom.width is not None and geom.height is not None
            assert geom.angle is not None
            assert geom.color is not None

            is_ellipse_family = geom.forza_shape_id == self.profile.shape_id_map.get("rotated_ellipse", 102)
            scale_div = self.profile.scale_divisor_ellipse if is_ellipse_family else self.profile.scale_divisor_other

            sx = float(geom.width) / float(scale_div)
            sy = float(geom.height) / float(scale_div)
            forza_angle = (360.0 - float(geom.angle)) % 360.0

            self._proc.write(lptr + LAYER_POS_OFF, struct.pack("<2f", float(geom.x), -float(geom.y))); bytes_total += 8
            self._proc.write(lptr + LAYER_SCALE_OFF, struct.pack("<2f", sx, sy)); bytes_total += 8
            self._proc.write(lptr + LAYER_ROT_OFF, struct.pack("<f", forza_angle)); bytes_total += 4
            self._proc.write(lptr + LAYER_COLOR_OFF, bytes(list(geom.color))); bytes_total += 4
            self._proc.write(lptr + LAYER_SHAPE_ID_OFF, bytes([int(geom.forza_shape_id)])); bytes_total += 1
            self._proc.write(lptr + LAYER_MASK_OFF, bytes([0])); bytes_total += 1

            written += 1
            if progress_cb:
                progress_cb(written, len(normalized))

        return InjectResult(
            success=(written > 0),
            shapes_written=written,
            message=f"Wrote {written}/{len(normalized)} shapes ({bytes_total} bytes) via validated shape mapping.",
        )
