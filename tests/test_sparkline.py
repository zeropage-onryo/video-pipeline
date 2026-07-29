"""
Tests for app/sparkline.py -- the inline growth-curve SVG. Per
BUILD_SPEC.md's Design Direction: 120x28, thin stroke, no fill, no
gridlines, no axis labels. Built and tested in isolation before it's
wired into the dashboard.
"""
from app.sparkline import render_sparkline


def test_empty_history_renders_an_empty_svg():
    svg = render_sparkline([])
    assert "<svg" in svg
    assert "polyline" not in svg
    assert "circle" not in svg


def test_single_point_renders_a_circle_not_a_line():
    svg = render_sparkline([{"views": 100}])
    assert "<circle" in svg
    assert "polyline" not in svg


def test_multiple_points_render_a_polyline_with_no_fill():
    history = [{"views": 10}, {"views": 50}, {"views": 30}]
    svg = render_sparkline(history)
    assert "<polyline" in svg
    assert 'fill="none"' in svg
    points = svg.split('points="')[1].split('"')[0]
    assert len(points.split()) == 3


def test_dimensions_are_120x28_by_default():
    svg = render_sparkline([{"views": 1}, {"views": 2}])
    assert 'width="120"' in svg
    assert 'height="28"' in svg


def test_custom_dimensions_are_respected():
    svg = render_sparkline([{"views": 1}, {"views": 2}], width=200, height=40)
    assert 'width="200"' in svg
    assert 'height="40"' in svg


def test_flat_history_does_not_crash():
    svg = render_sparkline([{"views": 50}, {"views": 50}, {"views": 50}])
    assert "<polyline" in svg


def test_ignores_none_values():
    history = [{"views": 10}, {"views": None}, {"views": 30}]
    svg = render_sparkline(history)
    points = svg.split('points="')[1].split('"')[0]
    assert len(points.split()) == 2


def test_metric_is_configurable():
    history = [{"likes": 5}, {"likes": 9}]
    svg = render_sparkline(history, metric="likes")
    points = svg.split('points="')[1].split('"')[0]
    assert len(points.split()) == 2
