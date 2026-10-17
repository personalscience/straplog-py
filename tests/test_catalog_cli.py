"""straplog.catalog and the CLI over a folder of exports."""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import pytest

from conftest import START_MS, make_v3, steady
from straplog import catalog, cli, export

DAY = 86_400_000


@pytest.fixture
def folder(tmp_path: Path, walk: Path) -> Path:
    """The walk (v2, unindexed) plus a v3 sleep a day later listed in index.json."""
    sleep = make_v3(tmp_path / "scratch.sqlite", steady(10), markers=[(START_MS + 2000, "lights_out", None)],
                    end_ms=START_MS + 10_000)
    entry = export.recordings(sleep)[0]
    entry |= {"file": "261016-1349-sleep.sqlite", "started_at_ms": START_MS + DAY}
    sleep.rename(tmp_path / entry["file"])
    (tmp_path / "index.json").write_text(json.dumps(
        {"format": "straplog-index", "version": 1, "recordings": [entry]}))
    return tmp_path


def test_index_then_scan_newest_first(folder: Path):
    rows = catalog.entries(folder)
    assert [(e["activity"], e["file"]) for e in rows] == [
        ("sleep", "261016-1349-sleep.sqlite"), ("other", "261015-1349-WALK.sqlite")]
    assert all(e["downloaded"] and Path(e["path"]).parent == folder for e in rows)


def test_evicted_index_entry_is_not_downloaded(folder: Path):
    (folder / "261016-1349-sleep.sqlite").rename(folder / ".261016-1349-sleep.sqlite.icloud")
    assert [e["downloaded"] for e in catalog.entries(folder)] == [False, True]


def test_select(folder: Path):
    rows = catalog.entries(folder)
    now = START_MS + DAY + 1000
    assert [e["activity"] for e in catalog.select(rows, activity="sleep")] == ["sleep"]
    assert [e["activity"] for e in catalog.select(rows, since="12h", now_ms=now)] == ["sleep"]
    assert len(catalog.select(rows, since="2d", now_ms=now)) == 2
    assert len(catalog.select(rows, limit=1)) == 1


def test_since_accepts_iso_dates():
    assert catalog.since_ms("2026-10-15T13:49:34-07:00", 0) == START_MS


def run(capsys, *argv: str) -> str:
    cli.main(list(argv))
    return capsys.readouterr().out


def test_cli_ls(folder: Path, capsys):
    rows = json.loads(run(capsys, "ls", str(folder), "--activity", "sleep", "--json"))
    assert [r["labels"] for r in rows] == [["lights_out"]]
    table = list(csv.DictReader(io.StringIO(run(capsys, "ls", str(folder)))))
    assert [r["activity"] for r in table] == ["sleep", "other"]
    assert table[0]["labels"] == "lights_out"


def test_cli_rr_events_meta(walk: Path, capsys):
    rr = list(csv.DictReader(io.StringIO(run(capsys, "rr", str(walk)))))
    assert len(rr) == 200 and rr[0] == {"t_ms": str(START_MS + 500), "rr_ms": "1000.0"}
    ev = json.loads(run(capsys, "events", str(walk), "--markers", "--json"))
    assert [e["note"] for e in ev] == ["a", "end"]
    m = json.loads(run(capsys, "meta", str(walk)))
    assert m["meta"]["schema_version"] == "2" and m["recordings"][0]["name"] == "WALK"


def test_cli_resolves_bare_names_in_the_default_folder(walk: Path, monkeypatch, capsys):
    monkeypatch.setattr(catalog, "DEFAULT_DIR", walk.parent)
    monkeypatch.chdir(walk.parent.parent)
    assert len(json.loads(run(capsys, "rr", walk.name, "--json"))) == 200


def test_cli_missing_file(capsys):
    with pytest.raises(SystemExit, match="No such export"):
        cli.main(["rr", "/nonexistent/x.sqlite"])
