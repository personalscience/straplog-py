# straplog

Read [StrapLog](https://github.com/personalscience) exports and compute heart-rate variability.

StrapLog is an iOS app that records beat-to-beat RR intervals from a Polar H10 chest strap. It writes each recording as one self-contained SQLite file (`<YYMMDD-HHMM>-<name>.sqlite`) to its iCloud folder, plus an `index.json` catalog. This package reads those files and provides the HRV algorithms used by the StrapLog Claude Code skills.

## Install

```sh
uv add straplog            # or: pip install straplog
uv add 'straplog[plot]'    # + the plotnine house chart style
```

## Use

```python
from straplog import db, hrv

recs = db.list_recordings("251018-0712-REST.sqlite")
rr, events, start_local, name = db.load_recording("251018-0712-REST.sqlite", recs[0]["pk"])

clean = hrv.clean_rr(rr["rr_ms"], pct_thresh=0.20)
hrv.time_domain(clean)        # n, hr_mean, sdnn_ms, rmssd_ms, ln_rmssd, pnn50_pct, ...
hrv.dfa_alpha1(clean)
hrv.rolling_features(rr)      # 2-min windows, 1-min stride: hr_bpm, alpha1, rmssd
```

| Module | Role |
|---|---|
| `straplog.export` | A file as stored: epoch ms UTC, typed events |
| `straplog.catalog` | List a folder of exports via `index.json` |
| `straplog.db` | Load beats and markers as DataFrames in local time |
| `straplog.hrv` | Artifact filter, time-domain metrics, DFA α1, sliding windows. Works on any RR series |
| `straplog.plot` | House chart style (plotnine; `plot` extra) |
| `straplog.cli` | `straplog ls / rr / events / meta` |

## CLI

```sh
straplog ls --activity sleep --since 14d
straplog rr 251018-0712-REST --json
straplog events 251018-0712-REST --markers
```

A bare export name resolves against the StrapLog iCloud folder.

## Conventions

- RR in ms. The H10 sends RR in 1/1024 s; `rr_1024` is canonical in the file and `rr_ms` is derived.
- SDNN, SDSD and HR SD are sample statistics (ddof=1). `hr_mean` is the mean of per-beat HR, not `60000 / mean_rr_ms`.
- The artifact filter applies a 300–2000 ms gate, then an iterative 5-beat median filter. The default threshold is 0.25 (workouts); use 0.20 for resting readings.

## License

MIT
