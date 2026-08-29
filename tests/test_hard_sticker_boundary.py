import random

import numpy as np

from fd6.shapegen.scoring import _respects_hard_alpha_boundary, score_shape
from fd6.shapegen.shapes.ellipse import RotatedEllipse
from fd6.shapegen.shapes.rectangle import RotatedRectangle


def test_hard_boundary_accepts_shape_fully_inside_alpha():
    mask = np.full((4, 4), 255, dtype=np.uint8)
    alpha = np.full((4, 4), 255, dtype=np.uint8)
    assert _respects_hard_alpha_boundary(mask, alpha)


def test_hard_boundary_rejects_single_pixel_in_transparency():
    mask = np.full((4, 4), 255, dtype=np.uint8)
    alpha = np.full((4, 4), 255, dtype=np.uint8)
    alpha[0, 0] = 0
    assert not _respects_hard_alpha_boundary(mask, alpha)


def test_score_shape_rejects_any_transparent_overlap():
    current = np.full((16, 16, 3), 40, dtype=np.uint8)
    target = np.zeros((16, 16, 3), dtype=np.uint8)
    alpha = np.zeros((16, 16), dtype=np.uint8)
    alpha[4:12, 4:12] = 255

    # This rectangle extends outside the 8x8 allowed silhouette by one or more pixels.
    shape = RotatedRectangle(color=(0, 0, 0, 255), x=8, y=8, hw=5, hh=5, angle=0)
    score, _ = score_shape(shape, current, target, alpha)
    assert score == float("inf")


def test_score_shape_accepts_contained_shape():
    current = np.full((16, 16, 3), 40, dtype=np.uint8)
    target = np.zeros((16, 16, 3), dtype=np.uint8)
    alpha = np.zeros((16, 16), dtype=np.uint8)
    alpha[3:13, 3:13] = 255

    shape = RotatedRectangle(color=(0, 0, 0, 255), x=8, y=8, hw=2, hh=2, angle=0)
    score, _ = score_shape(shape, current, target, alpha)
    assert np.isfinite(score)


def test_logo_primitives_generate_fully_opaque():
    rng = random.Random(123)
    rect = RotatedRectangle.random(rng, 64, 64)
    ellipse = RotatedEllipse.random(rng, 64, 64)
    assert rect.color[3] == 255
    assert ellipse.color[3] == 255
