from __future__ import annotations

import numpy as np

from fd6.shapegen.shapes.base import Shape


# Replica-first scoring.  Every run has the same objective regardless of layer
# count: minimise visible difference from the source.  Extra layers only give
# the optimiser more budget to approach that objective.
EDGE_BOOST = 10.0
SILHOUETTE_EDGE_BOOST = 18.0
SILHOUETTE_INNER_BOOSTS = (12.0, 7.0, 4.0)


def _shift_bool(mask: np.ndarray, dy: int, dx: int) -> np.ndarray:
    """Return mask shifted by (dy, dx), filling exposed pixels with False."""
    out = np.zeros_like(mask, dtype=bool)
    h, w = mask.shape
    sy0 = max(0, -dy)
    sy1 = min(h, h - dy)
    sx0 = max(0, -dx)
    sx1 = min(w, w - dx)
    dy0 = max(0, dy)
    dy1 = dy0 + (sy1 - sy0)
    dx0 = max(0, dx)
    dx1 = dx0 + (sx1 - sx0)
    if sy1 > sy0 and sx1 > sx0:
        out[dy0:dy1, dx0:dx1] = mask[sy0:sy1, sx0:sx1]
    return out


def _dilate8(mask: np.ndarray) -> np.ndarray:
    """One-pixel 8-neighbour dilation without a SciPy dependency."""
    out = mask.copy()
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dy == 0 and dx == 0:
                continue
            out |= _shift_bool(mask, dy, dx)
    return out


def _silhouette_boundary(allowed: np.ndarray) -> np.ndarray:
    """Pixels inside the source silhouette that touch forbidden transparency."""
    if not allowed.any():
        return np.zeros_like(allowed, dtype=bool)
    all_neighbours_inside = np.ones_like(allowed, dtype=bool)
    for dy, dx in ((-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)):
        all_neighbours_inside &= _shift_bool(allowed, dy, dx)
    return allowed & ~all_neighbours_inside


def _rgb_gradient_strength(target: np.ndarray) -> np.ndarray:
    """Sobel-like RGB gradient in [0, 1], preserving coloured edges too.

    Using only luminance can miss strong colour transitions with similar
    brightness.  A replica optimiser must see both tonal and chromatic edges,
    so compute the Sobel magnitude independently per channel and keep the
    strongest channel response.
    """
    h, w = target.shape[:2]
    t = target.astype(np.float32)
    mags: list[np.ndarray] = []
    for channel in range(3):
        src = t[:, :, channel]
        pad = np.pad(src, 1, mode="edge")
        gx = (
            -pad[0:h, 0:w] + pad[0:h, 2:w + 2]
            - 2.0 * pad[1:h + 1, 0:w] + 2.0 * pad[1:h + 1, 2:w + 2]
            - pad[2:h + 2, 0:w] + pad[2:h + 2, 2:w + 2]
        )
        gy = (
            -pad[0:h, 0:w] - 2.0 * pad[0:h, 1:w + 1] - pad[0:h, 2:w + 2]
            + pad[2:h + 2, 0:w] + 2.0 * pad[2:h + 2, 1:w + 1] + pad[2:h + 2, 2:w + 2]
        )
        mags.append(np.sqrt(gx * gx + gy * gy))
    mag = np.maximum.reduce(mags)
    # Robust normalization prevents a single extreme highlight from making all
    # other useful edges look insignificant.
    positive = mag[mag > 1e-6]
    if positive.size == 0:
        return np.zeros((h, w), dtype=np.float32)
    scale = float(np.percentile(positive, 99.0))
    if scale < 1e-6:
        scale = float(positive.max())
    return np.clip(mag / max(scale, 1e-6), 0.0, 1.0).astype(np.float32)


def compute_edge_weight(
    target: np.ndarray,
    alpha_mask: np.ndarray | None = None,
    boost: float = EDGE_BOOST,
) -> np.ndarray:
    """Build an H×W replica-importance map.

    The optimisation objective is the same for 500 or 2500 layers.  This map
    simply says which source errors are most visually expensive:

    * baseline interior pixels still count (weight 1), so texture and colour are
      never discarded;
    * RGB/chromatic edges receive up to ``boost`` weight;
    * for transparent artwork, the exact visible silhouette receives the
      strongest weight, with a three-pixel inward refinement band so later
      small primitives smooth the contour rather than spending all remaining
      budget on low-value interior texture;
    * fully transparent pixels remain weight 0 and are also a hard geometric
      rejection boundary in ``score_shape``.
    """
    gradient = _rgb_gradient_strength(target)
    weight = 1.0 + (float(boost) - 1.0) * gradient

    if alpha_mask is not None:
        allowed = alpha_mask > 0
        weight *= allowed.astype(np.float32)

        boundary = _silhouette_boundary(allowed)
        if boundary.any():
            weight[boundary] = np.maximum(weight[boundary], SILHOUETTE_EDGE_BOOST)
            previous = boundary
            covered = boundary.copy()
            for band_boost in SILHOUETTE_INNER_BOOSTS:
                expanded = _dilate8(previous) & allowed & ~covered
                if not expanded.any():
                    break
                weight[expanded] = np.maximum(weight[expanded], float(band_boost))
                covered |= expanded
                previous = expanded

    return weight.astype(np.float32)


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
    """True only when every rasterized candidate pixel stays inside source alpha."""
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
    """Composite one complete primitive exactly as FH6 will render it."""
    h, w = current.shape[:2]
    mask_local, bbox = shape.rasterize_mask(w, h)
    x0, y0, x1, y1 = bbox
    if x1 <= x0 or y1 <= y0 or mask_local.size == 0:
        return current, rms_error(current, target, alpha_mask, edge_weight)

    if alpha_mask is not None:
        region_alpha = alpha_mask[y0:y1, x0:x1]
        if not _respects_hard_alpha_boundary(mask_local, region_alpha):
            return current, rms_error(current, target, alpha_mask, edge_weight)

    # Legal sticker primitives are rendered whole by Forza.  Colour fitting
    # therefore uses the whole legal primitive as well; clipping it by source
    # alpha here would make the optimiser and preview disagree with injection.
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

    The transparent source silhouette is an absolute geometric constraint.  A
    legal candidate is then ranked by the replica-importance map, so the same
    objective applies at every layer count: best possible reconstruction of the
    source with the budget available.
    """
    h, w = current.shape[:2]
    mask_local, bbox = shape.rasterize_mask(w, h)
    x0, y0, x1, y1 = bbox
    if x1 <= x0 or y1 <= y0 or mask_local.size == 0:
        return float("inf"), shape.color

    if alpha_mask is not None:
        region_alpha = alpha_mask[y0:y1, x0:x1]
        if not _respects_hard_alpha_boundary(mask_local, region_alpha):
            return float("inf"), shape.color

    effective_mask = mask_local
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
