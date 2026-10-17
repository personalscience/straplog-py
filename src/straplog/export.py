"""One StrapLog export as stored: epoch ms UTC, typed markers.

Snapshots hold one recording each (the app's `Snapshot`). Exports from
before that held every recording on the phone; the file is still named after
one of them (`file_name`), and that one is the default everywhere. Every
reader also takes a recording id.
Schema v2 files have no `activity`, `context` or `event.label`; they read
as activity `other` with labels left in `note`, as the app's v3 migration does.
"""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ._sqlite import columns, connect, require_snapshot

# Must match Coverage.defaultGapThresholdMs in StrapLogCore.
GAP_THRESHOLD_MS = 3000
# meta values the app writes as JSON (ExportMeta).
JSON_META = ("preset", "event_kinds")


def meta(path: Path) -> dict:
    """The `meta` table, with ExportMeta's JSON values decoded."""
    with _open(path) as con:
        rows = dict(con.execute("SELECT key, value FROM meta"))
    for k in JSON_META:
        if k in rows:
            rows[k] = json.loads(rows[k])
    return rows


def recordings(path: Path, named_only: bool = False) -> list[dict]:
    """One `index.json` entry (ExportIndexEntry) per recording, newest first,
    computed from the file itself. `named_only` keeps just the recording the
    file is named after, when there is one."""
    path = Path(path)
    with _open(path) as con:
        recs = _recordings(con)
        if named_only:
            recs = [r for r in recs if r[0] == _named(recs, path)] or recs
        out = []
        for rid, name, act, start, end, tz in recs:
            (n,) = con.execute("SELECT COUNT(*) FROM beat WHERE recording_id=?", (rid,)).fetchone()
            entry = {
                "file": path.name, "id": rid, "name": name, "activity": act,
                "started_at_ms": start, "ended_at_ms": end, "tz_offset_s": tz,
                "started_local": _local_iso(start, tz),
                "duration_ms": None if end is None else end - start,
                "beats": n, "coverage": round(_app_coverage(con, rid), 4),
                "labels": [e["label"] for e in _events(con, rid, markers_only=True) if e["label"]],
            }
            out.append({k: v for k, v in entry.items() if v is not None})
    return out


def file_name(name: str, started_at_ms: int, tz_offset_s: int) -> str:
    """StrapLogCore's `Snapshot.fileName`: `YYMMDD-HHMM-<name>.sqlite` in the
    recording's local time, the name's other characters replaced by `_`."""
    local = datetime.fromtimestamp(started_at_ms / 1000 + tz_offset_s, timezone.utc)
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
    stamp = local.strftime("%y%m%d-%H%M")
    return f"{stamp}-{safe}.sqlite" if safe else f"{stamp}.sqlite"


def beats(path: Path, rid: int | None = None) -> list[dict]:
    """Beats in true order: `t_ms` (estimated beat end, epoch ms UTC) and
    `rr_ms` (exact). The H10 sends no beat times, so `t_ms` is anchored on
    phone receipt and clamped non-decreasing against BLE delivery jitter."""
    with _open(path) as con:
        rid = _one_recording(con, rid, path)
        rows = con.execute("SELECT t_end_ms_est, rr_ms FROM beat WHERE recording_id=? "
                           "ORDER BY id", (rid,)).fetchall()
    out, last = [], None
    for t, rr in rows:
        last = t if last is None else max(last, t)
        out.append({"t_ms": last, "rr_ms": rr})
    return out


def events(path: Path, rid: int | None = None, markers_only: bool = False) -> list[dict]:
    """Events in time order: `at_ms`, `kind`, `label` (v3 markers), `note`."""
    with _open(path) as con:
        return _events(con, _one_recording(con, rid, path), markers_only)


def _events(con: sqlite3.Connection, rid: int, markers_only: bool) -> list[dict]:
    label = "label" if "label" in columns(con, "event") else "NULL"
    where = " AND kind='marker'" if markers_only else ""
    return [dict(zip(("at_ms", "kind", "label", "note"), r)) for r in con.execute(
        f"SELECT at_ms, kind, {label}, note FROM event WHERE recording_id=?{where} "
        "ORDER BY at_ms, id", (rid,))]


def _app_coverage(con: sqlite3.Connection, rid: int) -> float:
    """StrapLogCore's `Coverage.fraction`: first-to-last notification span
    minus silences over GAP_THRESHOLD_MS, over that span; 0 if empty. (The
    HRV skills' `straplog.db.coverage` divides by the recording span instead.)"""
    t = [r[0] for r in con.execute("SELECT received_at_ms FROM notification "
                                   "WHERE recording_id=? ORDER BY received_at_ms", (rid,))]
    span = t[-1] - t[0] if len(t) > 1 else 0
    if span <= 0:
        return 0.0
    gaps = sum(b - a for a, b in zip(t, t[1:]) if b - a > GAP_THRESHOLD_MS)
    return (span - gaps) / span


def _recordings(con: sqlite3.Connection) -> list[tuple]:
    """(id, name, activity, started_at_ms, ended_at_ms, tz_offset_s), newest first."""
    activity = "activity" if "activity" in columns(con, "recording") else "'other'"
    return con.execute(
        f"SELECT id, name, {activity}, started_at_ms, ended_at_ms, tz_offset_s "
        "FROM recording ORDER BY started_at_ms DESC, id DESC").fetchall()


def _named(recs: list[tuple], path: Path) -> int | None:
    """The id of the recording `path` is named after, if any."""
    return next((r[0] for r in recs if file_name(r[1], r[3], r[5]) == Path(path).name), None)


def _one_recording(con: sqlite3.Connection, rid: int | None, path: Path) -> int:
    recs = _recordings(con)
    ids = sorted(r[0] for r in recs)
    if rid is None:
        rid = ids[0] if len(ids) == 1 else _named(recs, path)
        if rid is None:
            raise SystemExit(f"File holds recordings {ids}; pick one with --id.")
    if rid not in ids:
        raise SystemExit(f"Recording {rid} not found; the file holds {ids}.")
    return rid


def _local_iso(ms: int, tz_offset_s: int) -> str:
    """ISO 8601 with offset, as Swift's ISO8601DateFormatter writes it."""
    dt = datetime.fromtimestamp(ms / 1000, timezone(timedelta(seconds=tz_offset_s)))
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


@contextmanager
def _open(path: Path) -> Iterator[sqlite3.Connection]:
    """A checked, immutable, read-only connection."""
    require_snapshot(path)
    con = connect(path)
    try:
        yield con
    finally:
        con.close()
