"""Per-game profiles for FD6 injection.

Each profile bundles everything that differs between Forza titles:
  - process name(s) to attach to
  - struct offsets within the LiveryGroup and Layer types
  - the MSVC RTTI class-name string used by the optional vtable locator
  - the scale divisors used when packing JSON scale fields into FH world units
  - target-aware generator->Forza primitive shape-id mapping

Offsets and scale divisors for FH5 and FH6 are confirmed identical via the
public bvzrays/forza-painter-fh6 source (MIT). FH4 is provided as a beta
profile using the same layout under the working assumption that the Forge
engine carries the same CLiveryGroup struct across the FH4/FH5/FH6 lineage.
"""

from __future__ import annotations

from dataclasses import dataclass, field


RTTI_CLIVERY_GROUP = b".?AVCLiveryGroup@@"

# Stage 2 safe mapping: only primitives with verified-safe injector mapping.
# Triangle is intentionally NOT listed until native FH triangle mapping is proven.
DEFAULT_SHAPE_ID_MAP = {
    "rotated_ellipse": 102,
    "ellipse": 102,
    "circle": 102,
    "rectangle": 101,
    "rotated_rectangle": 101,
}


@dataclass(frozen=True)
class GameProfile:
    key: str
    label: str
    process_names: tuple[str, ...]
    rtti_class_name: bytes = RTTI_CLIVERY_GROUP

    # LiveryGroup offsets
    livery_count_offset: int = 0x5A
    layer_table_offset: int = 0x78

    # Layer offsets
    layer_position_offset: int = 0x18
    layer_scale_offset: int = 0x28
    layer_rotation_offset: int = 0x50
    layer_color_offset: int = 0x74
    layer_mask_offset: int = 0x78
    layer_shape_id_offset: int = 0x7A

    # Divisors
    scale_divisor_ellipse: float = 63.0
    scale_divisor_other: float = 127.0

    # Legacy ids kept for compatibility / docs
    shape_id_ellipse: int = 102
    shape_id_other: int = 101

    # Stage 2: target-aware primitive support map
    shape_id_map: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_SHAPE_ID_MAP))

    beta: bool = False
    beta_note: str = ""


FH6 = GameProfile(
    key="fh6",
    label="Forza Horizon 6",
    process_names=("forzahorizon6.exe", "ForzaHorizon6-Win64-Shipping.exe"),
)

FH5 = GameProfile(
    key="fh5",
    label="Forza Horizon 5 (BETA)",
    process_names=("ForzaHorizon5.exe", "forzahorizon5.exe"),
    beta=True,
    beta_note=(
        "FH5 uses the same struct layout as FH6 according to publicly available "
        "research (bvzrays/forza-painter-fh6). Not independently validated by FD6 "
        "against a live FH5 install yet."
    ),
)

FH4 = GameProfile(
    key="fh4",
    label="Forza Horizon 4",
    process_names=("ForzaHorizon4.exe", "forzahorizon4.exe"),
)

FH3 = GameProfile(
    key="fh3",
    label="Forza Horizon 3 (BETA)",
    process_names=("ForzaHorizon3.exe", "forzahorizon3.exe"),
    beta=True,
    beta_note=(
        "FH3 support is highly experimental. Struct compatibility is assumed from "
        "Forge lineage but not fully validated by FD6."
    ),
)

PROFILES: dict[str, GameProfile] = {
    FH6.key: FH6,
    FH5.key: FH5,
    FH4.key: FH4,
    FH3.key: FH3,
}


def get_profile(key: str) -> GameProfile:
    normalized = (key or "").lower().strip()
    if normalized not in PROFILES:
        supported = ", ".join(PROFILES)
        raise ValueError(f"Unsupported game profile '{key}'. Known: {supported}")
    return PROFILES[normalized]


def default_profile() -> GameProfile:
    return FH6


def list_profiles() -> list[GameProfile]:
    return [FH6, FH5, FH4, FH3]
