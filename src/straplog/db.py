"""Read a StrapLog export in the HRV Logger loaders' conventions.

StrapLog (the Polar H10 logger in ~/dev/iOS Projects/StrapLog) writes a
single-file SQLite snapshot: `recording`, `notification`, `beat`, `event`,
`motion`, `meta` (its docs/SCHEMA.md is the source of truth). Its times are
Unix epoch ms UTC plus a per-recording `tz_offset_s`.

The HRV Logger loaders in these skills work in Apple-epoch seconds of LOCAL
wall-clock (Core Data stored local time as if it were UTC). This module maps
StrapLog onto that convention, so every analysis downstream is unchanged:

    t = (t_end_ms_est / 1000 + tz_offset_s) - 978307200

Skills import it as `import straplog.db as straplog_db`; this replaced the
copies `_hrv_shared/sync.sh` used to push into each skill's scripts/.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

from ._sqlite import columns, connect as _connect, require_snapshot as _require_snapshot

APPLE_EPOCH_OFFSET = 978307200.0   # 2001-01-01 -> unix
# Consecutive H10 notifications arrive ~1 s apart; a longer silence is a
# Bluetooth dropout, and that time counts against coverage.
NOTIFICATION_GAP_SEC = 3.0


def is_straplog(db_path: Path) -> bool:
    """True for a StrapLog file (it has a `beat` table); False for HRV Logger."""
    con = _connect(db_path)
    try:
        return con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='beat'"
        ).fetchone() is not None
    finally:
        con.close()


def _local_apple(ms, tz_offset_s):
    return ms / 1000.0 + tz_offset_s - APPLE_EPOCH_OFFSET


def _recording(con: sqlite3.Connection, rid: int) -> dict:
    row = con.execute(
        "SELECT name, started_at_ms, ended_at_ms, tz_offset_s FROM recording "
        "WHERE id=?", (rid,)).fetchone()
    if row is None:
        raise SystemExit(f"Recording {rid} not found.")
    return dict(zip(("name", "started_at_ms", "ended_at_ms", "tz_offset_s"), row))


def _coverage(received_ms: np.ndarray, start_ms: int, end_ms: int) -> float | None:
    """Fraction of the recording's wall-clock span covered by notifications:
    the sum of inter-notification intervals no longer than
    NOTIFICATION_GAP_SEC, over end - start. Time before the first and after
    the last notification is uncovered."""
    span = end_ms - start_ms
    if span <= 0 or received_ms.size < 2:
        return None
    d = np.diff(received_ms)
    return float(d[d <= NOTIFICATION_GAP_SEC * 1000].sum() / span)


def coverage(db_path: Path, rid: int) -> float | None:
    _require_snapshot(db_path)
    con = _connect(db_path)
    try:
        rec = _recording(con, rid)
        rx = np.array([r[0] for r in con.execute(
            "SELECT received_at_ms FROM notification WHERE recording_id=? "
            "ORDER BY id", (rid,))], dtype=float)
    finally:
        con.close()
    end = rec["ended_at_ms"] or (int(rx[-1]) if rx.size else rec["started_at_ms"])
    return _coverage(rx, rec["started_at_ms"], end)


def list_recordings(db_path: Path) -> list[dict]:
    """One dict per recording with the keys the HRV Logger listers share:
    pk, name, start_local (ISO, local wall-clock), n_beats, duration_min,
    avg_hr, coverage. Each skill adds its own extra keys."""
    _require_snapshot(db_path)
    con = _connect(db_path)
    try:
        recs = con.execute(
            "SELECT id, name, started_at_ms, ended_at_ms, tz_offset_s "
            "FROM recording ORDER BY started_at_ms").fetchall()
        beats = {r[0]: r[1:] for r in con.execute(
            "SELECT recording_id, COUNT(*), AVG(rr_ms) FROM beat "
            "GROUP BY recording_id")}
        rx: dict[int, list[int]] = {}
        for rid, ms in con.execute(
                "SELECT recording_id, received_at_ms FROM notification ORDER BY id"):
            rx.setdefault(rid, []).append(ms)
    finally:
        con.close()

    out = []
    for rid, name, start_ms, end_ms, tz in recs:
        n, mean_rr = beats.get(rid, (0, None))
        r = np.array(rx.get(rid, []), dtype=float)
        end = end_ms or (int(r[-1]) if r.size else start_ms)
        cov = _coverage(r, start_ms, end)
        out.append({
            "pk": rid,
            "name": name or "",
            "start_local": pd.to_datetime(start_ms + tz * 1000, unit="ms").isoformat(),
            "n_beats": int(n),
            "duration_min": round((end - start_ms) / 60000.0, 1),
            "avg_hr": round(60000.0 / mean_rr, 1) if mean_rr else None,
            "coverage": None if cov is None else round(cov, 3),
        })
    return out


def load_rr(db_path: Path, rid: int) -> pd.DataFrame:
    """Beats as DataFrame[t, rr_ms], t in Apple-epoch local seconds.

    Ordered by beat id (true beat order). The H10 sends no beat timestamps, so
    `t_end_ms_est` is anchored on phone receipt, and BLE delivery jitter
    leaves ~2 % of beats up to ~0.9 s earlier than the beat before. `t` is
    clamped non-decreasing so window and gap logic never sees time run
    backwards; rr_ms itself is exact.
    """
    _require_snapshot(db_path)
    con = _connect(db_path)
    try:
        tz = _recording(con, rid)["tz_offset_s"]
        rr = pd.read_sql_query(
            "SELECT t_end_ms_est AS t, rr_ms FROM beat WHERE recording_id=? "
            "ORDER BY id", con, params=(rid,))
    finally:
        con.close()
    rr["t"] = _local_apple(rr["t"].astype(float).cummax(), tz)
    return rr


def load_events(db_path: Path, rid: int) -> pd.DataFrame:
    """User markers as DataFrame[t, note]: StrapLog's `marker` events, which
    are what HRV Logger's ZEVENT rows were. Lifecycle events (start, connect,
    snapshot, ...) are not user notes and are left out.

    From schema v3 a marker has a preset `label` (`a`, `awake`, ...), a free
    `note`, or both; `note` here is the label, then ` · note` if both, which
    matches v2 files where the label was the note."""
    _require_snapshot(db_path)
    con = _connect(db_path)
    try:
        tz = _recording(con, rid)["tz_offset_s"]
        cols = columns(con, "event")
        text = ("COALESCE(label || COALESCE(' · ' || note, ''), note, '')"
                if "label" in cols else "COALESCE(note, '')")
        ev = pd.read_sql_query(
            f"SELECT at_ms AS t, {text} AS note FROM event "
            "WHERE recording_id=? AND kind='marker' ORDER BY at_ms",
            con, params=(rid,))
    finally:
        con.close()
    ev["t"] = _local_apple(ev["t"].astype(float), tz)
    return ev


def load_recording(db_path: Path, rid: int):
    """(rr[t, rr_ms, t_rel], ev[t, note, t_rel], start_local, name), the shape
    of h10-session's HRV Logger `load_recording`. t_rel is seconds from the
    first beat; start_local is a naive local-wall-clock Timestamp."""
    rr = load_rr(db_path, rid)
    ev = load_events(db_path, rid)
    con = _connect(db_path)
    try:
        name = _recording(con, rid)["name"] or ""
    finally:
        con.close()
    t0 = rr["t"].iloc[0] if len(rr) else 0.0
    rr["t_rel"] = rr["t"] - t0
    ev["t_rel"] = ev["t"] - t0
    start_local = pd.to_datetime(t0 + APPLE_EPOCH_OFFSET, unit="s")
    return rr, ev, start_local, name
