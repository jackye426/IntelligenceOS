"""Print decay metrics for the Spire roster from Supabase."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from spire_monitor.config import load_consultants  # noqa: E402
from spire_monitor.metrics import compute_decay_metrics  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    results = []
    for c in load_consultants():
        m = compute_decay_metrics(c.consultant_id)
        results.append(m.as_dict())
        if not args.json:
            print(f"\n{m.practitioner_name} ({m.practitioner_id})")
            print(f"  location={m.location}  total={m.total_unique_slots}")
            print(
                f"  visible={m.currently_visible}  disappeared={m.disappeared}  expired={m.expired}"
            )
            print(f"  slots within T-windows: {m.slots_within_t_windows}")
            print(f"  % still visible at T:   {m.pct_visible_at_t_windows}")

    if args.json:
        print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
