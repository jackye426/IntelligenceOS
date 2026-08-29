# Spire appointment utilization monitor

Snapshots public Spire COBPS booking slots for a locked Cardiff roster, upserts
lifecycle into Supabase `appointment_slots` (`source_system = spire_monitor`), and
runs **3×/day Europe/London** on Railway.

## Roster (default)

| Consultant | ID |
|---|---|
| Mr Simon Phillips | `C4069414` |
| Miss Julie Cornish | `C6031568` |
| Mr Faris Soliman | `C7082057` |

Override with `SPIRE_CONSULTANTS` JSON env if needed.

## Local

```bash
cd appointment-monitor
pip install -r requirements.txt
cp .env.example .env   # or rely on repo-root .env.local for Supabase keys

# Fetch only (no DB writes)
python run_once.py --dry-run

# Write to Supabase
python run_once.py

# Metrics (needs ≥3 scrapes for survival %)
python compute_metrics.py

# Scheduler (keeps process alive)
python scheduler.py
python scheduler.py --test-interval 2
```

## Railway

1. New service, **Root Directory** = `appointment-monitor`
2. Env: `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `RUN_ON_START=true`, `LOG_LEVEL=INFO`
3. Deploy — `scheduler.py` runs scrapes at 07:00 / 13:00 / 19:00 London

No Playwright. HTTP-only.

## Plan

See `docs/EXECUTION_PLAN_APPOINTMENT_UTILIZATION_SPIRE.md`.
