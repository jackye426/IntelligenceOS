#!/usr/bin/env python3
"""CLI entrypoint for content tracker ingestion."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "data-worker"
sys.path.insert(0, str(ROOT))

from jobs.content_tracker import run_content_tracker  # noqa: E402


def main() -> None:
    csv_path = sys.argv[1] if len(sys.argv) > 1 else None
    result = run_content_tracker(csv_path)
    print(result)


if __name__ == "__main__":
    main()
