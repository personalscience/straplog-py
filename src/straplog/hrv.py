"""HRV algorithms over RR intervals in ms. Format-agnostic: nothing here
knows about StrapLog files, so it works on any RR series.

One copy of what the H10 skills (h10-session, hrv-overnight, hrv-ramp-test,
hrv-resting) each used to carry: the artifact filter, time-domain metrics,
DFA alpha1 and the sliding-window feature table.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

RR_MIN_MS = 300.0           # physiological gate: 200 bpm
RR_MAX_MS = 2000.0          # 30 bpm
PCT_THRESH_DEFAULT = 0.25   # workout; resting readings use a stricter 0.20

DFA_SCALE_MIN = 4           # short-term alpha1 box sizes, in beats
DFA_SCALE_MAX = 16

WINDOW_SEC_DEFAULT = 120.0
STRIDE_SEC_DEFAULT = 60.0
MIN_BEATS_PER_WIN = 60


def artifact_mask(rr_ms, pct_thresh: float = PCT_THRESH_DEFAULT) -> np.ndarray:
    """Boolean keep-mask over the input beats: physiological gate, then an
    iterative (up to 3 passes) 5-beat median filter dropping beats more than
    `pct_thresh` from the local median. In the spirit of Altini's 'Workout'
    correction: salvages high-HR segments without erasing real variability.

    A mask rather than the filtered values, so callers can carry per-beat
    timestamps through the filter and slice by time afterwards."""
    x = np.asarray(rr_ms, dtype=float).copy()
    x[(x < RR_MIN_MS) | (x > RR_MAX_MS)] = np.nan
    for _ in range(3):
        s = pd.Series(x)
        med = s.rolling(5, center=True, min_periods=3).median()
        bad = ((s - med).abs() / med) > pct_thresh
        if not bad.any():
            break
        x[bad.to_numpy()] = np.nan
    return ~np.isnan(x)


def clean_rr(rr_ms, pct_thresh: float = PCT_THRESH_DEFAULT) -> np.ndarray:
    """The beats `artifact_mask` keeps."""
    x = np.asarray(rr_ms, dtype=float)
    return x[artifact_mask(x, pct_thresh)]


def time_domain(rr_ms) -> dict:
    """Time-domain HRV over already-cleaned RR intervals (ms). SDNN, SDSD and
    HR SD are sample statistics (ddof=1), the HRV-literature convention.
    Fewer than 2 beats gives NaN for everything but n."""
    rr = np.asarray(rr_ms, dtype=float)
    n = int(rr.size)
    if n < 2:
        return {"n": n} | dict.fromkeys(
            ("mean_rr_ms", "hr_mean", "hr_sd", "hr_min", "hr_max", "sdnn_ms",
             "rmssd_ms", "ln_rmssd", "pnn50_pct", "sdsd_ms"), float("nan"))
    d = np.diff(rr)
    hr = 60000.0 / rr
    rmssd = float(np.sqrt(np.mean(d ** 2)))
    return {
        "n": n,
        "mean_rr_ms": float(rr.mean()),
        "hr_mean": float(hr.mean()),     # mean of beat HRs, not 60000/mean_rr_ms
        "hr_sd": float(hr.std(ddof=1)),
        "hr_min": float(hr.min()),
        "hr_max": float(hr.max()),
        "sdnn_ms": float(rr.std(ddof=1)),
        "rmssd_ms": rmssd,
        "ln_rmssd": float(np.log(rmssd)) if rmssd > 0 else float("nan"),
        "pnn50_pct": float(100.0 * np.mean(np.abs(d) > 50)),
        "sdsd_ms": float(d.std(ddof=1)) if d.size > 1 else float("nan"),
    }


def dfa_alpha1(rr_ms, scale_min: int = DFA_SCALE_MIN,
               scale_max: int = DFA_SCALE_MAX) -> float:
    """Short-term detrended fluctuation exponent (alpha1) of a cleaned RR
    series; NaN when there are too few beats to fit the scales."""
    rr = np.asarray(rr_ms, dtype=float)
    n_total = len(rr)
    if n_total < scale_max * 4:
        return np.nan

    y = np.cumsum(rr - rr.mean())
    scales = np.arange(scale_min, scale_max + 1)
    F = np.full(len(scales), np.nan)

    for i, n in enumerate(scales):
        nb = n_total // n
        if nb < 4:
            continue
        segs = y[: nb * n].reshape(nb, n)
        x = np.arange(n)
        x_mean = x.mean()
        x_var = ((x - x_mean) ** 2).sum()
        seg_mean = segs.mean(axis=1, keepdims=True)
        cov = ((segs - seg_mean) * (x - x_mean)).sum(axis=1) / x_var
        intercept = seg_mean.squeeze() - cov * x_mean
        trend = np.outer(cov, x) + intercept[:, None]
        F[i] = np.sqrt(((segs - trend) ** 2).mean())

    mask = np.isfinite(F) & (F > 0)
    if mask.sum() < 4:
        return np.nan
    slope, _ = np.polyfit(np.log(scales[mask]), np.log(F[mask]), 1)
    return float(slope)


def rolling_features(rr_df: pd.DataFrame,
                     window_sec: float = WINDOW_SEC_DEFAULT,
                     stride_sec: float = STRIDE_SEC_DEFAULT,
                     pct_thresh: float = PCT_THRESH_DEFAULT,
                     min_beats: int = MIN_BEATS_PER_WIN) -> pd.DataFrame:
    """Sliding windows over rr_df[t_rel, rr_ms], anchored at t_rel=0.
    Artifact correction runs per window, so a burst of bad beats doesn't drag
    a neighbouring window. Columns: t_center, t_min, hr_bpm, alpha1, rmssd,
    n_beats, n_raw. Windows with fewer than `min_beats` beats are skipped."""
    t_end = rr_df["t_rel"].max()
    centers = np.arange(window_sec / 2, t_end - window_sec / 2 + 1, stride_sec)
    t_arr = rr_df["t_rel"].to_numpy()
    rr_arr = rr_df["rr_ms"].to_numpy()

    rows = []
    for c in centers:
        lo, hi = c - window_sec / 2, c + window_sec / 2
        raw = rr_arr[(t_arr >= lo) & (t_arr < hi)]
        if raw.size < min_beats:
            continue
        clean = clean_rr(raw, pct_thresh)
        if clean.size < min_beats:
            continue
        d = np.diff(clean)
        rows.append({
            "t_center": c,
            "t_min": c / 60.0,
            "hr_bpm": 60000.0 / clean.mean(),
            "alpha1": dfa_alpha1(clean),
            "rmssd": float(np.sqrt((d ** 2).mean())) if d.size else np.nan,
            "n_beats": clean.size,
            "n_raw": raw.size,
        })
    return pd.DataFrame(rows, columns=["t_center", "t_min", "hr_bpm", "alpha1",
                                       "rmssd", "n_beats", "n_raw"])
