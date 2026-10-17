"""Deterministic data science for the crew.

Agents decide *what* to run and explain the results; every number comes from
this module. Nothing here calls a model.
"""
import hashlib
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

DATA_DIR = Path(__file__).parent / "data"
# The pinned baseline. Scheduled fetches add newer snapshots under DATA_DIR/snapshots.
SNAPSHOT = DATA_DIR / "pscomppars-2026-10-07.csv"
SNAPSHOT_SHA256 = "981ac4896e25de52fa702939c3ab64508c69e9387422d32c3e40bf992a64b3e8"

# Analysis window for planet size, in Earth radii (log10 space inside the KDE)
WINDOW = (1.0, 4.0)
GRID = np.linspace(np.log10(WINDOW[0]), np.log10(WINDOW[1]), 400)

# Below this many planets in the window the mode test has too little power to mean anything
MIN_SAMPLE = 200


class InsufficientSample(ValueError):
    pass


FILTER_OPS = {
    "eq": lambda s, v: s == v,
    "ne": lambda s, v: s != v,
    "lt": lambda s, v: s < v,
    "le": lambda s, v: s <= v,
    "gt": lambda s, v: s > v,
    "ge": lambda s, v: s >= v,
    "notna": lambda s, v: s.notna(),
}


def load_snapshot(path=SNAPSHOT, expected_sha256=SNAPSHOT_SHA256):
    """Load an archive snapshot, refusing a file that doesn't match its recorded hash.

    `path` may be relative to DATA_DIR (as stored on a Snapshot).
    """
    path = Path(path)
    if not path.is_absolute():
        path = DATA_DIR / path
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if expected_sha256 and digest != expected_sha256:
        raise ValueError(f"Snapshot hash mismatch: {digest}")
    df = pd.read_csv(path)
    df["rade_rel_err"] = df["pl_radeerr1"] / df["pl_rade"]
    return df, digest


def data_card(df):
    """Facts about the data that an analysis plan has to account for."""
    rel = df["rade_rel_err"].dropna()
    return {
        "n_planets": int(len(df)),
        "discovery_methods": df["disc_method"].value_counts().to_dict(),
        "missing_pct": (df[["pl_rade", "pl_bmasse", "pl_orbper", "st_teff", "sy_dist"]]
                        .isna().mean().mul(100).round(1).to_dict()),
        "mass_provenance": df["pl_bmassprov"].value_counts().to_dict(),
        "mass_from_mass_radius_relation_pct": round(
            float((df["pl_bmassprov"] == "M-R relationship").mean() * 100), 1),
        "median_orbital_period_days_by_method": (
            df.groupby("disc_method")["pl_orbper"].median().round(1).dropna().to_dict()),
        "radius_relative_error_quantiles": rel.quantile([0.25, 0.5, 0.75]).round(3).to_dict(),
        "columns": list(df.columns),
    }


class InvalidFilter(ValueError):
    pass


def _filter_value(df, column, op, value):
    """Check and normalize a filter's value; never silently match nothing."""
    if op == "notna":
        return None
    if value is None or (isinstance(value, str) and not value.strip()):
        if pd.api.types.is_numeric_dtype(df[column]):
            example = round(float(df[column].median()), 2)
        else:
            example = repr(df[column].mode().iloc[0])
        raise InvalidFilter(f"Filter '{column} {op}' needs a value (e.g. {column} {op} {example}).")
    if pd.api.types.is_numeric_dtype(df[column]):
        try:
            return float(value)
        except (TypeError, ValueError):
            raise InvalidFilter(f"{column} is numeric, but the value {value!r} is not a number.")
    if op not in ("eq", "ne"):
        raise InvalidFilter(f"{column} is text; use 'eq' or 'ne', not '{op}'.")
    return str(value)


def apply_filters(df, filters):
    """Apply filters given as dicts: {"column", "op", "value"}. Returns (subset, steps).

    Raises InvalidFilter for anything malformed, rather than silently matching no planets.
    """
    steps = []
    for f in filters:
        column, op = f["column"], f["op"]
        if column not in df.columns:
            raise InvalidFilter(f"Unknown column: {column}")
        if op not in FILTER_OPS:
            raise InvalidFilter(f"Unknown filter op: {op}")
        value = _filter_value(df, column, op, f.get("value"))
        before = len(df)
        df = df[FILTER_OPS[op](df[column], value)]
        steps.append({"column": column, "op": op, "value": value,
                      "before": before, "after": len(df)})
    return df, steps


def _kde(x, h, grid=GRID):
    """Gaussian KDE of x (log10 radii) evaluated on grid, bandwidth h (dex)."""
    z = (grid[:, None] - x[None, :]) / h
    return np.exp(-0.5 * z * z).sum(axis=1) / (len(x) * h * np.sqrt(2 * np.pi))


def count_modes(x, h, grid=GRID):
    d = _kde(x, h, grid)
    return int(np.sum((d[1:-1] > d[:-2]) & (d[1:-1] > d[2:])))


def critical_bandwidth(x, k=1, lo=1e-3, hi=1.0, iters=40):
    """Smallest bandwidth at which the KDE has at most k modes in the window."""
    for _ in range(iters):
        mid = (lo + hi) / 2
        if count_modes(x, mid) <= k:
            hi = mid
        else:
            lo = mid
    return hi


def silverman_test(x, k=1, n_boot=500, seed=0):
    """Silverman (1981) test of H0: at most k modes. Small p means more than k modes.

    Uses the variance-corrected smoothed bootstrap from Silverman's paper.
    """
    rng = np.random.default_rng(seed)
    h_crit = critical_bandwidth(x, k)
    mu, sigma = x.mean(), x.std()
    scale = 1 / np.sqrt(1 + h_crit**2 / sigma**2)
    exceed = 0
    for _ in range(n_boot):
        y = rng.choice(x, size=len(x), replace=True) + h_crit * rng.standard_normal(len(x))
        y = mu + (y - mu) * scale
        exceed += count_modes(y, h_crit) > k
    return {"h_crit_dex": round(float(h_crit), 4), "p_value": exceed / n_boot,
            "n_boot": n_boot, "seed": seed, "k": k}


def valley(x, h):
    """Location and depth of the deepest valley between the two highest peaks."""
    d = _kde(x, h)
    peaks = np.where((d[1:-1] > d[:-2]) & (d[1:-1] > d[2:]))[0] + 1
    if len(peaks) < 2:
        return None
    a, b = sorted(peaks[np.argsort(d[peaks])[-2:]])
    v = a + int(np.argmin(d[a:b + 1]))
    return {"radius_earth": round(float(10 ** GRID[v]), 3),
            "depth_ratio": round(float(d[v] / ((d[a] + d[b]) / 2)), 3),
            "peaks_radius_earth": [round(float(10 ** GRID[a]), 3), round(float(10 ** GRID[b]), 3)]}


def bootstrap_valley(x, h, n_boot=500, seed=0):
    """Percentile 95% interval for the valley location; also how often no valley appears."""
    rng = np.random.default_rng(seed)
    locs = []
    for _ in range(n_boot):
        v = valley(rng.choice(x, size=len(x), replace=True), h)
        if v:
            locs.append(v["radius_earth"])
    if not locs:
        return {"ci95_radius_earth": None, "valley_found_pct": 0.0}
    lo, hi = np.percentile(locs, [2.5, 97.5])
    return {"ci95_radius_earth": [round(float(lo), 3), round(float(hi), 3)],
            "valley_found_pct": round(100 * len(locs) / n_boot, 1),
            "n_boot": n_boot, "seed": seed}


def synthetic_null(x, seed=0):
    """Negative control: a unimodal (log-normal) sample with the same n, mean and spread."""
    rng = np.random.default_rng(seed)
    return rng.normal(x.mean(), x.std(), size=len(x))


def specification_curve(df, base_filters, error_cuts=(None, 0.20, 0.15, 0.10, 0.08, 0.05),
                        n_boot=300, seed=0):
    """Rerun the analysis across radius-precision cuts.

    Reported in full on every mission so a conclusion can't rest on one
    hand-picked filter (the garden of forking paths).
    """
    rows = []
    for cut in error_cuts:
        filters = list(base_filters)
        if cut is not None:
            filters.append({"column": "rade_rel_err", "op": "lt", "value": cut})
        subset, _ = apply_filters(df, filters)
        try:
            a = analyze_radius_distribution(subset["pl_rade"].dropna(), n_boot=n_boot, seed=seed)
        except InsufficientSample as exc:
            rows.append({"radius_rel_err_lt": cut, "insufficient_sample": str(exc)})
            continue
        rows.append({
            "radius_rel_err_lt": cut,
            "n": a.n,
            "p_value": a.silverman["p_value"],
            "valley_radius_earth": a.valley["radius_earth"] if a.valley else None,
            "depth_ratio": a.valley["depth_ratio"] if a.valley else None,
            "ci95_radius_earth": a.valley_bootstrap["ci95_radius_earth"],
        })
    return rows


@dataclass
class RadiusAnalysis:
    n: int
    silverman: dict
    valley: dict | None
    valley_bootstrap: dict
    bandwidth_sensitivity: list


def analyze_radius_distribution(radii, bandwidths=(0.03, 0.04, 0.05), n_boot=500, seed=0):
    """Full analysis of planet radii (Earth radii) inside WINDOW."""
    r = np.asarray(radii, dtype=float)
    x = np.log10(r[(r >= WINDOW[0]) & (r <= WINDOW[1])])
    if len(x) < MIN_SAMPLE:
        raise InsufficientSample(
            f"{len(x)} planets between {WINDOW[0]} and {WINDOW[1]} Earth radii; need {MIN_SAMPLE}")
    h = bandwidths[len(bandwidths) // 2]
    return RadiusAnalysis(
        n=int(len(x)),
        silverman=silverman_test(x, k=1, n_boot=n_boot, seed=seed),
        valley=valley(x, h),
        valley_bootstrap=bootstrap_valley(x, h, n_boot=n_boot, seed=seed),
        bandwidth_sensitivity=[{"bandwidth_dex": b, "valley": valley(x, b)} for b in bandwidths],
    )
