from __future__ import annotations

"""Single-process CPU search engine for frozen Windows builds.

The packaged Windows app runs generation in an existing QThread and must not
spawn child Python processes.  This engine therefore performs the CPU search
inline while keeping the same shape/scoring/commit contract as Engine.

Replica-first policy:
- every layer budget has the SAME objective: closest possible reconstruction;
- enabled primitive types compete on fitness instead of receiving fixed quotas;
- unfinished high-error regions are periodically re-weighted;
- most random candidates are proposed near pixels that are still wrong instead
  of wasting the finite search budget uniformly across already-good regions;
- candidate size shrinks aggressively through the run so the back half refines
  contours, lettering and small details instead of adding more coarse blocks;
- a candidate is never allowed to make the true unweighted source RMS worse.
"""

import numpy as np

from fd6.shapegen.engine import Engine
from fd6.shapegen.scoring import precompute_canvas_error, rms_error, score_shape
from fd6.shapegen.shapes import Shape, random_shape


class InlineEngine(Engine):
    """Replica-first Engine variant that never creates a ProcessPoolExecutor."""

    # Re-enable residual guidance in the packaged app, but refresh often enough
    # that the search follows what is CURRENTLY wrong rather than continuing to
    # optimise areas that have already been fixed.  The shrinking size schedule
    # below prevents residual weighting from turning into large late-run smears.
    RESIDUAL_REFRESH_EVERY = 10
    RESIDUAL_BOOST = 3.0

    # Candidate proposal policy. Fitness still decides which primitive wins;
    # this only decides where most RANDOM proposals begin. Keeping 25% uniform
    # proposals preserves exploration and avoids getting trapped in one region.
    FOCUS_CANDIDATE_FRACTION = 0.75
    FOCUS_RESIDUAL_POWER = 1.5

    def _max_size_frac_for_progress(self, progress: float) -> float:
        """Progressive coarse-to-fine geometry schedule for ANY layer count.

        Fractions are relative to canvas size, while the thresholds are relative
        to run progress.  Therefore a 500-layer job and a 2500-layer job follow
        the same reconstruction strategy; the larger budget simply spends more
        absolute layers at every refinement level.
        """
        if progress < 0.10:
            return 0.22   # establish broad colour/form only
        if progress < 0.30:
            return 0.16
        if progress < 0.55:
            return 0.10
        if progress < 0.75:
            return 0.065
        if progress < 0.90:
            return 0.040
        return 0.025      # final 10%: contour/lettering/detail cleanup

    def _build_focus_cdf(self) -> tuple[np.ndarray | None, float]:
        """Build a weighted distribution of pixels that still need correction.

        Uniform random centres spend most candidate evaluations in large flat
        regions once those regions are already close to the target.  That is a
        poor use of a finite random-sample budget.  Instead, combine CURRENT
        source residual with the live edge/silhouette importance map and sample
        most candidate centres from that distribution.

        This is proposal guidance only: score_shape remains the authority, the
        hard transparent boundary still rejects illegal geometry, and 25% of
        candidates remain uniformly placed for global exploration.
        """
        residual = np.abs(
            self.canvas.astype(np.float32) - self.target.astype(np.float32)
        ).mean(axis=2) / 255.0
        residual = np.power(residual, self.FOCUS_RESIDUAL_POWER, dtype=np.float32)

        importance = residual * self.edge_weight.astype(np.float32, copy=False)
        if self.alpha_mask is not None:
            importance *= (self.alpha_mask > 0).astype(np.float32)

        flat = importance.reshape(-1).astype(np.float64)
        total = float(flat.sum())
        if not np.isfinite(total) or total <= 1e-12:
            return None, 0.0
        return np.cumsum(flat), total

    def _focus_candidate(
        self,
        shape: Shape,
        focus_cdf: np.ndarray | None,
        focus_total: float,
    ) -> Shape:
        """Move a proposal centre onto a still-wrong source region most of the time."""
        if (
            focus_cdf is None
            or focus_total <= 0.0
            or not hasattr(shape, "x")
            or not hasattr(shape, "y")
            or self.rng.random() >= self.FOCUS_CANDIDATE_FRACTION
        ):
            return shape

        needle = self.rng.random() * focus_total
        idx = int(np.searchsorted(focus_cdf, needle, side="left"))
        idx = min(max(idx, 0), self.w * self.h - 1)
        y, x = divmod(idx, self.w)

        # Tiny jitter keeps multiple proposals from sharing precisely the same
        # centre while remaining local to the high-value residual region.
        jitter_x = self.rng.uniform(-2.0, 2.0)
        jitter_y = self.rng.uniform(-2.0, 2.0)
        shape.x = max(0.0, min(float(self.w - 1), float(x) + jitter_x))
        shape.y = max(0.0, min(float(self.h - 1), float(y) + jitter_y))
        return shape

    def _parallel_search(
        self,
        types: list[str],
        n_random: int,
        n_mutate: int,
        max_size_frac: float | None = None,
    ) -> tuple[float, Shape | None]:
        """Run a fair competitive search across ALL enabled primitive types.

        Engine.run historically rotates one primitive type per iteration so
        every selected type receives a quota.  That is useful for diagnostics,
        but it is the wrong objective for exact reconstruction: a weaker shape
        should never win merely because it is "its turn".

        The frozen app therefore intentionally ignores that one-type hint and
        considers every enabled profile type on every iteration.  Random budget
        is divided evenly across types, then the single best candidate across
        all types receives the mutation/hill-climb budget.

        Candidates are ranked with edge/silhouette weighting, but they must also
        pass a second invariant: their ordinary source RMS may not increase.
        This keeps the optimiser faithful to the whole image while still using
        stronger weights to decide WHERE the next useful layer should go.
        """
        n_random = max(1, n_random)
        n_mutate = max(1, n_mutate)

        allowed_types = [t for t in getattr(self.profile, "shape_types", []) if t]
        if not allowed_types:
            allowed_types = [t for t in types if t] or ["rotated_ellipse"]

        # Weighted canvas error drives salience/edge preference.
        weighted_full_sq, weighted_norm = precompute_canvas_error(
            self.canvas,
            self.target,
            self.alpha_mask,
            self.edge_weight,
        )
        # Ordinary source error is the hard monotonic fidelity guard.
        raw_full_sq, raw_norm = precompute_canvas_error(
            self.canvas,
            self.target,
            self.alpha_mask,
            None,
        )
        current_raw_rms = float(np.sqrt(max(0.0, raw_full_sq) / max(raw_norm, 1.0)))

        # Build once per committed layer, not once per candidate. This turns the
        # finite random budget into useful local proposals around the current
        # residual while keeping the score math unchanged.
        focus_cdf, focus_total = self._build_focus_cdf()

        best_score = float("inf")
        best_color = None
        best_shape: Shape | None = None

        # Equal candidate opportunity per enabled primitive.  This is NOT an
        # output quota: only fitness decides what actually gets committed.
        base_count = n_random // len(allowed_types)
        remainder = n_random % len(allowed_types)

        for type_index, type_name in enumerate(allowed_types):
            candidate_count = max(1, base_count + (1 if type_index < remainder else 0))
            for _ in range(candidate_count):
                shape = random_shape(
                    self.rng,
                    self.w,
                    self.h,
                    [type_name],
                    max_size_frac=max_size_frac,
                )
                shape = self._focus_candidate(shape, focus_cdf, focus_total)

                weighted_score, color = score_shape(
                    shape,
                    self.canvas,
                    self.target,
                    self.alpha_mask,
                    canvas_full_sq=weighted_full_sq,
                    canvas_norm=weighted_norm,
                    edge_weight=self.edge_weight,
                )
                if not np.isfinite(weighted_score):
                    continue

                # Same primitive/color fitting, but measured against the true
                # unweighted image.  Reject anything that makes the overall
                # source reconstruction worse even if it helps a highly-weighted
                # edge region.
                raw_score, _ = score_shape(
                    shape,
                    self.canvas,
                    self.target,
                    self.alpha_mask,
                    canvas_full_sq=raw_full_sq,
                    canvas_norm=raw_norm,
                    edge_weight=None,
                )
                if raw_score > current_raw_rms + 1e-9:
                    continue

                if weighted_score < best_score:
                    best_score = weighted_score
                    best_color = color
                    best_shape = shape

        if best_shape is None:
            return float("inf"), None

        best_shape.color = best_color
        no_improve = 0

        # Refine the geometry that actually won the cross-type competition.
        for _ in range(n_mutate):
            candidate = best_shape.mutate(self.rng, self.w, self.h)
            weighted_score, color = score_shape(
                candidate,
                self.canvas,
                self.target,
                self.alpha_mask,
                canvas_full_sq=weighted_full_sq,
                canvas_norm=weighted_norm,
                edge_weight=self.edge_weight,
            )
            if not np.isfinite(weighted_score):
                no_improve += 1
                continue

            raw_score, _ = score_shape(
                candidate,
                self.canvas,
                self.target,
                self.alpha_mask,
                canvas_full_sq=raw_full_sq,
                canvas_norm=raw_norm,
                edge_weight=None,
            )
            if raw_score > current_raw_rms + 1e-9:
                no_improve += 1
                if no_improve >= max(30, n_mutate // 3):
                    break
                continue

            if weighted_score < best_score:
                best_score = weighted_score
                best_color = color
                best_shape = candidate
                no_improve = 0
            else:
                no_improve += 1
                if no_improve >= max(30, n_mutate // 3):
                    break

        if best_color is not None:
            best_shape.color = best_color

        return best_score, best_shape

    def run(self):
        """Expose ordinary source RMS in progress/done events.

        The base Engine uses edge-weighted scoring to choose useful shapes, and
        composite() returns that weighted RMS.  That number is not comparable to
        the unweighted RMS used at engine startup.  Recalculate the true source
        RMS before every externally visible event so progress is apples-to-apples
        and can never appear to get worse merely because the weighting changed.
        """
        for event in super().run():
            if event.kind in {"shape_committed", "preview", "checkpoint", "done"}:
                true_rms = rms_error(self.canvas, self.target, self.alpha_mask)
                self.rms = true_rms
                event.rms = true_rms
            yield event
