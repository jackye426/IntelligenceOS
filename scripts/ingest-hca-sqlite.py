#!/usr/bin/env python3
"""CLI entrypoint for HCA SQLite migration."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "data-worker"
sys.path.insert(0, str(ROOT))

from jobs.hca_sqlite import run_hca_migration  # noqa: E402


def main() -> None:
    sqlite_path = sys.argv[1] if len(sys.argv) > 1 else None
    result = run_hca_migration(sqlite_path)
    print(result)


if __name__ == "__main__":
    main()
