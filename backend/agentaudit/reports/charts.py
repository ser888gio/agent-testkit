"""Chart geometry for the dashboard: numbers in, SVG coordinates out.

Pure functions, no rendering and no I/O, so the arithmetic is testable without a
TestClient and the templates stay declarative. Charts are inline SVG rather than
a charting library because this ships self-hosted and often air-gapped -- a CDN
script tag is a dependency the deployment cannot satisfy.

Everything here takes already-aggregated rows from `Store`. Nothing in this
module reaches a database, and nothing carries agent output.
"""

from __future__ import annotations

from collections.abc import Sequence

# A viewBox rather than pixel sizes: the SVG scales with its container, so the
# same geometry serves the dashboard and a narrow phone.
VIEW_W = 100.0
VIEW_H = 40.0


def sparkline_points(
    values: Sequence[float], *, width: float = VIEW_W, height: float = VIEW_H
) -> str:
    """`points` for a <polyline>, scaled to the viewBox.

    Scores are a fixed 0-100 scale, so the y-axis is pinned rather than fitted
    to the data: a run at 90 must not look like a disaster because every other
    run scored 95. A single point is emitted as a flat two-point line, since a
    one-vertex polyline draws nothing.
    """
    if not values:
        return ""
    if len(values) == 1:
        y = _y(values[0], height)
        return f"0,{y:.2f} {width:.2f},{y:.2f}"
    step = width / (len(values) - 1)
    return " ".join(f"{i * step:.2f},{_y(v, height):.2f}" for i, v in enumerate(values))


def _y(value: float, height: float) -> float:
    """Score to y, inverted: SVG y grows downward, scores grow upward."""
    clamped = max(0.0, min(100.0, float(value)))
    return height - (clamped / 100.0) * height


def bar_rows(rows: Sequence[dict], *, key: str = "rate", label: str = "category") -> list[dict]:
    """Rows for a horizontal bar chart, widths as percentages of the widest bar.

    Scaled to the largest value rather than to 1.0 so a set of small rates stays
    readable; the printed number carries the absolute value, the bar carries the
    comparison.
    """
    if not rows:
        return []
    peak = max(float(r.get(key, 0)) for r in rows) or 1.0
    return [
        {
            **r,
            "label": r.get(label, ""),
            "value": float(r.get(key, 0)),
            "percent": round(float(r.get(key, 0)) * 100),
            "width": round(float(r.get(key, 0)) / peak * 100, 1),
        }
        for r in rows
    ]


def donut_segments(rows: Sequence[dict], *, key: str = "total") -> list[dict]:
    """Stroke-dasharray segments for a donut, as fractions of the circumference.

    Uses a circumference of 100 so `dasharray` values are readable percentages
    and the template needs no arithmetic of its own.
    """
    total = sum(float(r.get(key, 0)) for r in rows)
    if total <= 0:
        return []
    offset = 0.0
    segments = []
    for r in rows:
        share = float(r.get(key, 0)) / total * 100
        segments.append({**r, "share": round(share, 2), "offset": round(offset, 2)})
        offset += share
    return segments
