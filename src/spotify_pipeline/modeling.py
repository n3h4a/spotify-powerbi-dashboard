"""Phase 3: survival analysis and chart-longevity prediction.

Two complementary questions:

1. **How long do tracks last?** Survival analysis on chart life, which uses tracks
   still charting when the data ends (censored) instead of discarding them.
   Kaplan-Meier curves, log-rank tests, a landmark analysis and a Cox model.
2. **Can we predict a long chart life early?** Will a track spend 30+ days on the
   chart in its first 180 days? A launch-day model (known at debut) is compared
   with a week-one model (adds the first 7 days of chart movement), on a
   time-based split with bootstrap confidence intervals.

Requires the optional ``ml`` dependencies (scikit-learn, statsmodels, pandas).
Every number in docs/model_report.md is produced here.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import duckdb
import numpy as np

from spotify_pipeline import insights as viz

log = logging.getLogger(__name__)

SEED = 42
TRAIN_CUTOFF = date(2024, 1, 1)  # train: debuts before this date; test: on or after
LANDMARK_DAYS = 7
N_BOOTSTRAP = 2000
AQUA = "#1baf7a"  # categorical slot 3 (validated with slots 1-2 for all-pairs use)

LAUNCH_FEATURES = [
    "debut_position",
    "debut_popularity",
    "log_release_age_days",
    "is_new_release",
    "is_collaboration",
    "n_credited_artists",
    "debut_is_explicit",
    "is_single",
    "duration_minutes",
    "debut_in_holiday_season",
    "artist_prior_tracks",
    "log_artist_prior_chart_days",
]
WEEK_ONE_FEATURES = LAUNCH_FEATURES + [
    "w1_chart_days",
    "w1_best_position",
    "w1_day7_position",
    "w1_position_change",
    "w1_position_slope",
    "w1_max_popularity",
    "w1_climbed",
]
FEATURE_LABELS = {
    "debut_position": "Debut position",
    "debut_popularity": "Popularity at debut",
    "log_release_age_days": "Days from release to debut (log)",
    "is_new_release": "New release (<=30 days old)",
    "is_collaboration": "Collaboration",
    "n_credited_artists": "Number of credited artists",
    "debut_is_explicit": "Explicit",
    "is_single": "Released as a single",
    "duration_minutes": "Duration (minutes)",
    "debut_in_holiday_season": "Debuted in holiday season",
    "artist_prior_tracks": "Artist's prior charting tracks",
    "log_artist_prior_chart_days": "Artist's prior chart days (log)",
    "w1_chart_days": "Week 1: days on chart",
    "w1_best_position": "Week 1: best position",
    "w1_day7_position": "Week 1: position on day 7 (51 = off chart)",
    "w1_position_change": "Week 1: positions gained by day 7",
    "w1_position_slope": "Week 1: position trend (slope)",
    "w1_max_popularity": "Week 1: peak popularity",
    "w1_climbed": "Week 1: climbed above debut",
}


# --------------------------------------------------------------------------- data


def load_features(con: duckdb.DuckDBPyConnection):
    """Feature frame with model-ready transforms (logs, booleans as 0/1)."""
    df = con.execute("SELECT * FROM ml.track_features ORDER BY debut_date, track_key").df()
    df["log_release_age_days"] = np.log1p(df["release_age_days"].astype(float))
    df["log_artist_prior_chart_days"] = np.log1p(df["artist_prior_chart_days"].astype(float))
    for col in df.columns:
        if df[col].dtype == bool:
            df[col] = df[col].astype(int)
    df["debut_date"] = df["debut_date"].dt.date
    return df


# --------------------------------------------------------------------------- prediction


@dataclass
class ModelResult:
    name: str
    feature_set: str
    algorithm: str
    cv_auc: float
    test_auc: float
    test_auc_ci: tuple[float, float]
    average_precision: float
    brier: float
    top20_precision: float
    test_scores: np.ndarray


def _candidates():
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    return {
        "Logistic regression": lambda: make_pipeline(
            StandardScaler(), LogisticRegression(C=0.5, max_iter=2000)
        ),
        "Gradient boosting": lambda: HistGradientBoostingClassifier(
            max_depth=3,
            learning_rate=0.05,
            max_iter=150,
            min_samples_leaf=20,
            l2_regularization=1.0,
            random_state=SEED,
        ),
    }


def bootstrap_auc(y: np.ndarray, *scores: np.ndarray, n: int = N_BOOTSTRAP):
    """Paired bootstrap of ROC-AUC: one array of resampled AUCs per score vector."""
    from sklearn.metrics import roc_auc_score

    rng = np.random.default_rng(SEED)
    out = [[] for _ in scores]
    idx_all = np.arange(len(y))
    while len(out[0]) < n:
        idx = rng.choice(idx_all, size=len(y), replace=True)
        if y[idx].min() == y[idx].max():
            continue  # a resample needs both classes
        for k, s in enumerate(scores):
            out[k].append(roc_auc_score(y[idx], s[idx]))
    return [np.array(a) for a in out]


def top_fraction_precision(y: np.ndarray, scores: np.ndarray, fraction: float = 0.2) -> float:
    """Precision among the highest-scored ``fraction`` of tracks (a lift metric)."""
    k = max(1, int(round(len(y) * fraction)))
    order = np.argsort(-scores, kind="stable")[:k]
    return float(y[order].mean())


def fit_and_evaluate(
    train, test, features: list[str], name: str, feature_set: str, n_bootstrap: int = N_BOOTSTRAP
):
    """Pick the algorithm by 5-fold CV AUC on train, refit, evaluate once on test."""
    from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
    from sklearn.model_selection import StratifiedKFold, cross_val_score

    x_train, y_train = train[features].to_numpy(float), train["lasts_30_days"].to_numpy(int)
    x_test, y_test = test[features].to_numpy(float), test["lasts_30_days"].to_numpy(int)
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=SEED)
    best = None
    for algo, make in _candidates().items():
        cv_auc = cross_val_score(make(), x_train, y_train, cv=cv, scoring="roc_auc").mean()
        if best is None or cv_auc > best[1]:
            best = (algo, cv_auc, make)
    algo, cv_auc, make = best
    model = make().fit(x_train, y_train)
    scores = model.predict_proba(x_test)[:, 1]
    [boot] = bootstrap_auc(y_test, scores, n=n_bootstrap)
    result = ModelResult(
        name=name,
        feature_set=feature_set,
        algorithm=algo,
        cv_auc=float(cv_auc),
        test_auc=float(roc_auc_score(y_test, scores)),
        test_auc_ci=(float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))),
        average_precision=float(average_precision_score(y_test, scores)),
        brier=float(brier_score_loss(y_test, scores)),
        top20_precision=top_fraction_precision(y_test, scores),
        test_scores=scores,
    )
    return result, model


# --------------------------------------------------------------------------- survival


@dataclass
class KMCurve:
    label: str
    n: int
    n_events: int
    times: np.ndarray
    survival: np.ndarray
    median: float


def kaplan_meier(time, event, label: str) -> KMCurve:
    from statsmodels.duration.survfunc import SurvfuncRight

    sf = SurvfuncRight(np.asarray(time, float), np.asarray(event, int))
    median = sf.quantile(0.5)
    return KMCurve(
        label=label,
        n=len(time),
        n_events=int(np.sum(event)),
        times=np.concatenate([[0.0], sf.surv_times]),
        survival=np.concatenate([[1.0], sf.surv_prob]),
        median=float(median) if np.isfinite(median) else float("nan"),
    )


def survival_at(curve: KMCurve, t: float) -> float:
    """Kaplan-Meier estimate of P(chart life > t)."""
    idx = np.searchsorted(curve.times, t, side="right") - 1
    return float(curve.survival[max(idx, 0)])


def logrank(time, event, groups) -> tuple[float, float]:
    from statsmodels.duration.survfunc import survdiff

    stat, p = survdiff(np.asarray(time, float), np.asarray(event, int), np.asarray(groups))
    return float(stat), float(p)


COX_COVARIATES = {
    # column builder, label: hazard ratio per unit given in the label
    "debut_position_10": (
        "Debut position (per 10 places lower)",
        lambda d: d["debut_position"] / 10,
    ),
    "debut_popularity_10": (
        "Popularity at debut (per 10 points)",
        lambda d: d["debut_popularity"] / 10,
    ),
    "is_new_release": ("New release (<=30 days old)", lambda d: d["is_new_release"]),
    "is_collaboration": ("Collaboration", lambda d: d["is_collaboration"]),
    "debut_is_explicit": ("Explicit", lambda d: d["debut_is_explicit"]),
    "is_single": ("Released as a single", lambda d: d["is_single"]),
    "duration_minutes": ("Duration (per minute)", lambda d: d["duration_minutes"]),
    "debut_in_holiday_season": (
        "Debuted in holiday season",
        lambda d: d["debut_in_holiday_season"],
    ),
    "log2_prior_days": (
        "Artist's prior chart days (per doubling)",
        lambda d: np.log2(1 + d["artist_prior_chart_days"]),
    ),
}


@dataclass
class CoxTerm:
    label: str
    hazard_ratio: float
    ci_low: float
    ci_high: float
    p_value: float
    ph_p_value: float  # proportional-hazards check (Grambsch-Therneau style)


def cox_model(df) -> tuple[list[CoxTerm], float]:
    """Cox proportional-hazards model on launch-day covariates. Returns terms and C-index."""
    from statsmodels.duration.hazard_regression import PHReg

    x = np.column_stack([build(df) for _, build in COX_COVARIATES.values()]).astype(float)
    time = df["chart_life_days"].to_numpy(float)
    event = df["chart_life_ended"].to_numpy(int)
    res = PHReg(time, x, status=event, ties="efron").fit()
    ph_p_values = ph_test(res.schoenfeld_residuals, time)
    terms = []
    for j, (label, _) in enumerate(COX_COVARIATES.values()):
        ph_p = ph_p_values[j]
        beta, se = res.params[j], res.bse[j]
        terms.append(
            CoxTerm(
                label,
                float(np.exp(beta)),
                float(np.exp(beta - 1.96 * se)),
                float(np.exp(beta + 1.96 * se)),
                float(res.pvalues[j]),
                float(ph_p),
            )
        )
    return terms, concordance_index(time, event, x @ res.params)


def ph_test(schoenfeld: np.ndarray, time: np.ndarray) -> list[float]:
    """Proportional-hazards check per covariate, Grambsch-Therneau style.

    Under proportional hazards, Schoenfeld residuals have mean zero at every event
    time, so they are uncorrelated with any function of time. The test is a Pearson
    correlation of the raw residuals with rank-transformed event times. A rank
    (Spearman) correlation of the residuals themselves would be wrong: their spread
    shifts as the risk set changes, which biases their ranks even when the model holds.
    tests/test_modeling.py checks the calibration on simulated data.
    """
    from scipy import stats

    out = []
    for j in range(schoenfeld.shape[1]):
        ok = ~np.isnan(schoenfeld[:, j])
        out.append(float(stats.pearsonr(schoenfeld[ok, j], stats.rankdata(time[ok])).pvalue))
    return out


def concordance_index(time, event, risk) -> float:
    """Harrell's C: share of comparable pairs where the higher-risk track exits first."""
    time, event, risk = map(np.asarray, (time, event, risk))
    concordant = ties = comparable = 0.0
    for i in np.flatnonzero(event):
        later = time > time[i]
        comparable += later.sum()
        concordant += (risk[i] > risk[later]).sum()
        ties += (risk[i] == risk[later]).sum()
    return float((concordant + 0.5 * ties) / comparable)


def fmt_p_cell(p: float) -> str:
    return "< 0.001" if p < 0.001 else f"{p:.3f}"


# --------------------------------------------------------------------------- charts


def _step_curves(
    curves: list[KMCurve],
    colors: list[str],
    title: str,
    subtitle: str,
    xlabel: str,
    path: Path,
    x_max: float = 180,
) -> None:
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(9, 4.8))
    fig.subplots_adjust(left=0.08, right=0.97, top=0.78, bottom=0.12)
    handles = []
    for curve, color in zip(curves, colors, strict=True):
        ax.step(curve.times, curve.survival * 100, where="post", color=color, linewidth=2)
        median = "not reached" if np.isnan(curve.median) else f"{curve.median:.0f} days"
        handles.append(
            plt.Line2D(
                [],
                [],
                color=color,
                linewidth=2,
                label=f"{curve.label}  (n={curve.n}, median {median})",
            )
        )
    ax.set_xlim(0, x_max)
    ax.set_ylim(0, 102)
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0f}%")
    ax.yaxis.grid(True, color=viz.GRID, linewidth=0.8)
    ax.set_xlabel(xlabel, color=viz.TEXT_SECONDARY, fontsize=9)
    ax.set_ylabel("Still charting", color=viz.TEXT_SECONDARY, fontsize=9)
    viz._style(ax, title, subtitle)
    ax.legend(handles=handles, loc="upper right", frameon=False, fontsize=9, labelcolor=viz.TEXT)
    viz._save(fig, path)


def chart_forest(terms: list[CoxTerm], path: Path) -> None:
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(9, 5.2))
    fig.subplots_adjust(left=0.36, right=0.83, top=0.8, bottom=0.11)
    order = sorted(terms, key=lambda t: t.hazard_ratio)
    for i, t in enumerate(order):
        significant = t.p_value < 0.05
        color = viz.BLUE if significant else viz.MUTED
        ax.plot([t.ci_low, t.ci_high], [i, i], color=color, linewidth=2, solid_capstyle="round")
        ax.plot(
            [t.hazard_ratio],
            [i],
            "o",
            color=color,
            markersize=7,
            markeredgecolor=viz.SURFACE,
            markeredgewidth=1.5,
        )
        p_text = "p < 0.001" if t.p_value < 0.001 else f"p = {t.p_value:.3f}"
        ax.text(
            1.02,
            i,
            f"{t.hazard_ratio:.2f}  ({p_text})",
            transform=ax.get_yaxis_transform(),
            va="center",
            fontsize=8.5,
            color=viz.TEXT if significant else viz.TEXT_SECONDARY,
        )
    ax.axvline(1, color=viz.TEXT_SECONDARY, linewidth=1)
    ax.set_xscale("log")
    ax.xaxis.set_minor_locator(plt.NullLocator())
    ax.set_xticks([0.5, 0.75, 1, 1.5, 2])
    ax.set_xticklabels(["0.5", "0.75", "1", "1.5", "2"])
    ax.set_xlim(
        min(0.45, min(t.ci_low for t in terms) * 0.9), max(2.2, max(t.ci_high for t in terms) * 1.1)
    )
    ax.set_yticks(range(len(order)), [t.label for t in order], fontsize=9, color=viz.TEXT)
    ax.xaxis.grid(True, color=viz.GRID, linewidth=0.8)
    ax.set_xlabel(
        "Hazard ratio of leaving the chart (log scale). Left of 1 = lasts longer",
        color=viz.TEXT_SECONDARY,
        fontsize=9,
    )
    viz._style(
        ax,
        "What shortens a chart life, all else equal",
        "Cox proportional-hazards model on launch-day characteristics, 95% CIs. "
        "Grey = not significant",
    )
    viz._save(fig, path)


def chart_roc(y: np.ndarray, results: list[ModelResult], path: Path) -> None:
    import matplotlib.pyplot as plt
    from sklearn.metrics import roc_curve

    colors = [viz.MUTED, viz.ORANGE, viz.BLUE]
    fig, ax = plt.subplots(figsize=(7.2, 6))
    fig.subplots_adjust(left=0.12, right=0.96, top=0.82, bottom=0.11)
    ax.plot([0, 1], [0, 1], color=viz.GRID, linewidth=1, linestyle=(0, (4, 3)))
    for r, color in zip(results, colors, strict=True):
        fpr, tpr, _ = roc_curve(y, r.test_scores)
        ax.plot(fpr, tpr, color=color, linewidth=2, label=f"{r.name}: AUC {r.test_auc:.2f}")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1.01)
    ax.set_aspect("equal")
    ax.grid(True, color=viz.GRID, linewidth=0.8)
    ax.spines["left"].set_visible(True)
    ax.spines["left"].set_color(viz.GRID)
    ax.set_xlabel("False positive rate", color=viz.TEXT_SECONDARY, fontsize=9)
    ax.set_ylabel("True positive rate", color=viz.TEXT_SECONDARY, fontsize=9)
    ax.legend(loc="lower right", frameon=False, fontsize=9, labelcolor=viz.TEXT)
    viz._style(
        ax,
        "One week of chart data sharpens the forecast",
        "ROC curves on the held-out 2024 test set: will a track chart 30+ days?",
    )
    viz._save(fig, path)


def chart_importance(rows: list[tuple[str, float, float]], n_repeats: int, path: Path) -> None:
    import matplotlib.pyplot as plt

    rows = rows[:10]
    fig, ax = plt.subplots(figsize=(9, 4.8))
    fig.subplots_adjust(left=0.38, right=0.95, top=0.8, bottom=0.11)
    labels = [FEATURE_LABELS[f] for f, _, _ in rows]
    means = [m for _, m, _ in rows]
    stds = [s for _, _, s in rows]
    colors = [viz.BLUE if f.startswith("w1_") else viz.ORANGE for f, _, _ in rows]
    ax.barh(
        labels,
        means,
        xerr=stds,
        height=0.6,
        color=colors,
        error_kw={"ecolor": viz.TEXT_SECONDARY, "elinewidth": 1, "capsize": 0},
    )
    ax.invert_yaxis()
    ax.axvline(0, color=viz.GRID, linewidth=1)
    ax.xaxis.grid(True, color=viz.GRID, linewidth=0.8)
    ax.tick_params(axis="y", labelcolor=viz.TEXT, labelsize=9)
    ax.spines["bottom"].set_visible(False)
    ax.set_xlabel(
        f"Drop in test AUC when the feature is shuffled (mean ± sd, {n_repeats} repeats)",
        color=viz.TEXT_SECONDARY,
        fontsize=9,
    )
    ax.legend(
        handles=[
            plt.Rectangle((0, 0), 1, 1, color=viz.BLUE, label="Week-one feature"),
            plt.Rectangle((0, 0), 1, 1, color=viz.ORANGE, label="Launch-day feature"),
        ],
        loc="lower right",
        frameon=False,
        fontsize=8.5,
        labelcolor=viz.TEXT,
    )
    viz._style(
        ax,
        "Momentum features carry the week-one model",
        "Permutation importance of the 10 most important features (held-out test set)",
    )
    viz._save(fig, path)


# --------------------------------------------------------------------------- report


def generate(
    con: duckdb.DuckDBPyConnection,
    report: Path,
    n_bootstrap: int = N_BOOTSTRAP,
    n_repeats: int = 50,
) -> None:
    from sklearn.inspection import permutation_importance

    fig_dir = report.parent / "figures"
    df = load_features(con)
    labeled = df[df["has_label"] == 1].copy()
    labeled["lasts_30_days"] = labeled["lasts_30_days"].astype(int)
    train = labeled[labeled["debut_date"] < TRAIN_CUTOFF]
    test = labeled[labeled["debut_date"] >= TRAIN_CUTOFF]
    y_test = test["lasts_30_days"].to_numpy(int)

    # ---- prediction
    baseline, _ = fit_and_evaluate(
        train, test, ["debut_position"], "Debut position only", "1 feature", n_bootstrap
    )
    launch, _ = fit_and_evaluate(
        train,
        test,
        LAUNCH_FEATURES,
        "Launch-day model",
        f"{len(LAUNCH_FEATURES)} features",
        n_bootstrap,
    )
    week1, week1_model = fit_and_evaluate(
        train,
        test,
        WEEK_ONE_FEATURES,
        "Week-one model",
        f"{len(WEEK_ONE_FEATURES)} features",
        n_bootstrap,
    )
    results = [baseline, launch, week1]
    b_launch, b_week1 = bootstrap_auc(y_test, launch.test_scores, week1.test_scores, n=n_bootstrap)
    gain = b_week1 - b_launch
    gain_ci = (float(np.percentile(gain, 2.5)), float(np.percentile(gain, 97.5)))
    gain_p = float(min(1.0, 2 * min((gain <= 0).mean(), (gain >= 0).mean())))

    pi = permutation_importance(
        week1_model,
        test[WEEK_ONE_FEATURES].to_numpy(float),
        y_test,
        scoring="roc_auc",
        n_repeats=n_repeats,
        random_state=SEED,
    )
    importance = sorted(
        zip(WEEK_ONE_FEATURES, pi.importances_mean, pi.importances_std, strict=True),
        key=lambda r: -r[1],
    )

    # Final model on all labelled tracks, then score recent debuts (no label yet).
    final = _candidates()[week1.algorithm]().fit(
        labeled[WEEK_ONE_FEATURES].to_numpy(float), labeled["lasts_30_days"].to_numpy(int)
    )
    recent = df[(df["has_label"] == 0) & (df["has_full_week_one"] == 1)].copy()
    recent["p_lasts_30"] = final.predict_proba(recent[WEEK_ONE_FEATURES].to_numpy(float))[:, 1]
    watchlist = recent.sort_values(["p_lasts_30", "debut_date"], ascending=[False, True]).head(10)

    # ---- survival
    surv = df
    t, e = surv["chart_life_days"].to_numpy(float), surv["chart_life_ended"].to_numpy(int)
    overall = kaplan_meier(t, e, "All tracks")
    bucket = np.select(
        [surv["debut_position"] <= 10, surv["debut_position"] <= 25],
        ["Debuted #1-10", "Debuted #11-25"],
        "Debuted #26-50",
    )
    by_debut = [
        kaplan_meier(t[bucket == b], e[bucket == b], b)
        for b in ("Debuted #1-10", "Debuted #11-25", "Debuted #26-50")
    ]
    debut_lr = logrank(t, e, bucket)

    lm = surv[surv["w1_on_chart_day7"] == 1]
    lm_t = (lm["chart_life_days"] - lm["w1_chart_days"]).to_numpy(float)
    lm_e = lm["chart_life_ended"].to_numpy(int)
    climbed = lm["w1_climbed"].to_numpy(int)
    by_momentum = [
        kaplan_meier(lm_t[climbed == 1], lm_e[climbed == 1], "Climbed in week one"),
        kaplan_meier(lm_t[climbed == 0], lm_e[climbed == 0], "Did not climb"),
    ]
    momentum_lr = logrank(lm_t, lm_e, climbed)
    cox_terms, c_index = cox_model(surv)

    # ---- charts
    _step_curves(
        by_debut,
        [viz.BLUE, viz.ORANGE, AQUA],
        "Top-10 debuts survive longer, but most tracks fall away fast",
        f"Kaplan-Meier estimate of chart survival by debut position ({len(surv)} "
        "tracks; still-charting tracks are censored, not dropped)",
        "Days on chart",
        fig_dir / "06_km_debut_position.png",
    )
    _step_curves(
        by_momentum,
        [viz.BLUE, viz.ORANGE],
        "Week-one momentum separates long runs from short ones",
        f"Landmark analysis: {len(lm)} tracks still charting on day 7, "
        "remaining chart life after week one",
        "Days on chart after week one",
        fig_dir / "07_landmark_week_one.png",
    )
    chart_forest(cox_terms, fig_dir / "08_cox_hazard_ratios.png")
    chart_roc(y_test, results, fig_dir / "09_roc_curves.png")
    chart_importance(importance, n_repeats, fig_dir / "10_feature_importance.png")

    # ---- markdown
    pct = viz.pct

    def p(x: float) -> str:
        return viz.fmt_p(x)

    sig_cox = [c for c in cox_terms if c.p_value < 0.05]
    ph_bad = [c for c in cox_terms if c.ph_p_value < 0.05]
    top_imp = importance[0]
    w1_share = sum(m for f, m, _ in importance if f.startswith("w1_") and m > 0) / sum(
        m for _, m, _ in importance if m > 0
    )

    def surv_row(c: KMCurve) -> str:
        med = "not reached" if np.isnan(c.median) else f"{c.median:.0f}"
        return (
            f"| {c.label} | {c.n} | {c.n_events} | {med} | "
            f"{pct(survival_at(c, 30))} | {pct(survival_at(c, 90))} |"
        )

    md = [
        "# Model Report: Predicting Chart Longevity",
        "",
        "> Generated by `spotify-pipeline model`. All numbers, tables and figures come from "
        "the warehouse; rerun the command to refresh them. Source: "
        "[`modeling.py`](../src/spotify_pipeline/modeling.py), features: "
        "[`track_features.sql`](../sql/ml/track_features.sql).",
        "",
        "## Summary",
        "",
        f"- **A week of chart data is worth more than everything known at launch.** On "
        f"tracks that debuted in 2024 (held out from training), the week-one model reaches "
        f"**ROC-AUC {week1.test_auc:.2f}** (95% CI {week1.test_auc_ci[0]:.2f}–"
        f"{week1.test_auc_ci[1]:.2f}), against {launch.test_auc:.2f} for the launch-day model "
        f"and {baseline.test_auc:.2f} for debut position alone. The gain is "
        f"**+{week1.test_auc - launch.test_auc:.2f} AUC** (95% CI {gain_ci[0]:+.2f} to "
        f"{gain_ci[1]:+.2f}, paired bootstrap).",
        f"- **The model is useful in practice.** Of the 20% of test tracks it ranks highest, "
        f"{pct(week1.top20_precision)} went on to chart 30+ days, against a base rate of "
        f"{pct(y_test.mean())} (**{week1.top20_precision / y_test.mean():.1f}x lift**).",
        f"- **Survival analysis agrees.** Half of all tracks leave the chart within "
        f"**{overall.median:.0f} chart days**. Among tracks still charting on day 7, those "
        f"that climbed in week one have a median remaining life of "
        f"**{by_momentum[0].median:.0f} days**, against {by_momentum[1].median:.0f} for those "
        f"that didn't (log-rank {p(momentum_lr[1])}).",
        f"- **At launch, {len(sig_cox)} of {len(cox_terms)} characteristics significantly "
        "change survival** in a Cox model: "
        + "; ".join(f"{c.label.lower()} (HR {c.hazard_ratio:.2f})" for c in sig_cox)
        + f". The model ranks tracks only moderately well (C-index {c_index:.2f}), which "
        "confirms that launch-day information alone is limited.",
        "",
        "---",
        "",
        "## 1. Problem framing",
        "",
        "| | |",
        "|---|---|",
        "| **Question** | Will a newly charting track spend **30 or more days** on the Global "
        "Top 50 within 180 days of its debut? |",
        "| **Why 30 days** | It separates lasting hits from release-week spikes: "
        f"{pct(labeled['lasts_30_days'].mean())} of labelled tracks reach it. |",
        "| **Unit** | One track with a known debut (tracks already charting on the first day "
        "are excluded). |",
        "| **Decision supported** | Which recent releases deserve continued promotion or "
        "playlist support, decided one week after debut. |",
        "",
        "## 2. Leakage controls and validation design",
        "",
        "- **Point-in-time features.** Launch-day features use only the debut snapshot, release "
        "metadata and the lead artist's chart history *before* the debut date. Week-one "
        "features use only the 7 days after debut. Tests in `tests/test_ml_features.py` "
        "check both rules.",
        "- **Labels need a full window.** Tracks debuting in the last 180 days of data have "
        "no label, because their outcome isn't known yet. They are scored on a watchlist "
        "(section 5) instead of being dropped silently or mislabelled.",
        f"- **Time-based split.** Train on debuts before {TRAIN_CUTOFF:%d %b %Y} "
        f"(n = {len(train)}), test on later debuts (n = {len(test)}). A random split would "
        "let the model learn from tracks released after the ones it predicts.",
        "- **Model selection** uses 5-fold cross-validation inside the training set only. The "
        "test set is scored exactly once.",
        f"- **Uncertainty.** Confidence intervals come from {n_bootstrap:,} paired bootstrap "
        "resamples of the test set.",
        "",
        "## 3. Results",
        "",
        "![ROC curves](figures/09_roc_curves.png)",
        "",
        "| Model | Features | Chosen algorithm | CV AUC (train) | Test AUC [95% CI] | "
        "Avg precision | Brier | Precision @ top 20% |",
        "|---|---|---|---:|---:|---:|---:|---:|",
        *[
            f"| {r.name} | {r.feature_set} | {r.algorithm} | {r.cv_auc:.3f} | "
            f"{r.test_auc:.3f} [{r.test_auc_ci[0]:.2f}–{r.test_auc_ci[1]:.2f}] | "
            f"{r.average_precision:.3f} | {r.brier:.3f} | {pct(r.top20_precision)} |"
            for r in results
        ],
        "",
        f"Base rate in the test set: {pct(y_test.mean())}. An uninformative model scores "
        f"AUC 0.50 and average precision {y_test.mean():.3f}.",
        "",
        f"**Does momentum really add value?** In a paired bootstrap, the week-one model beats "
        f"the launch-day model by {week1.test_auc - launch.test_auc:+.3f} AUC (95% CI "
        f"{gain_ci[0]:+.3f} to {gain_ci[1]:+.3f}, bootstrap {p(gain_p)}).",
        "",
        "### What drives the prediction",
        "",
        "![Feature importance](figures/10_feature_importance.png)",
        "",
        f"Shuffling **{FEATURE_LABELS[top_imp[0]].lower()}** costs the most AUC "
        f"({top_imp[1]:.3f}). Week-one features account for {pct(w1_share)} of the total "
        "importance. Permutation importance on the held-out set is model-agnostic, and "
        "unlike impurity-based importance it isn't biased towards high-cardinality features.",
        "",
        "## 4. Survival analysis",
        "",
        "Classification needs a fixed window and drops tracks whose outcome is unknown. "
        "Survival analysis keeps every track: those still charting when the data ends are "
        "**censored**, meaning they count for as long as they were observed.",
        "",
        "- **Time:** total days on chart.",
        "- **Event:** the chart life has ended, meaning the track was absent for at least the "
        "last 14 days of data.",
        f"- **Tracks:** {len(surv)} with a known debut, of which {int(e.sum())} have ended "
        f"their chart life and {len(surv) - int(e.sum())} are censored.",
        "",
        "### Kaplan-Meier by debut position",
        "",
        "![Kaplan-Meier by debut position](figures/06_km_debut_position.png)",
        "",
        "| Group | Tracks | Exits | Median chart days | Still charting at 30 days | "
        "Still charting at 90 days |",
        "|---|---:|---:|---:|---:|---:|",
        surv_row(overall),
        *[surv_row(c) for c in by_debut],
        "",
        f"Log-rank test across the three groups: χ² = {debut_lr[0]:.1f}, {p(debut_lr[1])}.",
        "",
        "### Landmark analysis: does week-one momentum matter?",
        "",
        "![Landmark analysis](figures/07_landmark_week_one.png)",
        "",
        "Comparing tracks that climbed in week one with those that didn't, from debut, "
        "would be biased: a track has to *survive* in order to climb (**immortal-time "
        "bias**). The landmark design avoids this. Only tracks still charting on day 7 are "
        "compared, and survival is measured from that point.",
        "",
        "| Group | Tracks | Exits | Median remaining chart days | At 30 days | At 90 days |",
        "|---|---:|---:|---:|---:|---:|",
        *[surv_row(c) for c in by_momentum],
        "",
        f"Log-rank test: χ² = {momentum_lr[0]:.1f}, {p(momentum_lr[1])}.",
        "",
        "### Cox proportional-hazards model (launch-day covariates)",
        "",
        "![Cox hazard ratios](figures/08_cox_hazard_ratios.png)",
        "",
        "A hazard ratio (HR) above 1 means the track tends to leave the chart sooner.",
        "",
        "| Covariate | HR | 95% CI | p | PH check p |",
        "|---|---:|---|---:|---:|",
        *[
            f"| {c.label} | {c.hazard_ratio:.2f} | {c.ci_low:.2f}–{c.ci_high:.2f} | "
            f"{fmt_p_cell(c.p_value)} | {fmt_p_cell(c.ph_p_value)} |"
            for c in cox_terms
        ],
        "",
        f"Concordance (Harrell's C): **{c_index:.2f}**. The *PH check* tests whether each "
        "covariate's effect is constant over time, by correlating its Schoenfeld residuals "
        "with time. "
        + (
            "No covariate violates the proportional-hazards assumption at the 5% level."
            if not ph_bad
            else (
                f"{len(ph_bad)} covariate(s) show a time-varying effect ("
                + ", ".join(c.label.lower() for c in ph_bad)
                + "). Their hazard ratios are averages over the chart life and should be "
                "read as such. A stratified or time-varying Cox model is the natural next "
                "step."
            )
        ),
        "",
        "## 5. Watchlist: recent debuts scored by the final model",
        "",
        "The final week-one model is refit on all labelled tracks and scores the tracks that "
        "debuted too recently to have a label. These are genuine forecasts:",
        "",
        "| Track | Lead artist | Debut | Debut pos. | Day-7 pos. | P(30+ days) | Chart days "
        "so far |",
        "|---|---|---|---:|---:|---:|---:|",
        *[
            f"| {r.track_title} | {r.lead_artist_name} | {r.debut_date:%Y-%m-%d} | "
            f"{r.debut_position} | {'off' if r.w1_day7_position == 51 else r.w1_day7_position} "
            f"| {pct(r.p_lasts_30)} | {r.chart_life_days} |"
            for r in watchlist.itertuples()
        ],
        "",
        "## 6. Model card",
        "",
        "| | |",
        "|---|---|",
        f"| **Model** | {week1.algorithm}, {len(WEEK_ONE_FEATURES)} features |",
        f"| **Training data** | {len(labeled)} labelled tracks "
        f"(debuts {labeled['debut_date'].min()} to {labeled['debut_date'].max()}) |",
        "| **Intended use** | Ranking newly charting tracks by their likelihood of lasting, "
        "one week after debut |",
        "| **Not intended for** | Predicting stream counts, regional charts, or tracks "
        "outside the Global Top 50 |",
        "| **Known limitations** | Small sample; a single 18-month window; artist history "
        "only visible inside the dataset window, so early debuts have less of it; "
        "associations, not causal effects |",
        "| **Monitoring** | Recompute the test AUC as new labels mature, and retrain if it "
        "drops below the launch-day model |",
        "",
        "## Reproduce",
        "",
        "```bash",
        "make install   # includes the ml extra",
        "make all       # build the warehouse, including ml.track_features",
        "make model     # regenerates this report and figures 06-10",
        "```",
    ]
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("\n".join(md) + "\n", encoding="utf-8")
    log.info("Model report written to %s", report)
