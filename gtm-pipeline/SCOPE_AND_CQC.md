# Scope + CQC (gtm-pipeline only)

## Locked rule

- GTM discovery, extract, CQC match/location, and Supabase sync run through **`gtm-pipeline` only**.
- Do **not** call `Clinic sales agent/src/main.py`, `doctify_scraper.py`, or `cqc_lookup.py` from GTM scripts, CLI, or Railway.
- `Clinic sales agent/` may remain on disk as legacy; GTM runners must not import or subprocess it.

## Scope (listing URLs)

- Source of truth for listing URLs: `gtm-pipeline/config/doctify_scope.csv`
  (same shape as Clinic sales `input_urls.csv`: `url,pages`).
- CLI: `python -m gtm_pipeline doctify discover --scope gtm-pipeline/config/doctify_scope.csv`
- Listing only — no practice profile / contact scrape (that is `doctify extract`).

## Practice extract

- Single: `python -m gtm_pipeline doctify extract --url … --upsert`
- Batch (recover OG-seeded rows):  
  `python -m gtm_pipeline doctify extract-batch --from-supabase --priority --upsert`
- Provenance on success: `source=doctify`, `extractor=playwright_practice_v1`
- Upsert preserves existing CQC columns unless `--refresh-cqc`

## CQC

- Directory match: `gtm_pipeline.cqc_directory` against official `CQC_directory.csv`
- Auto-refresh: downloads from CQC transparency page if missing or older than
  `CQC_DIRECTORY_MAX_AGE_DAYS` (default 7). On Railway, runs at service startup
  (`CQC_DIRECTORY_AUTO_REFRESH=1`) and via `POST /cqc/refresh-directory`.
- CLI: `python -m gtm_pipeline cqc refresh-directory [--force]`
- Default path: `$GTM_DATA_DIR/cqc_directory.csv` (no dependency on Clinic sales)
- Location Overview: `gtm_pipeline.cqc_location`
- Wired into extract-batch / scoped runner via `--cqc` / `--refresh-cqc`

## Orchestrator

`gtm-pipeline/scripts/run_scoped_discovery.py` — listing → extract → optional CQC.
Hard-fails if argv or paths reference Clinic sales agent.

Railway (preferred trigger):

- `POST /pipeline/scoped-run` — E2E job (`from_supabase: true` for backfill, or discover from scope)
- `POST /doctify/discover` / `POST /doctify/extract-batch` (durable + parallel by default)
- Poll `GET /jobs/{id}`; resume after restart with `POST /jobs/{id}/resume`
- Ambiguous CQC/person matches → `gtm_match_reviews` (`GET /match-reviews/pending`)

Apply `sql/010_gtm_durable_jobs.sql` in Supabase before durable jobs work (falls back to in-memory otherwise).

## Segmentation + contact enrichment (P1 / P2)

Clinic profile for cohorts comes from **existing Doctify extract** (`specialties`,
`visible_clinic_size`, people). Do **not** use LinkedIn/RocketReach to rediscover services.

Schema: `sql/011_gtm_outreach_segments.sql` → cohorts; `sql/012_gtm_outreach_contacts.sql`
→ **one PIC contact per clinic** (`gtm_outreach_contacts`).

### Simple loop (production)

1. **CQC PIC** — nominated individual → registered manager → founder/high-priority  
2. **Materialize** `gtm_outreach_contacts` (copy any existing email/LinkedIn)  
3. **RocketReach for everyone** (store `rocketreach_email`; prefer existing email for `preferred_channel`)  
4. **LinkedIn for everyone** missing a URL (even if email exists)  
5. **Export** `status=ready` for Doctors Sales handoff  

```bash
# Build ~734+ CQC-named PIC rows (no network)
python -m gtm_pipeline contacts refresh-outreach

# Optional cohort-scoped first batch
python -m gtm_pipeline contacts refresh-outreach --cohort solo_og_fertility

# RocketReach (noop without ROCKETREACH_API_KEY / GTM_ROCKETREACH_MODE=noop)
python -m gtm_pipeline contacts rocketreach --limit 20 --sync --dry-run
python -m gtm_pipeline contacts rocketreach --cohort solo_og_fertility --limit 50

# LinkedIn find for residual / all missing URLs
python -m gtm_pipeline contacts linkedin-find --limit 20

# Sales handoff
python -m gtm_pipeline contacts list --ready-sales --limit 100
```

Railway:

- `POST /contacts/refresh-outreach`
- `POST /contacts/rocketreach` / `POST /contacts/linkedin-find` (durable)
- `GET /contacts/outreach?ready_sales=true`

Seed cohorts: `solo_og_fertility`, `small_derm`, `needs_contact_priority` (batch filters only).

### Smoke metrics

| Metric | Target |
|--------|--------|
| `contacts refresh-outreach` (CQC-named) | ~734+ rows, no network, &lt;1 min |
| Rows with email | `preferred_channel=email`; still eligible for RR+LI |
| LinkedIn / RR | Attempt for contacts missing that channel data |
| Auto-sends | **0** |