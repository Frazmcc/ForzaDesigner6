"""FH6 memory injection.

This package defines the injector interface and the concrete FH6 implementation,
which uses the LiveryGroup + layer_table discovery strategy (see
`fh6_injector.py`). For a new FH6 build, layout offsets may need to be
re-derived; the in-app FH6 → Discovery Workflow dialog documents the steps.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any
import struct


@dataclass
class VinylGroupHandle:
    """Opaque handle returned by Injector.find_active_vinyl_group(). Fields are filled in by the concrete injector."""

    base_addr: int = 0
    layer_count: int = 0
    shape_array_addr: int = 0
    shape_stride: int = 0
    meta: dict[str, Any] | None = None


@dataclass
class InjectResult:
    success: bool
    shapes_written: int = 0
    message: str = ""


class Injector(ABC):
    """Abstract base for all per-game injectors."""

    game_label: str = "unknown"

    @abstractmethod
    def attach(self) -> None:
        """Locate and open the game process. Raise on failure."""

    @abstractmethod
    def find_active_vinyl_group(self) -> VinylGroupHandle:
        """Locate the currently-loaded vinyl group in memory. Caller must have already
        loaded a template group with N pre-allocated shapes inside the game.
        """

    @abstractmethod
    def inject(self, shapes: list, group: VinylGroupHandle) -> InjectResult:
        """Overwrite the shape slots in `group` with `shapes`. The number of slots
        in the group must be >= len(shapes) (per the 3000-sphere template workflow).
        """

    def detach(self) -> None:  # default no-op
        pass


from fd6.inject.fh6_injector import FH6Injector, patterns_are_populated  # noqa: E402


# FH6 stores the primitive selector at layer offset 0x7A as a *16-bit word*.
# The legacy FD6 injector historically wrote only the low byte. That happens to
# work when the stale high byte is already zero, but mixed-shape templates can
# retain a non-zero high byte and FH6 then resolves the wrong resource/primitive.
#
# Keep the proven locator/write path in fh6_injector.py untouched, then finish a
# successful injection by writing the complete uint16 primitive word for every
# safe written layer. This is intentionally narrow: only the shape word is
# corrected here; volatile resource pointers are never copied or changed.
_ORIGINAL_FH6_INJECT = FH6Injector.inject


def _inject_with_full_shape_words(
    self,
    shapes: list,
    group: VinylGroupHandle,
    progress_cb=None,
    image_size: tuple[int, int] | None = None,
    coord_scale: float = 1.0,
) -> InjectResult:
    result = _ORIGINAL_FH6_INJECT(
        self,
        shapes,
        group,
        progress_cb=progress_cb,
        image_size=image_size,
        coord_scale=coord_scale,
    )
    if not result.success or self._proc is None:
        return result

    layer_addrs: list[int] = (group.meta or {}).get("layer_addrs") or []
    if not layer_addrs:
        return result

    # Import internals only after fh6_injector has completed loading, avoiding
    # circular-import problems during package initialization.
    from fd6.inject import fh6_injector as _impl

    corrected = 0
    for i, shape in enumerate(shapes[: len(layer_addrs)]):
        lptr = layer_addrs[i]
        if not _impl._is_user_ptr(lptr) or _impl._score_layer(self._proc, lptr) < 5:
            continue

        if hasattr(shape, "to_json"):
            sd = shape.to_json()
        elif isinstance(shape, dict):
            sd = shape
        else:
            continue

        shape_type = str(sd.get("type", "rotated_ellipse"))
        shape_word = self.profile.shape_id_map.get(shape_type)
        if shape_word is None:
            # Preserve legacy classification for compatible JSON aliases.
            is_ellipse = "ellipse" in shape_type or shape_type == "circle"
            shape_word = (
                self.profile.shape_id_ellipse
                if is_ellipse
                else self.profile.shape_id_other
            )

        try:
            self._proc.write(
                lptr + self.profile.layer_shape_id_offset,
                struct.pack("<H", int(shape_word) & 0xFFFF),
            )
            corrected += 1
        except OSError:
            continue

    if corrected:
        result.message += (
            f" Rewrote {corrected} FH6 primitive selector(s) as full 16-bit "
            "shape words at layer+0x7A. Save the vinyl group and reopen it "
            "before judging mixed-shape rendering."
        )
    return result


FH6Injector.inject = _inject_with_full_shape_words

__all__ = ["Injector", "VinylGroupHandle", "InjectResult", "FH6Injector", "patterns_are_populated"]
