from fd6.inject.fh6_injector import shape_to_forza_layer_geometry
from fd6.inject.game_profiles import get_profile

def _fh6():
    return get_profile("fh6")

def test_rotated_ellipse_maps():
    g = shape_to_forza_layer_geometry({
        "type": "rotated_ellipse", "x": 10, "y": 20, "rx": 5, "ry": 3, "angle": 30, "color": [1, 2, 3, 4]
    }, _fh6())
    assert g.supported is True
    assert g.forza_shape_id == 102
    assert g.width == 10
    assert g.height == 6

def test_ellipse_maps():
    g = shape_to_forza_layer_geometry({
        "type": "ellipse", "x": 1, "y": 2, "rx": 4, "ry": 6, "color": [1, 2, 3, 255]
    }, _fh6())
    assert g.supported is True
    assert g.forza_shape_id == 102
    assert g.angle == 0.0

def test_circle_maps():
    g = shape_to_forza_layer_geometry({
        "type": "circle", "x": 1, "y": 2, "r": 7, "color": [9, 8, 7, 6]
    }, _fh6())
    assert g.supported is True
    assert g.forza_shape_id == 102
    assert g.width == 14
    assert g.height == 14

def test_rectangle_maps():
    g = shape_to_forza_layer_geometry({
        "type": "rectangle", "x": 200, "y": 300, "hw": 50, "hh": 20, "color": [1, 1, 1, 1]
    }, _fh6())
    assert g.supported is True
    assert g.forza_shape_id == 101
    assert g.width == 100
    assert g.height == 40
    assert g.angle == 0.0

def test_rotated_rectangle_maps():
    g = shape_to_forza_layer_geometry({
        "type": "rotated_rectangle", "x": 200, "y": 300, "hw": 50, "hh": 20, "angle": 35, "color": [1, 2, 3, 4]
    }, _fh6())
    assert g.supported is True
    assert g.forza_shape_id == 101
    assert g.width == 100
    assert g.height == 40
    assert g.angle == 35

def test_triangle_unsupported():
    g = shape_to_forza_layer_geometry({
        "type": "triangle", "x1": 0, "y1": 0, "x2": 10, "y2": 0, "x3": 5, "y3": 10, "color": [255, 0, 0, 255]
    }, _fh6())
    assert g.supported is False
    assert "triangle" in (g.reason or "").lower() or "forza triangle" in (g.reason or "").lower()

def test_triangle_does_not_silently_default_to_origin():
    g = shape_to_forza_layer_geometry({
        "type": "triangle", "x1": 100, "y1": 100, "x2": 200, "y2": 100, "x3": 150, "y3": 250, "color": [0, 255, 0, 255]
    }, _fh6())
    assert g.supported is False
    assert g.x is None and g.y is None
