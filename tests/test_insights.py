"""The insights report generates end to end on the real warehouse."""

import pytest

pytest.importorskip("scipy")
pytest.importorskip("matplotlib")

from spotify_pipeline import insights  # noqa: E402


def test_effect_labels():
    assert insights.effect_label(0.05) == "negligible"
    assert insights.effect_label(-0.17) == "weak"
    assert insights.effect_label(0.69) == "large"


def test_mann_whitney_detects_separation():
    result = insights.mann_whitney([10, 11, 12, 13, 14], [1, 2, 3, 4, 5], "a", "b")
    assert result.effect_size == 1.0
    assert result.p_value < 0.05


def test_generate_report(real_warehouse, tmp_path):
    import matplotlib

    matplotlib.use("Agg")
    con, settings = real_warehouse
    report = tmp_path / "docs" / "insights.md"
    insights.generate(con, settings.sql_dir, report)
    text = report.read_text()
    assert "## Executive summary" in text
    assert "Mann-Whitney" in text
    assert len(list((tmp_path / "docs" / "figures").glob("*.png"))) == 7
