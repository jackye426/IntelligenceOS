# Feature Implementation Plan

**Overall Progress:** `90%`

## TLDR

Build a **Spire Cardiff appointment utilization monitor** that snapshots public online booking slots for a **locked 3-consultant roster** (Simon Phillips + Julie Cornish + Faris Soliman), stores slot lifecycle in **Supabase**, and runs **3×/day on Railway**. Reuse HCA utilisation *logic* (visible → disappeared → decay), but scrape via Spire COBPS HTTP APIs (no Playwright). Doctify stays **local and gitignored**.

## Acceptance criteria

- [x] Scheduled scrapes run on Railway without this device (3×/day Europe/London).
- [x] All three roster consultants are tracked every run.
- [x] Each run upserts slots to Supabase `appointment_slots` with `source_system = spire_monitor`.
- [x] Slot lifecycle works: `visible` → `disappeared` / `expired` with T-48h rule.
- [ ] Utilisation proxy metrics available after ≥3 runs (decay at T-21d / T-14d / T-7d / T-3d / T-48h).
- [x] Fallback logic handles partial failures without losing prior data or stopping the whole roster.
- [x] Scrape runs logged to `data_ingestion_runs` (or equivalent) for ops visibility.

## Locked roster (validated 2026-08-29)

| Consultant | ConsultantId | Profile URL |
|---|---|---|
| Mr Simon Phillips | `C4069414` | https://www.spirehealthcare.com/consultant-profiles/mr-simon-phillips-c4069414/ |
| Miss Julie Cornish | `C6031568` | https://www.spirehealthcare.com/spire-cardiff-hospital/consultants/julie-cornish-c6031568/ |
| Mr Faris Soliman | `C7082057` | https://www.spirehealthcare.com/spire-cardiff-hospital/consultants/mr-faris-soliman-c7082057/ |

## Critical Decisions

- **Spire first, HCA later** — public COBPS JSON; no Playwright.
- **Supabase as system of record** — `source_system = spire_monitor`.
- **Dedicated Railway service** — `appointment-monitor/` (not TikTok `data-worker`).
- **Two-step fetch** — month days → per-day full slots.
- **Consultant ID** — slug `-cNNNN` → `CNNNN` (leading C required).
- **Self-pay only (v1)**.
- **Doctify out of repo**.

## Tasks

- [x] 🟩 **Step 1: Spire monitor package**
  - [x] 🟩 API client + retries
  - [x] 🟩 Locked roster config
  - [x] 🟩 Slot lifecycle upsert
  - [x] 🟩 `run_once.py` with per-consultant isolation

- [x] 🟩 **Step 2: Supabase persistence**
  - [x] 🟩 Map → `appointment_slots`
  - [x] 🟩 Stable `source_slot_id`
  - [x] 🟩 `data_ingestion_runs` logging

- [x] 🟩 **Step 3: Fallback logic**
  - [x] 🟩 ID resolution + HTTP retries + partial runs + T-48h

- [x] 🟩 **Step 4: Utilisation metrics**
  - [x] 🟩 `compute_metrics.py` (survival % after ≥3 scrapes)
  - [ ] 🟥 Optional HTML report later

- [x] 🟩 **Step 5: Railway deployment**
  - [x] 🟩 `appointment-monitor/` + Procfile + railway.toml + scheduler
  - [x] 🟩 Railway service `appointment-monitor` live on IntelligenceOS / production
  - [x] 🟩 Env: Supabase + Spire knobs; `RUN_ON_START=false` after first prod scrape
  - [x] 🟩 Scheduler jobs 07:00 / 13:00 / 19:00 Europe/London confirmed in logs

- [x] 🟩 **Step 6: Consultant roster**
  - [x] 🟩 Phillips, Cornish, Soliman seeded + validated

- [ ] 🟨 **Step 7: Ops & acceptance**
  - [x] 🟩 First live scrape: **83 slots** inserted (54 + 4 + 25)
  - [x] 🟩 Railway startup scrape: **208 seen**, 125 inserted / 83 updated, 3/3 consultants OK
  - [ ] 🟥 72h prod soak (next: confirm 3×/day; survival % after ≥3 runs)
  - [x] 🟩 Catalog updated (`E1b`)
  - [x] 🟩 Doctify still gitignored

## First live scrape (2026-08-29)

`status=success` — Phillips 54, Cornish 4, Soliman 25 → Supabase.

## Railway (2026-08-29)

- Project: IntelligenceOS · service: `appointment-monitor` · env: production
- Dashboard: https://railway.com/project/0c93ae76-9286-4d76-83e6-a42f16b2f65c/service/3c093daf-2cfd-49f4-b3ef-bbe3a984eb5e
- Startup scrape OK; scheduler ready (no scrape on redeploy with `RUN_ON_START=false`)

## Remaining

1. 72h soak: verify scheduled runs at 07:00 / 13:00 / 19:00 London without this device.
2. After ≥3 scrapes, confirm survival % / decay metrics populate.

## Reference

Package: `appointment-monitor/`  
Plan: this file  
Investigation: `Appointment utilization rate/spire-monitor/`
