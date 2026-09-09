from __future__ import annotations

"""Single-process CPU search engine for frozen Windows builds.

The packaged Windows app runs generation in an existing QThread and must not
spawn child Python processes.  This engine therefore performs the CPU search
inline while keeping the same shape/scoring/commit contract as Engine.

Replica-first policy:
- every layer budget has the SAME objective: closest possible reconstruction;
- enabled primitive types compete on fitness instead of receiving fixed quotas;
- unfinished high-error regions are periodically re-weighted;
- candidate size shrinks aggressively through the run so the back half refines
  contours, lettering and small details instead of adding more coarse blocks.
"""

from fd6.shapegen.engine import Engine
from fd6.shapegen.scoring import precompute_canvas_error, score_shape
from fd6.shapegen.shapes import Shape, random_shape


class InlineEngine(Engine):
    """Replica-first Engine variant that never creates a ProcessPoolExecutor."""

    # Re-enable residual guidance in the packaged app, but refresh often enough
    # that the search follows what is CURRENTLY wrong rather than continuing to
    # optimise areas that have already been fixed.  The shrinking size schedule
    # below prevents residual weighting from turning into large late-run smears.
    RESIDUAL_REFRESH_EVERY = 10
    RESIDUAL_BOOST = 3.0

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
        """
        n_random = max(1, n_random)
        n_mutate = max(1, n_mutate)

        allowed_types = [t for t in getattr(self.profile, "shape_types", []) if t]
        if not allowed_types:
            allowed_types = [t for t in types if t] or ["rotated_ellipse"]

        canvas_full_sq, canvas_norm = precompute_canvas_error(
            self.canvas,
            self.target,
            self.alpha_mask,
            self.edge_weight,
        )

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
                score, color = score_shape(
                    shape,
                    self.canvas,
                    self.target,
                    self.alpha_mask,
                    canvas_full_sq=canvas_full_sq,
                    canvas_norm=canvas_norm,
                    edge_weight=self.edge_weight,
                )
                if score < best_score:
                    best_score = score
                    best_color = color
                    best_shape = shape

        if best_shape is None:
            return float("inf"), None

        best_shape.color = best_color
        no_improve = 0

        # Refine the geometry that actually won the cross-type competition.
        for _ in range(n_mutate):
            candidate = best_shape.mutate(self.rng, self.w, self.h)
            score, color = score_shape(
                candidate,
                self.canvas,
                self.target,
                self.alpha_mask,
                canvas_full_sq=canvas_full_sq,
                canvas_norm=canvas_norm,
                edge_weight=self.edge_weight,
            )
            if score < best_score:
                best_score = score
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
