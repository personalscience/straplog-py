"""Synthetic StrapLog exports in the schema of docs/SCHEMA.md."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

TZ = -25200                       # PDT
START_MS = 1_792_097_374_000      # 2026-10-15 13:49:34 PDT
APPLE = 978307200.0

V2_DDL = """
CREATE TABLE meta(key TEXT PRIMARY KEY NOT NULL, value TEXT NOT NULL);
CREATE TABLE recording(id INTEGER PRIMARY KEY, name TEXT NOT NULL,
  started_at_ms INTEGER NOT NULL, ended_at_ms INTEGER, tz_offset_s INTEGER NOT NULL,
  device_id TEXT, firmware TEXT, battery_start INTEGER, battery_end INTEGER, notes TEXT);
CREATE TABLE notification(id INTEGER PRIMARY KEY, recording_id INTEGER NOT NULL,
  received_at_ms INTEGER NOT NULL, hr_bpm INTEGER NOT NULL, contact INTEGER, n_rr INTEGER NOT NULL);
CREATE TABLE beat(id INTEGER PRIMARY KEY, recording_id INTEGER NOT NULL,
  notification_id INTEGER NOT NULL, idx INTEGER NOT NULL, rr_1024 INTEGER NOT NULL,
  rr_ms REAL NOT NULL, t_end_ms_est INTEGER NOT NULL, UNIQUE(notification_id, idx));
CREATE TABLE event(id INTEGER PRIMARY KEY, recording_id INTEGER NOT NULL,
  at_ms INTEGER NOT NULL, kind TEXT NOT NULL, note TEXT);
INSERT INTO meta VALUES ('format', 'straplog'), ('schema_version', '2');
"""

V3_MIGRATION = """
ALTER TABLE recording ADD COLUMN activity TEXT NOT NULL DEFAULT 'other';
ALTER TABLE recording ADD COLUMN context TEXT;
ALTER TABLE event ADD COLUMN label TEXT;
UPDATE meta SET value = '3' WHERE key = 'schema_version';
"""

SLEEP_PRESET = {"id": "sleep", "title": "Sleep", "markers": ["lights_out", "awake", "up"],
                "pacer": False, "overnight": True}


def make_straplog(path: Path, notifications: list[tuple[int, list[int]]],
                  events: list[tuple[int, str, str | None]],
                  end_ms: int | None, name: str = "WALK") -> Path:
    """A v2 export. notifications: (received_at_ms, [rr_1024, ...]); beats get
    the app's t_end_ms_est = received - sum(later rr in the same notification)."""
    con = sqlite3.connect(path)
    con.executescript(V2_DDL)
    con.execute("INSERT INTO recording(id, name, started_at_ms, ended_at_ms, tz_offset_s) "
                "VALUES (1, ?, ?, ?, ?)", (name, START_MS, end_ms, TZ))
    for nid, (rx, rrs) in enumerate(notifications, start=1):
        con.execute("INSERT INTO notification VALUES (?, 1, ?, 70, 1, ?)", (nid, rx, len(rrs)))
        for idx, r in enumerate(rrs):
            later = sum(rrs[idx + 1:])
            con.execute("INSERT INTO beat(recording_id, notification_id, idx, rr_1024, rr_ms, t_end_ms_est) "
                        "VALUES (1, ?, ?, ?, ?, ?)",
                        (nid, idx, r, r * 1000 / 1024, rx - round(later * 1000 / 1024)))
    for at, kind, note in events:
        con.execute("INSERT INTO event(recording_id, at_ms, kind, note) VALUES (1, ?, ?, ?)",
                    (at, kind, note))
    con.commit()
    con.close()
    return path


def make_v3(path: Path, notifications, activity: str = "sleep",
            markers: list[tuple[int, str | None, str | None]] = (),
            end_ms: int | None = None, name: str = "sleep 2026-10-15") -> Path:
    """A v3 export with ExportMeta rows; markers are (at_ms, label, note)."""
    make_straplog(path, notifications, [(START_MS, "start", None)], end_ms, name)
    con = sqlite3.connect(path)
    con.executescript(V3_MIGRATION)
    con.execute("UPDATE recording SET activity = ?", (activity,))
    con.executemany("INSERT INTO event(recording_id, at_ms, kind, label, note) "
                    "VALUES (1, ?, 'marker', ?, ?)", markers)
    con.executemany("INSERT INTO meta VALUES (?, ?)", [
        ("app_version", "0.2.0 (7)"), ("exported_at_ms", str(START_MS + 10**7)),
        ("preset", json.dumps(SLEEP_PRESET)), ("event_kinds", '["start","stop","marker"]')])
    con.commit()
    con.close()
    return path


def steady(n: int, rr_1024: int = 1024, t0: int = START_MS + 500) -> list[tuple[int, list[int]]]:
    """n notifications one beat each, 1 s apart."""
    return [(t0 + i * 1000, [rr_1024]) for i in range(n)]


@pytest.fixture
def walk(tmp_path: Path) -> Path:
    events = [(START_MS, "start", None), (START_MS + 400, "connect", "119D243F"),
              (START_MS + 60_250, "marker", "a"), (START_MS + 120_750, "marker", "end"),
              (START_MS + 200_000, "stop", None)]
    return make_straplog(tmp_path / "261015-1349-WALK.sqlite", steady(200), events,
                         end_ms=START_MS + 200_000)
