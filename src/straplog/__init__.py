"""Read StrapLog exports: one single-file SQLite snapshot per recording.

`straplog.export` reads a file as stored (epoch ms UTC, typed markers);
`straplog.catalog` lists a folder of exports; `straplog.db` loads into the
HRV skills' Apple-epoch local-time convention; `straplog.hrv` holds the
format-agnostic HRV algorithms; `straplog.plot` is the house chart style
(needs the `plot` extra); `straplog.cli` is the agent tool surface.
The schema is docs/SCHEMA.md in the StrapLog app repo.
"""
__version__ = "0.2.0"
