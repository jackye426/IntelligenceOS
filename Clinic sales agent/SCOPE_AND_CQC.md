# Clinic sales scope → CQC matching

## How they fit together

```
input_urls.csv  (specialty × Harley Street × distance × pages)
        │
        ▼
Doctify listing scrape  →  practice profile URLs + name/address/website
        │
        ▼  (per clinic)
CQC directory LOOKUP  →  location id / RM / nominated individual
        │
        ▼  (optional, gtm-pipeline)
CQC location page scrape  →  registered since, specialisms, who-runs
```

## CQC: lookup, not live pull-all

1. **Once per process (refresh every 7 days):** download the public England CQC directory CSV (~18 MB) from the CQC transparency page into `Clinic sales agent/output/cqc_directory.csv`.
2. **Per clinic:** match Doctify `clinic_name` + `location` (postcode) against that local CSV — in-memory lookup, not an API crawl of every CQC location.
3. **Fallbacks (wired in):** if postcode/geo name match fails → **name-only** across the directory (exact / contains / strict multi-token overlap); also try **website hostname** against the CQC website field. Confidence labels: `exact` | `fuzzy` | `name_only` | `website` | `name_website`.
4. **On match:** HTTP-scrape **that one** CQC location Overview page for Registered Manager / Nominated Individual.

So we pull the **directory once**, then **look up** each Doctify clinic. We do **not** scrape every CQC location in England.

`gtm-pipeline cqc match` uses the same directory file with numeric `match_confidence`, always includes a name-narrowed pool, and adds a website-host pool when a URL is provided.

## Scope knobs (Clinic sales agent)

| Input | Role |
|-------|------|
| `input_urls.csv` | Specialty listing URLs + page counts |
| `--start-url` / `--pages` | Override for a sample specialty |
| `--append` | Skip `doctify_profile_url`s already in the output CSV |
| `--scrape-only` | Discovery + profile scrape only (no LLM) |
| `--cqc` / `--cqc-only` | Directory lookup + location page roles |

## Sample check (2026-07-14)

Endometriosis Harley Street, 1 page → 10 clinics; CQC on top 5 → **4/5 matched** (Claire Mellon `NOT_FOUND`).  
`gtm-pipeline` matched London Gynaecology Moorgate at confidence **1.0** (`1-8616190725`).
