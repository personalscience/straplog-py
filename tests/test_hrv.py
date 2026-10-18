import math

import numpy as np
import pandas as pd
import pytest

from straplog import hrv


def test_artifact_mask_gates_and_drops_spike():
    rr = np.full(20, 800.0)
    rr[3] = 250.0      # below the physiological gate
    rr[10] = 1200.0    # 50 % off the local median
    keep = hrv.artifact_mask(rr)
    assert not keep[3] and not keep[10]
    assert keep.sum() == 18


def test_stricter_threshold_drops_more():
    rr = np.full(20, 800.0)
    rr[10] = 980.0     # 22.5 % off: kept at 0.25, dropped at 0.20
    assert hrv.artifact_mask(rr, 0.25)[10]
    assert not hrv.artifact_mask(rr, 0.20)[10]


def test_clean_rr_is_masked_values():
    rr = np.array([800, 810, 2500, 790, 800, 805], dtype=float)
    np.testing.assert_array_equal(hrv.clean_rr(rr), rr[hrv.artifact_mask(rr)])


def test_time_domain_known_values():
    rr = [1000.0, 1100.0, 1000.0, 1100.0]
    m = hrv.time_domain(rr)
    assert m["n"] == 4
    assert m["rmssd_ms"] == pytest.approx(100.0)
    assert m["ln_rmssd"] == pytest.approx(math.log(100.0))
    assert m["sdnn_ms"] == pytest.approx(np.std(rr, ddof=1))
    assert m["pnn50_pct"] == pytest.approx(100.0)
    assert m["mean_rr_ms"] == pytest.approx(1050.0)
    assert m["hr_mean"] == pytest.approx((60.0 + 60000 / 1100) / 2)
    assert m["hr_min"] == pytest.approx(60000 / 1100)
    assert m["hr_max"] == pytest.approx(60.0)


def test_time_domain_too_short_is_nan():
    m = hrv.time_domain([800.0])
    assert m["n"] == 1 and math.isnan(m["rmssd_ms"]) and math.isnan(m["sdnn_ms"])


def test_dfa_alpha1_white_noise_and_brownian():
    rng = np.random.default_rng(0)
    white = 800 + rng.normal(0, 30, 4000)
    brown = 800 + np.cumsum(rng.normal(0, 3, 4000))
    assert hrv.dfa_alpha1(white) == pytest.approx(0.5, abs=0.1)
    assert hrv.dfa_alpha1(brown) == pytest.approx(1.5, abs=0.15)


def test_dfa_alpha1_too_few_beats():
    assert math.isnan(hrv.dfa_alpha1(np.full(40, 800.0)))


def test_rolling_features_windows():
    rng = np.random.default_rng(1)
    rr = 750 + rng.normal(0, 20, 900)          # ~11 min at 80 bpm
    df = pd.DataFrame({"rr_ms": rr, "t_rel": np.cumsum(rr) / 1000.0})
    feat = hrv.rolling_features(df)
    assert list(feat.columns) == ["t_center", "t_min", "hr_bpm", "alpha1",
                                  "rmssd", "n_beats", "n_raw"]
    assert len(feat) >= 9
    assert feat["hr_bpm"].between(75, 85).all()
    assert (feat["n_beats"] >= hrv.MIN_BEATS_PER_WIN).all()


def test_rolling_features_too_short_is_empty_with_columns():
    df = pd.DataFrame({"rr_ms": [800.0] * 10, "t_rel": np.arange(10) * 0.8})
    feat = hrv.rolling_features(df)
    assert feat.empty and "alpha1" in feat.columns
