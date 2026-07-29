"""
The growth-curve sparkline: inline SVG from db.get_video_history, drawn
like a scope readout per BUILD_SPEC.md's Design Direction -- 120x28,
thin stroke, no fill, no gridlines, no axis labels. The shape is the
information; nothing else about it is decoration.
"""


def render_sparkline(history: list, metric: str = "views", width: int = 120, height: int = 28) -> str:
    values = [h[metric] for h in history if h.get(metric) is not None]

    if not values:
        return f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}"></svg>'

    if len(values) == 1:
        cx, cy = width / 2, height / 2
        return (
            f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}">'
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="1.5" fill="currentColor" /></svg>'
        )

    lo, hi = min(values), max(values)
    span = hi - lo
    n = len(values)

    def x(i):
        return (i / (n - 1)) * width

    def y(v):
        return height / 2 if span == 0 else height - ((v - lo) / span) * height

    points = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(values))
    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}">'
        f'<polyline points="{points}" fill="none" stroke="currentColor" stroke-width="1.5" /></svg>'
    )
