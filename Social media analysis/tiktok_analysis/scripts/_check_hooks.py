import csv
from pathlib import Path

tracker = Path(__file__).resolve().parents[2] / "Marketing - Content - Tracker - Content Tracker (3).csv"
rows = list(csv.DictReader(tracker.open(encoding="utf-8-sig", newline="")))

print("Hook-related columns:", [k for k in rows[0].keys() if "hook" in k.lower() or "cover" in k.lower()])
print()

for r in rows:
    tt = r.get("TT_Link", "").strip()
    hook = r.get("Hook_Cover_Text", "").strip()
    if tt:
        vid = tt.rstrip("/").split("/")[-1]
        print(f"{vid}  |  hook: {repr(hook)}")
