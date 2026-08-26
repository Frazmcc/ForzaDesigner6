import numpy as np

from fd6.shapegen.engine import EngineConfig
from fd6.shapegen.inline_engine import InlineEngine
from fd6.shapegen.profile import Profile


def _make_target(size: int = 32) -> np.ndarray:
    arr = np.full((size, size, 3), 220, dtype=np.uint8)
    arr[8:24, 6:26] = (30, 50, 220)
    return arr


def test_inline_engine_generates_without_process_pool():
    profile = Profile(
        name="inline-test",
        stop_at=4,
        random_samples=30,
        mutated_samples=8,
        preview_every=2,
        save_at=[],
        save_every=0,
        max_threads=1,
        shape_types=["rotated_rectangle", "rotated_ellipse"],
        compute_backend="cpu",
    )
    engine = InlineEngine(_make_target(), EngineConfig(profile=profile, seed=1234))

    events = list(engine.run())

    assert len(engine.shapes) == profile.stop_at
    assert any(event.kind == "shape_committed" for event in events)
    assert any(event.kind == "done" for event in events)
    # The fallback must never construct a ProcessPoolExecutor.
    assert engine._executor is None


def test_inline_engine_reduces_or_preserves_rms():
    profile = Profile(
        name="inline-rms",
        stop_at=3,
        random_samples=25,
        mutated_samples=6,
        preview_every=1,
        save_at=[],
        save_every=0,
        max_threads=1,
        shape_types=["rotated_ellipse"],
        compute_backend="cpu",
    )
    engine = InlineEngine(_make_target(), EngineConfig(profile=profile, seed=99))
    initial_rms = engine.rms

    done_rms = None
    for event in engine.run():
        if event.kind == "done":
            done_rms = event.rms

    assert done_rms is not None
    assert done_rms <= initial_rms
