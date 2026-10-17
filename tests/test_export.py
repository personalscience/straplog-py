"""straplog.export: a file as stored, and the index entries it yields."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from conftest import START_MS, TZ, make_straplog, make_v3, steady
from straplog import export


def test_v3_entry_matches_export_index_entry(tmp_path: Path):
    path = make_v3(tmp_path / "261015-1349-sleep_2026-10-15.sqlite", steady(100),
                   markers=[(START_MS + 5000, "lights_out", None), (START_MS + 9000, None, "noise"),
                            (START_MS + 60_000, "awake", "bathroom")],
                   end_ms=START_MS + 100_000)
    assert export.recordings(path) == [{
        "file": path.name, "id": 1, "name": "sleep 2026-10-15", "activity": "sleep",
        "started_at_ms": START_MS, "ended_at_ms": START_MS + 100_000, "tz_offset_s": TZ,
        "started_local": "2026-10-15T13:49:34-07:00", "duration_ms": 100_000,
        "beats": 100, "coverage": 1.0, "labels": ["lights_out", "awake"]}]


def test_meta_decodes_json_values(tmp_path: Path):
    path = make_v3(tmp_path / "s.sqlite", steady(3))
    m = export.meta(path)
    assert m["schema_version"] == "3" and m["app_version"] == "0.2.0 (7)"
    assert m["preset"]["markers"] == ["lights_out", "awake", "up"]
    assert m["event_kinds"] == ["start", "stop", "marker"]


def test_v2_reads_as_other_without_labels(walk: Path):
    [e] = export.recordings(walk)
    assert e["activity"] == "other" and e["labels"] == []
    assert [(x["kind"], x["label"], x["note"]) for x in export.events(walk, markers_only=True)] == \
        [("marker", None, "a"), ("marker", None, "end")]


def test_unfinished_recording_omits_end_and_duration(tmp_path: Path):
    [e] = export.recordings(make_straplog(tmp_path / "u.sqlite", steady(5), [], None))
    assert "ended_at_ms" not in e and "duration_ms" not in e


def test_coverage_is_the_apps_notification_span_fraction(tmp_path: Path):
    # Notifications 10..39 s and 60..89 s: span 79 s, one 21 s gap.
    notes = steady(30, t0=START_MS + 10_000) + steady(30, t0=START_MS + 60_000)
    [e] = export.recordings(make_straplog(tmp_path / "c.sqlite", notes, [], START_MS + 100_000))
    assert e["coverage"] == round(58 / 79, 4)


def test_beats_are_utc_ms_and_never_run_backwards(tmp_path: Path):
    notes = [(START_MS + 1000, [512, 512]), (START_MS + 1200, [1024, 512])]
    b = export.beats(make_straplog(tmp_path / "j.sqlite", notes, [], None))
    assert [x["rr_ms"] for x in b] == [500.0, 500.0, 1000.0, 500.0]
    assert [x["t_ms"] for x in b] == [START_MS + 500, START_MS + 1000, START_MS + 1000, START_MS + 1200]


def test_file_name_mirrors_snapshot_file_name():
    assert export.file_name("SLEEP 261015", 1792122309426, -25200) == "261015-2045-SLEEP_261015.sqlite"
    assert export.file_name("", START_MS, TZ) == "261015-1349.sqlite"


def two_recordings(path: Path) -> Path:
    """A pre-per-recording export: every recording, named after the second."""
    make_straplog(path, steady(5), [], START_MS + 5000, name="FIRST")
    con = sqlite3.connect(path)
    con.execute("INSERT INTO recording(id, name, started_at_ms, ended_at_ms, tz_offset_s) "
                "VALUES (2, 'SECOND', ?, ?, ?)", (START_MS + 3_600_000, START_MS + 3_700_000, TZ))
    con.execute("INSERT INTO notification VALUES (99, 2, ?, 60, 1, 1)", (START_MS + 3_600_500,))
    con.execute("INSERT INTO beat(recording_id, notification_id, idx, rr_1024, rr_ms, t_end_ms_est) "
                "VALUES (2, 99, 0, 1024, 1000.0, ?)", (START_MS + 3_600_500,))
    con.commit()
    con.close()
    return path


def test_multi_recording_file_defaults_to_its_named_recording(tmp_path: Path):
    path = two_recordings(tmp_path / "261015-1449-SECOND.sqlite")
    assert [e["name"] for e in export.recordings(path)] == ["SECOND", "FIRST"]
    assert [e["name"] for e in export.recordings(path, named_only=True)] == ["SECOND"]
    assert len(export.beats(path)) == 1
    assert len(export.beats(path, 1)) == 5


def test_ambiguous_file_needs_an_id(tmp_path: Path):
    path = two_recordings(tmp_path / "renamed.sqlite")
    with pytest.raises(SystemExit, match=r"recordings \[1, 2\]; pick one"):
        export.beats(path)
    with pytest.raises(SystemExit, match="Recording 3 not found"):
        export.events(path, 3)
