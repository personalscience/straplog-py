"""`straplog`: the agent tool surface over StrapLog exports.

    straplog ls [FOLDER|FILE] [--activity sleep] [--since 14d] [--limit N] [--json]
    straplog rr FILE [--id N] [--json]          beats: t_ms, rr_ms
    straplog events FILE [--id N] [--markers] [--json]
    straplog meta FILE

FILE is a path or a bare export name in the iCloud folder. Times are epoch ms
UTC; local time = UTC + tz_offset_s (`ls` prints it as `started_local`).
Tables print as CSV unless --json.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from . import catalog, export

LS_COLUMNS = ("started_local", "activity", "name", "duration_ms", "beats", "coverage", "labels", "file")


def main(argv: list[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    args.run(args)


def _ls(args) -> None:
    rows = catalog.select(catalog.entries(args.where), args.activity, args.since, args.limit)
    if args.json:
        _json(rows)
    else:
        _csv([{**r, "labels": " ".join(r["labels"])} for r in rows], LS_COLUMNS)


def _rr(args) -> None:
    _table(export.beats(_file(args), args.id), ("t_ms", "rr_ms"), args.json)


def _events(args) -> None:
    _table(export.events(_file(args), args.id, args.markers), ("at_ms", "kind", "label", "note"), args.json)


def _meta(args) -> None:
    path = _file(args)
    _json({"meta": export.meta(path), "recordings": export.recordings(path)})


def _file(args) -> Path:
    path = catalog.resolve(args.file)
    if not path.exists():
        raise SystemExit(f"No such export: {path}")
    return path


def _table(rows: list[dict], cols: tuple[str, ...], as_json: bool) -> None:
    _json(rows) if as_json else _csv(rows, cols)


def _json(value) -> None:
    json.dump(value, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")


def _csv(rows: list[dict], cols: tuple[str, ...]) -> None:
    w = csv.DictWriter(sys.stdout, cols, extrasaction="ignore", lineterminator="\n")
    w.writeheader()
    w.writerows(rows)


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="straplog", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(required=True, metavar="COMMAND")

    ls = sub.add_parser("ls", help="list recordings, newest first")
    ls.add_argument("where", nargs="?", type=Path, default=catalog.DEFAULT_DIR,
                    help="folder of exports or one export (default: the iCloud folder)")
    ls.add_argument("--activity", help="e.g. sleep, other")
    ls.add_argument("--since", help="14d, 12h, 90m, or an ISO date")
    ls.add_argument("--limit", type=int)
    ls.add_argument("--json", action="store_true")
    ls.set_defaults(run=_ls)

    for name, run, help_ in (("rr", _rr, "beats: t_ms, rr_ms"),
                             ("events", _events, "events: at_ms, kind, label, note"),
                             ("meta", _meta, "meta table and index entry, as JSON")):
        c = sub.add_parser(name, help=help_)
        c.add_argument("file")
        c.set_defaults(run=run)
        if name != "meta":
            c.add_argument("--id", type=int, help="recording id (only for multi-recording files)")
            c.add_argument("--json", action="store_true")
    sub.choices["events"].add_argument("--markers", action="store_true", help="markers only")
    return p


if __name__ == "__main__":
    main()
