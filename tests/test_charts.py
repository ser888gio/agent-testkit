from agentaudit.reports.charts import (
    VIEW_H,
    VIEW_W,
    bar_rows,
    donut_segments,
    sparkline_points,
)


def _ys(points: str) -> list[float]:
    return [float(p.split(",")[1]) for p in points.split()]


def test_sparkline_pins_the_axis_to_the_score_scale():
    """A 90 must not look like a disaster next to a 95."""
    points = sparkline_points([90, 95])

    # Pinned to 0-100, so 90 sits near the top rather than at the floor.
    assert _ys(points) == [VIEW_H * 0.10, VIEW_H * 0.05]


def test_sparkline_inverts_y_because_svg_grows_downward():
    assert _ys(sparkline_points([0, 100])) == [VIEW_H, 0.0]


def test_sparkline_spans_the_full_width():
    xs = [float(p.split(",")[0]) for p in sparkline_points([10, 20, 30]).split()]

    assert xs[0] == 0.0
    assert xs[-1] == VIEW_W


def test_sparkline_handles_empty_and_single_values():
    assert sparkline_points([]) == ""
    # One vertex draws nothing, so a lone score becomes a flat line.
    single = sparkline_points([50])
    assert len(single.split()) == 2
    assert _ys(single) == [VIEW_H / 2, VIEW_H / 2]


def test_sparkline_clamps_out_of_range_values():
    assert _ys(sparkline_points([-20, 150])) == [VIEW_H, 0.0]


def test_bar_rows_scale_to_the_widest_bar():
    rows = bar_rows(
        [{"category": "a", "rate": 0.5}, {"category": "b", "rate": 0.25}],
    )

    assert rows[0]["width"] == 100.0
    assert rows[1]["width"] == 50.0
    # The printed number keeps the absolute value; only the bar is relative.
    assert [r["percent"] for r in rows] == [50, 25]


def test_bar_rows_survive_an_all_zero_set():
    rows = bar_rows([{"category": "a", "rate": 0.0}])

    assert rows[0]["width"] == 0.0
    assert rows[0]["percent"] == 0


def test_bar_rows_of_nothing_is_nothing():
    assert bar_rows([]) == []


def test_donut_segments_sum_to_the_circumference():
    segments = donut_segments([{"total": 3}, {"total": 1}])

    assert [s["share"] for s in segments] == [75.0, 25.0]
    # Each segment starts where the previous one ended.
    assert [s["offset"] for s in segments] == [0.0, 75.0]


def test_donut_segments_of_an_empty_or_zero_set_is_empty():
    assert donut_segments([]) == []
    assert donut_segments([{"total": 0}]) == []
