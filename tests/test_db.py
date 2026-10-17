"""straplog.db: the HRV skills' loader convention (Apple-epoch local seconds)."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd
import pytest

import straplog.db as straplog_db
from conftest import APPLE, START_MS, TZ, make_straplog, steady


def test_detects_format(walk: Path, tmp_path: Path):
    other = tmp_path / "DB.sqlite"
    sqlite3.connect(other).executescript("CREATE TABLE ZRECORDING(Z_PK INTEGER PRIMARY KEY);")
    assert straplog_db.is_straplog(walk)
    assert not straplog_db.is_straplog(other)


def test_times_are_local_apple_epoch_seconds(walk: Path):
    rr, ev, start, name = straplog_db.load_recording(walk, 1)
    first_beat_ms = START_MS + 500
    assert list(rr.columns) == ["t", "rr_ms", "t_rel"]
    assert list(ev.columns) == ["t", "note", "t_rel"]
    assert rr["t"].iloc[0] == pytest.approx(first_beat_ms / 1000 + TZ - APPLE)
    assert start == pd.Timestamp("2026-10-15 13:49:34.500") and start.tz is None
    assert rr["rr_ms"].iloc[0] == 1000.0
    assert name == "WALK"


def test_markers_become_events(walk: Path):
    _, ev, _, _ = straplog_db.load_recording(walk, 1)
    assert ev["note"].tolist() == ["a", "end"]
    assert ev["t_rel"].tolist() == pytest.approx([59.75, 120.25])


def test_v3_marker_labels_read_as_notes(tmp_path: Path):
    path = make_straplog(tmp_path / "v3.sqlite", steady(5), [], START_MS + 5000)
    con = sqlite3.connect(path)
    con.executescript("""
        ALTER TABLE recording ADD COLUMN activity TEXT NOT NULL DEFAULT 'other';
        ALTER TABLE recording ADD COLUMN context TEXT;
        ALTER TABLE event ADD COLUMN label TEXT;
        UPDATE meta SET value = '3' WHERE key = 'schema_version';
    """)
    con.executemany("INSERT INTO event(recording_id, at_ms, kind, label, note) VALUES (1, ?, 'marker', ?, ?)",
                    [(START_MS + 1000, "a", None), (START_MS + 2000, None, "felt dizzy"),
                     (START_MS + 3000, "awake", "bathroom")])
    con.commit()
    con.close()
    _, ev, _, _ = straplog_db.load_recording(path, 1)
    assert ev["note"].tolist() == ["a", "felt dizzy", "awake · bathroom"]


def test_beats_keep_id_order_and_time_never_runs_backwards(tmp_path: Path):
    # The first notification is delivered late (BLE jitter), so the second
    # one's first beat is estimated 300 ms before the first one's last beat.
    notes = [(START_MS + 1000, [512, 512]), (START_MS + 1200, [1024, 512]), (START_MS + 2200, [1024])]
    db = make_straplog(tmp_path / "j.sqlite", notes, [(START_MS, "start", None)], None)
    rr = straplog_db.load_rr(db, 1)
    assert rr["rr_ms"].tolist() == [500.0, 500.0, 1000.0, 500.0, 1000.0]
    assert rr["t"].is_monotonic_increasing
    assert rr["t"].iloc[2] == rr["t"].iloc[1]


def test_coverage_counts_notification_gaps(tmp_path: Path):
    # 100 s recording: start, notifications every 1 s from t=10..39 and
    # t=60..89 (a 21 s dropout between), then silence to the end.
    notes = steady(30, t0=START_MS + 10_000) + steady(30, t0=START_MS + 60_000)
    db = make_straplog(tmp_path / "c.sqlite", notes, [(START_MS, "start", None)],
                       end_ms=START_MS + 100_000)
    assert straplog_db.coverage(db, 1) == pytest.approx(58 / 100)
    [row] = straplog_db.list_recordings(db)
    assert row["coverage"] == 0.58


def test_list_recordings(walk: Path):
    [row] = straplog_db.list_recordings(walk)
    assert row == {"pk": 1, "name": "WALK", "start_local": "2026-10-15T13:49:34",
                   "n_beats": 200, "duration_min": 3.3, "avg_hr": 60.0, "coverage": 0.995}


def test_unfinished_recording_spans_to_last_notification(tmp_path: Path):
    db = make_straplog(tmp_path / "u.sqlite", steady(60), [(START_MS, "start", None)], None)
    [row] = straplog_db.list_recordings(db)
    assert row["duration_min"] == round((59_500) / 60000, 1)


def test_live_database_is_refused(walk: Path):
    Path(str(walk) + "-wal").write_bytes(b"")
    with pytest.raises(SystemExit, match="live database"):
        straplog_db.load_rr(walk, 1)


def test_reads_never_write_sidecars(walk: Path, tmp_path: Path):
    straplog_db.load_recording(walk, 1)
    straplog_db.list_recordings(walk)
    assert sorted(p.name for p in tmp_path.iterdir()) == [walk.name]
