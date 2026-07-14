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

Apply schema: run `sql/009_gtm_account_intelligence.sql` in the Supabase SQL editor.

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
  sync/              # Supabase upserts
  shared/            # address, name, match_confidence, provenance
```

## Doctify scope → CQC (Clinic sales agent)

Clinic discovery still uses **Clinic sales agent** listing URLs (`input_urls.csv`). CQC is a **per-clinic lookup** against a cached national directory CSV (not a live “download all CQC then join” each run):

1. Scrape Doctify listings → practice rows (name, location, website, profile URL)
2. Match each row into `output/cqc_directory.csv` by name + postcode/address
3. Scrape the matched CQC location page for Registered Manager / Nominated Individual

```bash
# Sample (1 listing page)
python gtm-pipeline/scripts/run_scoped_discovery.py \
  --start-url 'https://www.doctify.com/uk/find/endometriosis/harley-street/practices#distance=10' \
  --pages 1

# Full Harley Street specialty scope from input_urls.csv
python gtm-pipeline/scripts/run_scoped_discovery.py --full
```

`gtm-pipeline cqc match` uses the same directory file (`CQC_DIRECTORY_PATH`) with numeric confidence.

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
| POST | `/doctify/extract` | Live Playwright Doctify extract (+ optional upsert) |
| POST | `/owners/scan` | Owner discovery scan |
| POST | `/cqc/match` | CQC directory match |
| POST | `/cqc/location` | CQC location Overview scrape |

Required env: `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `GTM_SERVICE_TOKEN`.

Local HTTP:

```bash
pip install -e "./gtm-pipeline[service]"
uvicorn gtm_pipeline.service:app --reload --port 8080
```

## Notes

- Do **not** commit secrets; upserts no-op / dry-run when credentials are missing.
- `Clinic sales agent/` remains legacy — this package replaces CSV-first enrichment for GTM.
- P1–P3 (LinkedIn, outreach send, Next.js review UI) are intentionally out of scope here.
