"""Statistical helpers in modeling.py, validated against known answers and simulations."""

import numpy as np
import pytest

pytest.importorskip("sklearn")
pytest.importorskip("statsmodels")

from spotify_pipeline import modeling  # noqa: E402


def test_kaplan_meier_without_censoring_is_the_empirical_survival():
    curve = modeling.kaplan_meier([1, 2, 2, 3, 5], [1, 1, 1, 1, 1], "x")
    assert modeling.survival_at(curve, 0) == 1.0
    assert modeling.survival_at(curve, 2) == pytest.approx(0.4)
    assert modeling.survival_at(curve, 5) == 0.0
    assert curve.median == 2


def test_kaplan_meier_handles_censoring():
    # 4 tracks; one censored at t=2. S(3) = (3/4) * (1/2) = 0.375.
    curve = modeling.kaplan_meier([1, 2, 3, 4], [1, 0, 1, 1], "x")
    assert modeling.survival_at(curve, 3) == pytest.approx(0.375)


def test_concordance_index_extremes():
    time = np.array([1, 2, 3, 4])
    event = np.ones(4)
    assert modeling.concordance_index(time, event, -time) == 1.0  # high risk exits first
    assert modeling.concordance_index(time, event, time) == 0.0


def test_top_fraction_precision():
    y = np.array([1, 0, 1, 0, 0, 0, 0, 0, 0, 0])
    scores = np.arange(10)[::-1].astype(float)  # first item scored highest
    assert modeling.top_fraction_precision(y, scores, 0.2) == 0.5


def _simulate(rng, proportional: bool, n: int = 600):
    from statsmodels.duration.hazard_regression import PHReg

    x = np.column_stack([rng.normal(size=n), rng.integers(0, 2, n)])
    t = rng.exponential(1 / np.exp(0.3 * x[:, 0] + 0.5 * x[:, 1]))
    if not proportional:  # the binary covariate gets a different hazard shape
        t = np.where(x[:, 1] == 1, rng.weibull(2.5, n) * 0.8, t)
    c = rng.exponential(3, n)
    time, event = np.ceil(np.minimum(t, c) * 20), (t <= c).astype(int)
    res = PHReg(time, x, status=event, ties="efron").fit()
    return modeling.ph_test(res.schoenfeld_residuals, time)[1]


def test_ph_test_is_calibrated_and_has_power():
    """Under true proportional hazards the check rarely fires; when violated it does."""
    rng = np.random.default_rng(7)
    false_alarms = np.mean([_simulate(rng, True) < 0.05 for _ in range(40)])
    power = np.mean([_simulate(rng, False) < 0.05 for _ in range(20)])
    assert false_alarms <= 0.15
    assert power >= 0.9


def test_model_report_generates(real_warehouse, tmp_path):
    import matplotlib

    matplotlib.use("Agg")
    con, _ = real_warehouse
    report = tmp_path / "docs" / "model_report.md"
    modeling.generate(con, report, n_bootstrap=100, n_repeats=3)
    text = report.read_text()
    assert "## 3. Results" in text and "Kaplan-Meier" in text
    assert len(list((tmp_path / "docs" / "figures").glob("*.png"))) == 5
