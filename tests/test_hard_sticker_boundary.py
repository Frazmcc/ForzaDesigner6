import random

import numpy as np
from PIL import Image

from fd6.shapegen.profile import load_profile
from fd6.shapegen.scoring import _respects_hard_alpha_boundary, score_shape
from fd6.shapegen.shapes.ellipse import RotatedEllipse
from fd6.shapegen.shapes.rectangle import RotatedRectangle
from fd6.shapegen.worker import prepare_solid_logo_rgba


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


def test_solid_logo_preprocessing_removes_antialias_grey():
    rgba = Image.fromarray(
        np.array(
            [
                [[80, 80, 80, 40], [120, 120, 120, 127], [180, 180, 180, 128], [240, 240, 240, 255]],
            ],
            dtype=np.uint8,
        ),
        "RGBA",
    )

    rgb, alpha = prepare_solid_logo_rgba(rgba, 128)
    out = np.asarray(rgb, dtype=np.uint8)

    # Colour is never inherited from the PNG anti-alias fringe: all legal logo
    # pixels target pure black, and membership is decided only by alpha.
    assert np.all(out == 0)
    assert alpha.tolist() == [[0, 0, 255, 255]]


def test_solid_logo_profile_round_trip_fields_parse():
    profile = load_profile(
        "solid-test",
        """[profile]\nsolidLogoMode = true\nsolidLogoAlphaThreshold = 140\npreserveTransparency = true\n""",
    )
    assert profile.solid_logo_mode is True
    assert profile.solid_logo_alpha_threshold == 140
    assert profile.preserve_transparency is True
