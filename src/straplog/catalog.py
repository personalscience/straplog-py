"""Find recordings in a folder of exports: `index.json` first, then a scan.

The app rewrites `index.json` after every export and delete (ExportIndex),
so an agent reads one file instead of opening each snapshot. Exports the
index does not list (older builds, files copied in from elsewhere) are
read directly, each as the recording it is named after, so a folder without
an index still lists completely and without duplicates.
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime
from pathlib import Path

from . import export

DEFAULT_DIR = Path.home() / "Library/Mobile Documents/iCloud~com~personalscience~straplog/Documents"
INDEX = "index.json"


def entries(where: Path = DEFAULT_DIR) -> list[dict]:
    """Index entries, newest first, each with `path` and `downloaded` added.
    `where` is a folder of exports or a single export file."""
    where = Path(where).expanduser()
    if where.is_file():
        return [_located(e, where.parent) for e in export.recordings(where)]
    indexed = []
    if (where / INDEX).exists():
        indexed = json.loads((where / INDEX).read_text())["recordings"]
    listed = {e["file"] for e in indexed}
    scanned = [e for f in sorted(where.glob("*.sqlite")) if f.name not in listed
               for e in export.recordings(f, named_only=True)]
    rows = [_located(e, where) for e in indexed + scanned]
    return sorted(rows, key=lambda e: (e["started_at_ms"], e["id"]), reverse=True)


def select(rows: list[dict], activity: str | None = None, since: str | None = None,
           limit: int | None = None, now_ms: int | None = None) -> list[dict]:
    if activity:
        rows = [e for e in rows if e["activity"] == activity]
    if since:
        cutoff = since_ms(since, now_ms if now_ms is not None else int(time.time() * 1000))
        rows = [e for e in rows if e["started_at_ms"] >= cutoff]
    return rows[:limit] if limit else rows


def since_ms(since: str, now_ms: int) -> int:
    """`14d`, `12h`, `90m` back from now, or an ISO date/time (local if naive)."""
    m = re.fullmatch(r"(\d+)([dhm])", since)
    if m:
        return now_ms - int(m[1]) * {"d": 86_400_000, "h": 3_600_000, "m": 60_000}[m[2]]
    return int(datetime.fromisoformat(since).astimezone().timestamp() * 1000)


def resolve(file: str, folder: Path | None = None) -> Path:
    """A path, or a bare export name looked up in `folder` (default DEFAULT_DIR)."""
    p = Path(file).expanduser()
    if p.exists() or p.parent != Path("."):
        return p
    return Path(folder or DEFAULT_DIR) / file


def _located(entry: dict, folder: Path) -> dict:
    path = folder / entry["file"]
    return {**entry, "path": str(path), "downloaded": path.exists()}
