# gtm-pipeline

GTM Account Intelligence for DocMap Intelligence OS (P0).

Extracts clinic structure from Doctify, matches/enriches via CQC, discovers owner signals from practitioner bios, and upserts into Supabase `gtm_*` tables from day one.

Plan: [`docs/EXECUTION_PLAN_GTM_ACCOUNT_INTELLIGENCE.md`](../docs/EXECUTION_PLAN_GTM_ACCOUNT_INTELLIGENCE.md)

## Setup

```bash
pip install -e "./gtm-pipeline[dev]"
playwright install chromium   # required for live Doctify extract
```

Env (from repo root `.env.local` / `.env`):

| Variable | Purpose |
|----------|---------|
| `SUPABASE_URL` / `NEXT_PUBLIC_SUPABASE_URL` | Supabase project URL |
| `SUPABASE_SERVICE_ROLE_KEY` / `SUPABASE_KEY` | Service-role writes to `gtm_*` |
| `CQC_DIRECTORY_PATH` | Optional override for CQC directory CSV |
| `CQC_API_KEY` | Optional CQC Public API (stub client) |

Apply schema: run `sql/009_gtm_account_intelligence.sql`, then `sql/010_gtm_durable_jobs.sql`,
then `sql/011_gtm_outreach_segments.sql` in the Supabase SQL editor.

## CLI

```bash
# Doctify practice extract (live Playwright)
python -m gtm_pipeline doctify extract \
  --url 'https://www.doctify.com/uk/practice/london-gynaecology-harley-street#specialists' \
  --dry-run

# Upsert when credentials are present
python -m gtm_pipeline doctify extract --url <url> --upsert

# Offline HTML fixture
python -m gtm_pipeline doctify extract --html path/to/page.html --url <url> --dry-run

# Owner discovery (unmatched → gtm_unmatched_owners)
python -m gtm_pipeline owners scan --dry-run
python -m gtm_pipeline owners scan --limit 200

# CQC directory match
python -m gtm_pipeline cqc match --name 'The Luna Clinic' --postcode 'W1G 9PF'

# CQC location Overview (Luna fixture URL)
python -m gtm_pipeline cqc location --url 'https://www.cqc.org.uk/location/1-19271937885'
python -m gtm_pipeline cqc location --html gtm-pipeline/tests/fixtures/cqc_luna_1-19271937885.html \
  --url 'https://www.cqc.org.uk/location/1-19271937885'
```

### Live Doctify smoke

```bash
bash gtm-pipeline/scripts/smoke_doctify_live.sh
```

Expect ~25 specialists after “Load more specialists” on the London Gynaecology fixture.

## Tests

```bash
pytest gtm-pipeline/tests -q
```

CI-friendly coverage:

- address / name / `match_confidence` unit tests
- offline Doctify locked-selector HTML parse
- offline CQC Luna Overview parse

Live Doctify scrape is **not** required for CI.

## Package layout

```
gtm-pipeline/src/gtm_pipeline/
  doctify/           # P0a Playwright extract
  cqc_directory/     # P0b directory match (numeric confidence)
  cqc_location/      # P0b Overview HTML scrape
  cqc_api/           # optional API stub
  companies_house/   # stub
  owner_discovery/   # P0a-owners
  person_resolve/    # stub
  scoring/           # size + founder score + leadership keywords
  segments/          # outreach cohorts (size × specialty)
  contacts/          # CQC rematch + people enrich for cohorts
  linkedin/          # find-only profile URL (no send)
  sync/              # Supabase upserts
  shared/            # address, name, match_confidence, provenance
```

## Segments + outreach contacts

Cohorts prioritize batches. **Sales surface** is `gtm_outreach_contacts` (one PIC/clinic).

```bash
python -m gtm_pipeline contacts refresh-outreach
python -m gtm_pipeline contacts rocketreach --limit 20
python -m gtm_pipeline contacts linkedin-find --limit 20
python -m gtm_pipeline contacts list --ready-sales
```

Loop: CQC PIC → materialize → RocketReach **and** LinkedIn for everyone → export ready.
Clinic profile stays Doctify/CQC; enrichers never overwrite specialties/size/bio.

See [`SCOPE_AND_CQC.md`](SCOPE_AND_CQC.md).

## Doctify scope → extract → CQC (gtm-pipeline only)

**Do not call** `Clinic sales agent/` from GTM runners. Scope CSV is listing URLs only
(`gtm-pipeline/config/doctify_scope.csv`). Practice enrichment uses Playwright extract;
CQC uses `gtm_pipeline.cqc_directory` + `cqc_location`.

```bash
# Listing discovery
python -m gtm_pipeline doctify discover --scope gtm-pipeline/config/doctify_scope.csv --limit 20 --out stubs.json

# Batch re-extract existing Supabase URLs (priority: email / CQC / score>=40)
python -m gtm_pipeline doctify extract-batch --from-supabase --priority --limit 20 --upsert --cqc

# Orchestrated sample (listing → extract → optional CQC)
python gtm-pipeline/scripts/run_scoped_discovery.py \
  --start-url 'https://www.doctify.com/uk/find/endometriosis/harley-street/practices#distance=10' \
  --pages 1 --limit 5 --upsert --cqc

# Full Harley Street specialty scope
python gtm-pipeline/scripts/run_scoped_discovery.py --full --upsert --cqc
```

`gtm-pipeline cqc match` uses `CQC_DIRECTORY_PATH` (directory CSV may still live under
Clinic sales `output/` as a **data artifact** only) with numeric confidence, name-narrowed
pool, and website-host pool.

## Railway service

Separate scrape service on the **IntelligenceOS** Railway project (`gtm-pipeline`).

```bash
# from gtm-pipeline/
railway up --service gtm-pipeline --detach -m "gtm-pipeline scrape service"
```

Endpoints (auth: `Authorization: Bearer $GTM_SERVICE_TOKEN`):

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/health` | Liveness (no auth) |
| GET | `/jobs` / `/jobs/{id}` | Poll job status (durable Supabase + in-memory) |
| POST | `/jobs/{id}/resume` | Re-attach worker to durable job after restart |
| GET | `/match-reviews/pending` | Ambiguous matches flagged for outreach review |
| POST | `/doctify/extract` | Single practice extract (+ optional upsert) |
| POST | `/doctify/discover` | Listing → practice URL stubs (default background) |
| POST | `/doctify/extract-batch` | Durable parallel batch extract (default) |
| POST | `/pipeline/scoped-run` | E2E: discover → extract → CQC (or supabase backfill) |
| POST | `/owners/scan` | Owner discovery scan |
| POST | `/cqc/refresh-directory` | Download/refresh national CQC directory CSV |
| POST | `/cqc/match` | CQC directory match |
| POST | `/cqc/location` | CQC location Overview scrape |
| POST | `/segments/refresh` | Rebuild outreach cohort membership |
| GET | `/segments` / `/segments/{slug}/members` | List cohorts / members |
| POST | `/contacts/prepare` | CQC rematch + people enrich for a cohort |
| POST | `/contacts/refresh-outreach` | Materialize PIC outreach contacts (no network) |
| POST | `/contacts/rocketreach` | RocketReach enrich (durable; everyone) |
| POST | `/contacts/linkedin-find` | LinkedIn find-only (durable; everyone missing URL) |
| GET | `/contacts/outreach` | List / `ready_sales=true` handoff |

Long runs default to **background jobs** (`background: true`). Response includes `job_id`;
poll `GET /jobs/{id}` until `status` is `completed` or `failed`.

Trigger examples (after deploy):

```bash
BASE=https://gtm-pipeline-production-ed6f.up.railway.app
AUTH="Authorization: Bearer $GTM_SERVICE_TOKEN"

# Priority backfill of existing Supabase URLs (Playwright + CQC)
curl -sS -X POST "$BASE/pipeline/scoped-run" -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"from_supabase":true,"priority":true,"discover_limit":20,"cqc":true,"upsert":true}'

# Or extract-batch only
curl -sS -X POST "$BASE/doctify/extract-batch" -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"from_supabase":true,"priority":true,"limit":20,"upsert":true,"cqc":true}'

# Sample listing discover (1 page worth via limit)
curl -sS -X POST "$BASE/doctify/discover" -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"start_url":"https://www.doctify.com/uk/find/endometriosis/harley-street/practices#distance=10","pages":1,"limit":10}'
```

CQC directory auto-refreshes on startup when missing/stale (`CQC_DIRECTORY_AUTO_REFRESH`,
`CQC_DIRECTORY_MAX_AGE_DAYS`). File lives under `GTM_DATA_DIR` (Railway: `/tmp/gtm-data`).
Scope CSV is baked into the image at `config/doctify_scope.csv`.

Required env: `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `GTM_SERVICE_TOKEN`.

Local HTTP:

```bash
pip install -e "./gtm-pipeline[service]"
uvicorn gtm_pipeline.service:app --reload --port 8080
```

### Sync / recover

```bash
# Prefer Playwright batch over legacy CSV sync
python -m gtm_pipeline doctify extract-batch --from-supabase --priority --upsert --cqc

# Legacy: upsert old OG scoped CSV (seed only — not the ongoing path)
python -m gtm_pipeline sync scoped-csv --path gtm-pipeline/data/full_scope_run.csv --limit 20 --dry-run

# Match CQC RM/NI to practitioners
python -m gtm_pipeline people match-cqc \
  --nominated-individual "Dr Bassel Hamameeh Al Wattar"
```

## Notes

- Do **not** commit secrets; upserts no-op / dry-run when credentials are missing.
- `Clinic sales agent/` remains legacy — this package replaces CSV-first enrichment for GTM.
- Auto-send / sequencing (P3) stays out of scope. LinkedIn here is **find-only**.
