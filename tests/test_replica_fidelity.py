from __future__ import annotations

import random
from types import SimpleNamespace

import numpy as np

from fd6.shapegen.inline_engine import InlineEngine
from fd6.shapegen.scoring import compute_edge_weight


def test_transparent_silhouette_boundary_is_highest_priority() -> None:
    target = np.full((9, 9, 3), 120, dtype=np.uint8)
    alpha = np.zeros((9, 9), dtype=np.uint8)
    alpha[2:7, 2:7] = 255

    weight = compute_edge_weight(target, alpha)

    assert weight[0, 0] == 0.0
    assert weight[4, 4] >= 1.0
    assert weight[2, 4] > weight[4, 4]
    assert weight[2, 4] >= 12.0


def test_coloured_edge_is_detected_even_with_similar_luminance() -> None:
    target = np.zeros((12, 12, 3), dtype=np.uint8)
    target[:, :6] = (255, 0, 0)
    target[:, 6:] = (0, 130, 0)

    weight = compute_edge_weight(target)

    assert float(weight[:, 5:7].mean()) > float(weight[:, :2].mean())


def test_detail_schedule_is_coarse_to_fine_for_every_budget() -> None:
    engine = InlineEngine.__new__(InlineEngine)

    values = [
        engine._max_size_frac_for_progress(0.00),
        engine._max_size_frac_for_progress(0.20),
        engine._max_size_frac_for_progress(0.50),
        engine._max_size_frac_for_progress(0.70),
        engine._max_size_frac_for_progress(0.85),
        engine._max_size_frac_for_progress(0.95),
    ]

    assert values == sorted(values, reverse=True)
    assert values[-1] <= 0.025


def test_focus_distribution_targets_remaining_error() -> None:
    engine = InlineEngine.__new__(InlineEngine)
    engine.w = 8
    engine.h = 8
    engine.canvas = np.zeros((8, 8, 3), dtype=np.uint8)
    engine.target = np.zeros((8, 8, 3), dtype=np.uint8)
    engine.target[6, 5] = (255, 255, 255)
    engine.alpha_mask = None
    engine.edge_weight = np.ones((8, 8), dtype=np.float32)
    engine.rng = random.Random(7)

    cdf, total = engine._build_focus_cdf()

    assert cdf is not None
    assert total > 0.0
    flat_index = 6 * 8 + 5
    before = cdf[flat_index - 1] if flat_index > 0 else 0.0
    assert before == 0.0
    assert cdf[flat_index] == total


def test_focused_candidate_moves_near_remaining_error() -> None:
    class DummyShape:
        x = 0.0
        y = 0.0

    engine = InlineEngine.__new__(InlineEngine)
    engine.w = 10
    engine.h = 10
    engine.canvas = np.zeros((10, 10, 3), dtype=np.uint8)
    engine.target = np.zeros((10, 10, 3), dtype=np.uint8)
    engine.target[8, 7] = (255, 255, 255)
    engine.alpha_mask = None
    engine.edge_weight = np.ones((10, 10), dtype=np.float32)
    engine.rng = random.Random(1)
    engine.FOCUS_CANDIDATE_FRACTION = 1.0

    cdf, total = engine._build_focus_cdf()
    shape = engine._focus_candidate(DummyShape(), cdf, total)

    assert abs(shape.x - 7.0) <= 2.0
    assert abs(shape.y - 8.0) <= 2.0


def test_detail_hotspot_shrinks_ellipse_geometry() -> None:
    class DummyEllipse:
        x = 5.0
        y = 5.0
        rx = 20.0
        ry = 10.0

    engine = InlineEngine.__new__(InlineEngine)
    engine.w = 12
    engine.h = 12
    engine.edge_weight = np.ones((12, 12), dtype=np.float32)
    engine.edge_weight[5, 5] = 10.0
    engine.rng = random.Random(2)

    shape = DummyEllipse()
    result = engine._shrink_shape_for_detail_hotspot(shape)

    assert 1.0 <= result.rx < 20.0
    assert 1.0 <= result.ry < 10.0


def test_flat_region_does_not_force_detail_shrink() -> None:
    class DummyRectangle:
        x = 4.0
        y = 4.0
        hw = 12.0
        hh = 8.0

    engine = InlineEngine.__new__(InlineEngine)
    engine.w = 10
    engine.h = 10
    engine.edge_weight = np.ones((10, 10), dtype=np.float32)
    engine.rng = random.Random(3)

    shape = DummyRectangle()
    result = engine._shrink_shape_for_detail_hotspot(shape)

    assert result.hw == 12.0
    assert result.hh == 8.0


def test_enabled_shape_types_compete_instead_of_receiving_output_quota(monkeypatch) -> None:
    import fd6.shapegen.inline_engine as inline_module

    class DummyShape:
        def __init__(self, type_name: str) -> None:
            self.type_name = type_name
            self.color = (0, 0, 0, 255)

        def mutate(self, _rng, _w, _h):
            return self

    seen: list[str] = []

    def fake_random_shape(_rng, _w, _h, allowed_types, max_size_frac=None):
        del max_size_frac
        seen.append(allowed_types[0])
        return DummyShape(allowed_types[0])

    def fake_score_shape(shape, *_args, **_kwargs):
        score = 1.0 if shape.type_name == "rotated_rectangle" else 10.0
        return score, (0, 0, 0, 255)

    monkeypatch.setattr(inline_module, "random_shape", fake_random_shape)
    monkeypatch.setattr(inline_module, "score_shape", fake_score_shape)

    engine = InlineEngine.__new__(InlineEngine)
    engine.canvas = np.zeros((4, 4, 3), dtype=np.uint8)
    engine.target = np.zeros((4, 4, 3), dtype=np.uint8)
    engine.alpha_mask = None
    engine.edge_weight = np.ones((4, 4), dtype=np.float32)
    engine.w = 4
    engine.h = 4
    engine.rng = random.Random(123)
    engine.profile = SimpleNamespace(
        shape_types=["rotated_ellipse", "rotated_rectangle"],
    )

    score, winner = engine._parallel_search(
        ["rotated_ellipse"], 20, 1, max_size_frac=0.1,
    )

    assert "rotated_ellipse" in seen
    assert "rotated_rectangle" in seen
    assert score == 1.0
    assert winner is not None
    assert winner.type_name == "rotated_rectangle"
