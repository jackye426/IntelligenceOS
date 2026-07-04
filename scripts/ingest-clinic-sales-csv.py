#!/usr/bin/env python3
"""CLI shim for the P4 clinic sales CSV seed lane.

Equivalent to: python -m ingestion_pipeline sync clinic-csv [args]
Works without installing the package (adds src/ to sys.path).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ingestion-pipeline" / "src"))

from ingestion_pipeline.cli import main  # noqa: E402

main(["sync", "clinic-csv", *sys.argv[1:]])
