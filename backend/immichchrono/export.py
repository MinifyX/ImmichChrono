"""Export the decision log as JSON lines: `python -m immichchrono.export [--user ID] > decisions.jsonl`."""

from __future__ import annotations

import argparse
import sys

from .config import settings
from .db import Database
from .decisions import export


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m immichchrono.export", description=__doc__)
    parser.add_argument("--user", help="nur Entscheidungen dieser Immich-User-ID")
    parser.add_argument("--db", default=str(settings.db_path), help="Pfad zur SQLite-Datenbank")
    args = parser.parse_args(argv)
    db = Database(args.db)
    for line in export(db, args.user):
        sys.stdout.write(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
