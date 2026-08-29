from __future__ import annotations

import numpy as np

from fd6.shapegen.shapes.base import Shape


# Edge-weighted scoring: how much more an edge pixel counts toward fitness vs
# a smooth interior pixel. With EDGE_BOOST=6, a shape that nails a 3px pupil
# outline is worth more than a shape that smooths over a 100px cheek block —
# without this, the random sampler drifts toward big translucent ellipses
# because they get good *averaged* error even when they miss every salient
# detail (eyes, mouths, hard outlines). Cheap Sobel magnitude, normalized to
# [1, EDGE_BOOST] so smooth regions still contribute baseline weight 1.
EDGE_BOOST = 6.0


def compute_edge_weight(
    target: np.ndarray,
    alpha_mask: np.ndarray | None = None,
    boost: float = EDGE_BOOST,
) -> np.ndarray:
    """Build an H×W float32 importance map for `target`.

    Combines a Sobel-gradient magnitude (normalized 0..1) with the alpha mask
    so the result is:
        - 0       where alpha_mask says transparent / buffer (ignored entirely)
        - 1       in smooth interior regions
        - up to `boost` on the strongest edges

    Pass this to `rms_error` / `precompute_canvas_error` / `score_shape` /
    `composite` as the `edge_weight` keyword. Build it ONCE per generation
    (the target doesn't change) and reuse for every score.
    """
    h, w = target.shape[:2]
    lum = (
        target[:, :, 0].astype(np.float32) * 0.299
        + target[:, :, 1].astype(np.float32) * 0.587
        + target[:, :, 2].astype(np.float32) * 0.114
    )
    pad = np.pad(lum, 1, mode="edge")
    gx = (
        -1.0 * pad[0:h, 0:w]   + 0.0 * pad[0:h, 1:w+1]   + 1.0 * pad[0:h, 2:w+2]
        + -2.0 * pad[1:h+1, 0:w] + 0.0 * pad[1:h+1, 1:w+1] + 2.0 * pad[1:h+1, 2:w+2]
        + -1.0 * pad[2:h+2, 0:w] + 0.0 * pad[2:h+2, 1:w+1] + 1.0 * pad[2:h+2, 2:w+2]
    )
    gy = (
        -1.0 * pad[0:h, 0:w]   + -2.0 * pad[0:h, 1:w+1]   + -1.0 * pad[0:h, 2:w+2]
        + 0.0 * pad[1:h+1, 0:w] + 0.0 * pad[1:h+1, 1:w+1] + 0.0 * pad[1:h+1, 2:w+2]
        + 1.0 * pad[2:h+2, 0:w] + 2.0 * pad[2:h+2, 1:w+1] + 1.0 * pad[2:h+2, 2:w+2]
    )
    mag = np.sqrt(gx * gx + gy * gy)
    max_mag = float(mag.max())
    if max_mag < 1e-6:
        norm = np.ones((h, w), dtype=np.float32)
    else:
        norm = 1.0 + (boost - 1.0) * (mag / max_mag).astype(np.float32)
    if alpha_mask is not None:
        norm = norm * (alpha_mask > 0).astype(np.float32)
    return norm


def rms_error(
    a: np.ndarray,
    b: np.ndarray,
    alpha_mask: np.ndarray | None = None,
    edge_weight: np.ndarray | None = None,
) -> float:
    """RMS pixel error between two (H, W, 3) uint8 images. Lower is better."""
    diff = a.astype(np.int32) - b.astype(np.int32)
    sq = diff * diff
    if edge_weight is not None:
        weight = edge_weight[:, :, None]
        total = float((sq * weight).sum())
        n = float(edge_weight.sum() * 3)
        if n < 1:
            return 0.0
        return float(np.sqrt(total / n))
    if alpha_mask is None:
        return float(np.sqrt(sq.mean()))
    weight = (alpha_mask > 0)[:, :, None].astype(np.float32)
    total = float((sq * weight).sum())
    n = float(weight.sum() * 3)
    if n < 1:
        return 0.0
    return float(np.sqrt(total / n))


def compute_optimal_color(
    target: np.ndarray,
    current: np.ndarray,
    mask_local: np.ndarray,
    bbox: tuple[int, int, int, int],
    alpha: int,
) -> tuple[int, int, int, int]:
    """For a given shape mask and fixed alpha, compute the RGB color that minimizes RMS over the masked region."""
    x0, y0, x1, y1 = bbox
    if x1 <= x0 or y1 <= y0 or mask_local.size == 0:
        return (0, 0, 0, alpha)
    tgt = target[y0:y1, x0:x1].astype(np.float32)
    cur = current[y0:y1, x0:x1].astype(np.float32)
    m = mask_local.astype(np.float32) / 255.0
    weight = m.sum()
    if weight < 0.5:
        return (0, 0, 0, alpha)
    a = alpha / 255.0
    if a < 1e-6:
        return (0, 0, 0, alpha)
    src = (tgt - (1.0 - a) * cur) / a
    src_masked = src * m[:, :, None]
    avg = src_masked.reshape(-1, 3).sum(axis=0) / weight
    avg = np.clip(avg, 0, 255).astype(np.int32)
    return (int(avg[0]), int(avg[1]), int(avg[2]), alpha)


def _respects_hard_alpha_boundary(mask_local: np.ndarray, region_alpha: np.ndarray) -> bool:
    """Return True only when every rasterized candidate pixel stays inside source alpha.

    Sticker mode represents a real Forza vinyl group, not a composited bitmap.
    Forza renders the whole primitive; it cannot clip an ellipse/rectangle to the
    PNG alpha mask. Therefore any candidate pixel that overlaps a fully
    transparent source pixel is illegal. We deliberately use ``mask_local > 0``
    rather than a 50%/128 body threshold so even the candidate's anti-aliased
    raster footprint must remain inside the source silhouette.

    Partially transparent source-edge pixels are considered part of the source
    silhouette; only alpha==0 is forbidden. This preserves the original PNG's
    outer support without inventing an artificial inward threshold.
    """
    footprint = mask_local > 0
    if not footprint.any():
        return False
    allowed = region_alpha > 0
    return not bool(np.any(footprint & ~allowed))


def composite(
    current: np.ndarray,
    shape: Shape,
    target: np.ndarray,
    alpha_mask: np.ndarray | None = None,
    edge_weight: np.ndarray | None = None,
) -> tuple[np.ndarray, float]:
    """Composite shape over current canvas with optimal color. Return (new_canvas, new_rms)."""
    h, w = current.shape[:2]
    mask_local, bbox = shape.rasterize_mask(w, h)
    x0, y0, x1, y1 = bbox
    if x1 <= x0 or y1 <= y0 or mask_local.size == 0:
        return current, rms_error(current, target, alpha_mask)
    if alpha_mask is not None:
        region_alpha = alpha_mask[y0:y1, x0:x1]
        # A committed sticker shape should already have passed the strict
        # boundary gate in score_shape. Keep the clipping here as a defensive
        # preview safeguard, but it must never be relied on to make an illegal
        # candidate appear legal.
        effective_mask = np.minimum(mask_local, region_alpha)
    else:
        effective_mask = mask_local
    color = compute_optimal_color(target, current, effective_mask, bbox, shape.color[3])
    new = current.copy()
    a = color[3] / 255.0
    region_cur = new[y0:y1, x0:x1].astype(np.float32)
    region_tgt_color = np.array(color[:3], dtype=np.float32)
    m = (effective_mask.astype(np.float32) / 255.0)[:, :, None]
    blended = m * (a * region_tgt_color + (1.0 - a) * region_cur) + (1.0 - m) * region_cur
    new[y0:y1, x0:x1] = np.clip(blended, 0, 255).astype(np.uint8)
    shape.color = color
    return new, rms_error(new, target, alpha_mask, edge_weight)


def precompute_canvas_error(
    current: np.ndarray,
    target: np.ndarray,
    alpha_mask: np.ndarray | None = None,
    edge_weight: np.ndarray | None = None,
) -> tuple[float, float]:
    """Return (full_canvas_squared_error, normalizer_n) for the current canvas."""
    if edge_weight is not None:
        weight_full = edge_weight[:, :, None]
        diff = (current.astype(np.float32) - target.astype(np.float32)) ** 2
        full_sq = float((diff * weight_full).sum())
        n = float(edge_weight.sum() * 3)
        return full_sq, n
    if alpha_mask is None:
        diff = current.astype(np.int32) - target.astype(np.int32)
        full_sq = float((diff * diff).sum())
        n = float(current.shape[0] * current.shape[1] * 3)
        return full_sq, n
    weight_full = (alpha_mask > 0)[:, :, None].astype(np.float32)
    diff = (current.astype(np.float32) - target.astype(np.float32)) ** 2
    full_sq = float((diff * weight_full).sum())
    n = float(weight_full.sum() * 3)
    return full_sq, n


def score_shape(
    shape: Shape,
    current: np.ndarray,
    target: np.ndarray,
    alpha_mask: np.ndarray | None = None,
    *,
    canvas_full_sq: float | None = None,
    canvas_norm: float | None = None,
    edge_weight: np.ndarray | None = None,
) -> tuple[float, tuple[int, int, int, int]]:
    """Score a candidate without modifying the working canvas.

    Sticker-mode contract is intentionally absolute: if any rasterized part of
    the candidate touches an alpha==0 source pixel, return +inf. This makes the
    transparent boundary a hard geometric constraint rather than a soft score.
    Slight under-fill is preferred to any protrusion outside the source image.
    """
    h, w = current.shape[:2]
    mask_local, bbox = shape.rasterize_mask(w, h)
    x0, y0, x1, y1 = bbox
    if x1 <= x0 or y1 <= y0 or mask_local.size == 0:
        return float("inf"), shape.color

    effective_mask = mask_local
    if alpha_mask is not None:
        region_alpha = alpha_mask[y0:y1, x0:x1]
        if not _respects_hard_alpha_boundary(mask_local, region_alpha):
            return float("inf"), shape.color
        effective_mask = np.minimum(mask_local, region_alpha)

    color = compute_optimal_color(target, current, effective_mask, bbox, shape.color[3])
    a = color[3] / 255.0
    region_cur = current[y0:y1, x0:x1].astype(np.float32)
    region_tgt = target[y0:y1, x0:x1].astype(np.float32)
    src = np.array(color[:3], dtype=np.float32)
    m = (mask_local.astype(np.float32) / 255.0)[:, :, None]
    blended = m * (a * src + (1.0 - a) * region_cur) + (1.0 - m) * region_cur
    diff_in = blended - region_tgt

    if edge_weight is not None:
        if canvas_full_sq is None or canvas_norm is None:
            full_sq, n = precompute_canvas_error(current, target, alpha_mask, edge_weight)
        else:
            full_sq, n = canvas_full_sq, canvas_norm
        weight_region = edge_weight[y0:y1, x0:x1][:, :, None]
        region_old_sq = float((((region_cur - region_tgt) ** 2) * weight_region).sum())
        region_new_sq = float(((diff_in ** 2) * weight_region).sum())
        total_sq = full_sq - region_old_sq + region_new_sq
        if n < 1:
            return 0.0, color
        return float(np.sqrt(max(0.0, total_sq) / n)), color

    if alpha_mask is None:
        if canvas_full_sq is None or canvas_norm is None:
            full_sq, n_px = precompute_canvas_error(current, target, None)
        else:
            full_sq, n_px = canvas_full_sq, canvas_norm
        region_old_sq = float(((region_cur - region_tgt) ** 2).sum())
        region_new_sq = float((diff_in ** 2).sum())
        total_sq = full_sq - region_old_sq + region_new_sq
        return float(np.sqrt(max(0.0, total_sq) / n_px)), color

    if canvas_full_sq is None or canvas_norm is None:
        full_sq, n = precompute_canvas_error(current, target, alpha_mask)
    else:
        full_sq, n = canvas_full_sq, canvas_norm
    weight_region = ((alpha_mask[y0:y1, x0:x1] > 0).astype(np.float32))[:, :, None]
    region_old_sq = float((((region_cur - region_tgt) ** 2) * weight_region).sum())
    region_new_sq = float(((diff_in ** 2) * weight_region).sum())
    total_sq = full_sq - region_old_sq + region_new_sq
    if n < 1:
        return 0.0, color
    return float(np.sqrt(max(0.0, total_sq) / n)), color
