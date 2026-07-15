# Execution Plan — GTM Account Intelligence

**Status:** P0 complete (backfill); P1 segment + P2 LinkedIn find-only implemented  
**Package:** `gtm-pipeline/`  
**Schema:** `sql/009_gtm_account_intelligence.sql` → `010` durable jobs → `011` outreach cohorts

This plan is the source of truth for DocMap GTM Account Intelligence inside the Intelligence OS monorepo.

---

## Goal

Build clinic-level GTM intelligence (size, CQC, founders/owners, evidence) with Supabase as the system of record from day one — replacing CSV-first enrichment in `Clinic sales agent/` for new work.

## Phases

| Phase | Scope | Status |
|-------|--------|----------|
| **P0** | Schema, shared match utils, Doctify extract, owner discovery, CQC directory + location, Supabase sync, tests | Done (~1512 Playwright clinics) |
| **P1** | Outreach segments + contact prepare + **`gtm_outreach_contacts`** (one PIC/clinic) | Done |
| **P2** | RocketReach + LinkedIn find for **everyone** on contacts (no send) | Done |
| P3 | Outreach send + Next.js review UI | Out of scope |

---

## 1.5 Schema (P0)

### `gtm_clinic_intelligence`
FK to `clinic_accounts` (nullable until linked). Doctify URL, size (`visible_clinic_size`), CQC fields, founder score, structure, evidence JSONB, provenance.

### `gtm_clinic_people`
People on a clinic: roles, specialty, priority, reasons, optional email, evidence/provenance.

### `gtm_match_reviews`
Ambiguous matches with confidence in `[0.50, 0.80)` for human review.

### `gtm_unmatched_owners`
Owner-first hits with **no clinic link yet**. **Keep email.** Upsert on `practitioner_id`. Never drop.

RLS enabled with authenticated SELECT + `service_role` ALL (service-role-friendly).

---

## P0 lanes

### Shared utilities
- `normalise_postcode` / `parse_address`
- `normalise_name` (strip Ltd / clinic / centre …)
- `match_confidence(candidate, target)` — phone 50% / name 30% / geo 20% when phone present; else name 80% / geo 20%
- Provenance + evidence helpers

### P0a — Doctify
Locked selectors:
- `[data-testid="specialist-link"]` → listed count (“N specialists”)
- `[data-testid="specialist-card"]` / `specialist-name` / `specialist-specialty`
- Dismiss CMP (AGREE); click “Load more specialists” until cards == listed count
- Fixture: `https://www.doctify.com/uk/practice/london-gynaecology-harley-street#specialists` (~25)

### P0a-owners
Scan `integrated_practitioners.about` for leadership keywords. Matched → attach evidence; unmatched → `gtm_unmatched_owners`.

### P0b — CQC
- Directory match with numeric confidence + multi-candidate
- Location Overview HTML (registered since, specialisms, who-runs)
- Fixture: `https://www.cqc.org.uk/location/1-19271937885` (Luna)
- Optional CQC Public API client if `CQC_API_KEY` set

### Sync
Every successful extract upserts Supabase (`--dry-run` when no credentials). Optional/create `clinic_accounts` by Doctify URL / name where appropriate.

---

## Constraints

- Do not modify unrelated marketing / TikTok / MCP code
- Do not delete `Clinic sales agent/`
- LinkedIn is find-only (no connect/InMail/send); P3 send stays out
- No secrets in git

## Done criteria (P0)

1. `pip install -e ./gtm-pipeline` works  
2. SQL migration present  
3. Doctify extract works on fixture / solid offline test + live smoke script  
4. CQC Luna parse works  
5. Supabase upsert path implemented (dry-run without credentials)  
6. Owner discovery writes unmatched to schema  
7. README + shared match/address tests  

## Done criteria (P1 segment + P2 find)

1. `sql/011_gtm_outreach_segments.sql` applied; cohorts seedable  
2. `segments refresh` / `list` CLI + `/segments/*` Railway routes  
3. `contacts prepare` rematch + people enrich on a cohort  
4. `contacts linkedin-find` durable; stores `linkedin_url` only (no clinic specialty overwrite)  
5. Smoke metrics documented in `gtm-pipeline/SCOPE_AND_CQC.md`  
