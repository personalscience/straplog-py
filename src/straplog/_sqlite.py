"""Opening a StrapLog export safely."""
from __future__ import annotations

import sqlite3
from pathlib import Path


def connect(db_path: Path) -> sqlite3.Connection:
    """Open read-only and immutable: no -wal/-shm is ever created beside the
    user's export."""
    return sqlite3.connect(f"{Path(db_path).resolve().as_uri()}?immutable=1",
                           uri=True)


def require_snapshot(db_path: Path) -> None:
    """A StrapLog -wal means the live database, which an immutable read would
    see only partly. Exports are always single files."""
    if Path(str(db_path) + "-wal").exists():
        raise SystemExit(
            f"{db_path} has a -wal sidecar, so it is StrapLog's live database. "
            "Use an exported snapshot (iCloud Drive > StrapLog > <date>-<name>.sqlite, on the Mac "
            "~/Library/Mobile Documents/iCloud~com~personalscience~straplog/Documents/).")


def columns(con: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
