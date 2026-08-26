from __future__ import annotations

"""Single-process CPU search engine for frozen Windows builds.

PyInstaller one-file builds can be sensitive to spawning ProcessPoolExecutor
workers.  If worker dispatch is not intercepted correctly, a child process can
re-enter the application entrypoint and open another FD6 window.  This engine
keeps exactly the same candidate/scoring/commit pipeline but performs the CPU
search inside the existing GenerationWorker QThread, so no child Python
processes are created.

The normal :class:`fd6.shapegen.engine.Engine` remains unchanged and is still
used for source/development runs where multiprocessing works normally.
"""

from fd6.shapegen.engine import Engine
from fd6.shapegen.scoring import precompute_canvas_error, score_shape
from fd6.shapegen.shapes import Shape, random_shape


class InlineEngine(Engine):
    """Engine variant whose CPU search never creates a ProcessPoolExecutor."""

    def _parallel_search(
        self,
        types: list[str],
        n_random: int,
        n_mutate: int,
        max_size_frac: float | None = None,
    ) -> tuple[float, Shape | None]:
        """Run one full random-search + hill-climb chain in the worker thread.

        One inline chain is intentionally equivalent to one worker's full
        search in the normal multiprocessing engine.  This avoids multiplying
        an already expensive Logo Ultra search by the number of CPU cores while
        providing a reliable fallback for frozen Windows executables.
        """
        n_random = max(1, n_random)
        n_mutate = max(1, n_mutate)

        canvas_full_sq, canvas_norm = precompute_canvas_error(
            self.canvas,
            self.target,
            self.alpha_mask,
            self.edge_weight,
        )

        best_score = float("inf")
        best_color = None
        best_shape: Shape | None = None

        for _ in range(n_random):
            shape = random_shape(
                self.rng,
                self.w,
                self.h,
                types,
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
        cap = n_mutate

        for _ in range(cap):
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
                if no_improve >= max(20, cap // 4):
                    break

        if best_color is not None:
            best_shape.color = best_color

        return best_score, best_shape
