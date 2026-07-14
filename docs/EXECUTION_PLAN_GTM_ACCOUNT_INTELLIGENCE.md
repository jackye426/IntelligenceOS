# GTM Account Intelligence — Execution Plan

**Created:** 2026-07-14  
**Status:** Draft — ready to implement P0  
**Repo home:** Intelligence OS (monorepo package; not standalone)  
**Companion sources:** `Clinic sales agent/` (legacy), [synaptic-docmap/GTM_B2B](https://github.com/synaptic-docmap/GTM_B2B) (reusable algorithms), `ingestion-pipeline/`

---

## Objective

Turn each Doctify clinic into a **defensible account record** that answers:

1. How large and commercially relevant is the clinic?
2. What is its operating structure?
3. Is it likely founder-led?
4. Who is the most relevant person to contact?
5. Should DocMap approach the founder, registered manager, clinic manager, or a group-level executive?

**MVP output is not an email list.** It is an evidence-backed account record:

```json
{
  "clinic_type": "clinician-founder boutique clinic",
  "founder_led_score": 84,
  "primary_target": "Founder-clinician",
  "secondary_target": "Registered manager",
  "reason": "The CQC nominated individual and registered manager match the principal consultant listed on Doctify.",
  "recommended_channel": "email_plus_linkedin"
}
```

---

## What we keep (good parts)

### From the original GTM refinement plan

| Keep | Why |
|------|-----|
| Account intelligence before outreach | Prevents empty personalisation and wrong contacts |
| Doctify → CQC → people → structure → contact strategy | Correct dependency order |
| Transparent founder-led scoring (rules + evidence) | Auditable; human-reviewable |
| Operating structure classifier driving outreach | Strategy, not just a name |
| Buying committee (up to 3 roles) | Matches how clinics buy |
| Human review before enrichment/send | Safety + model improvement loop |
| Outcome tracking by role / structure / channel | Learning system later |
| Gold-set MVP on 50–100 clinics | Measurable quality gate |

### From live scrape research (locked targets)

| Keep | Why |
|------|-----|
| Doctify `data-testid` specialist contracts | Stable DOM; ignore hashed CSS |
| `specialist-link` = **count** (“25 specialists”); cards = people | Avoid wrong selector |
| Load-more until `len(cards) == count` | Otherwise undercount size + miss person match |
| CQC Overview: registered since, specialisms, who-runs | Exact Luna fields |
| CQC directory CSV/API for IDs, phone, website, provider | Better match signals than page alone |
| Explicit NOT_REGULATED / ambiguous / review queue | Many Doctify listings are not CQC clinics |

### From GTM_B2B (port algorithms, not the stack)

| Keep / port | Why |
|-------------|-----|
| CQC **Public API** for provider firmographics | Durable vs HTML for rating, phone, website, status |
| `matchConfidence` (phone + name + geo weights) | Proven fuzzy join for contact↔registry |
| `mergeRecord` authority rules (registry vs contact sources) | Prevents Maps/directory overwriting firmographics |
| UK `normalisePostcode` / `parseAddress` | Shared geo hygiene |
| Companies House + **director enrichment** | Ownership/founder signal once provider Ltd known |
| Provenance: `sources[]` + `sourceMatchConfidence` | Every field explainable |
| Women’s health keyword filters (`cqc-filters.json`) | Ready specialty targeting |
| BSGE / POGP directory pattern | Later seed source (P1+) |
| `NEEDS_CONFIRM` review queue for low-confidence joins | Same pattern as CQC match review |

### From Intelligence OS (do not reinvent)

| Keep | Why |
|------|-----|
| Live in this monorepo as `gtm-pipeline/` | Same Supabase, app, outreach history |
| Ingestion lane contract (stage → sync → log) | Matches `ingestion-pipeline` |
| Strangle `Clinic sales agent/` lane-by-lane | Don’t harden the CSV script pile in place |
| `clinic_accounts` / `clinic_contacts` as consumers | UI already exists |
| Doctors Sales Agent name-match ideas (rapidfuzz) | Reuse for CQC↔Doctify people |
| `integrated_practitioners.about` bios (~40k rows; ~1.4k leadership-keyword hits) | Owner/founder discovery pass + per-clinic evidence |

---

## What we discard or defer

| Item | Decision |
|------|----------|
| Airtable as store of record (GTM_B2B) | Discard — Supabase is canonical |
| Apify-only runtime as requirement | Defer — Python/Playwright worker first; Apify optional later |
| Provider-only CQC ingest as full CQC solution | Discard — we need **location** RM/NI |
| Hard global “80% of all Doctify → CQC” | Replace — denominator = likely-regulated England clinics |
| Outreach / LinkedIn automation in P0 | Defer to P2; LinkedIn research stays manual-approval |
| Rewriting marketing-pipeline / MCP for GTM | Out of scope |

---

## Architecture decisions (locked)

| # | Decision | Choice |
|---|----------|--------|
| 1 | Repo | **In Intelligence OS** as new package `gtm-pipeline/` |
| 2 | Legacy | `Clinic sales agent/` is reference only; freeze behaviour; delete after parity |
| 3 | Stack | Python primary (align with ingestion + existing scrapers); port TS algorithms from GTM_B2B |
| 4 | Store | **Supabase from day one** — not CSV as system of record |
| 5 | Identity keys | `doctify_url` → `cqc_location_id` → `cqc_provider_id` → `companies_house_number` |
| 6 | CQC data | Directory/API for match + firmographics; **location HTML** for RM/NI + registered since |
| 7 | Heavy scrape | Local / Railway worker (not Vercel) |
| 8 | GTM_B2B | Sister repo for registry discovery; sync ideas/code, not Airtable writes |
| 9 | Unmatched owners | Keep in dedicated table with email — never drop |

```text
Intelligence OS/
├── gtm-pipeline/                 # NEW — scrape, match, score, upsert
│   ├── lanes/
│   │   ├── doctify/
│   │   ├── cqc_directory/
│   │   ├── cqc_location/
│   │   ├── cqc_api/              # ported from GTM_B2B
│   │   ├── companies_house/      # ported from GTM_B2B
│   │   ├── owner_discovery/      # integrated_practitioners leadership scan
│   │   └── person_resolve/
│   ├── scoring/
│   ├── sync/                     # Supabase upserts (authoritative writes)
│   └── shared/
├── sql/                          # NEW: gtm_* schema migrations
├── Clinic sales agent/           # LEGACY CSV — reference only
└── app/                          # review UI later (P1)
```

**Write path (locked):**

```text
Scrape / enrich
  → optional local staging JSONL (debug/replay only)
  → upsert Supabase (canonical)
  → CSV export optional, read-only, never the agent’s source of truth
```

Core flow:

```text
Doctify clinic
  → specialist roster + size + leadership keywords
  → upsert clinic_accounts + gtm_clinic_intelligence
  → CQC match + location Overview + API / CH
  → person match + founder score + buying committee
  → upsert clinic_contacts + evidence

Parallel: owner-first scan of integrated_practitioners
  → matched → attach to clinic
  → unmatched → upsert gtm_unmatched_owners (keep email for later)
```

---

## Phase 0 — Gold set and scrape contracts (gate)

Before building at scale, freeze fixtures:

| Fixture | URL / ID | Validates |
|---------|----------|-----------|
| London Gynaecology – Harley Street | Doctify practice + `#specialists` | Count=25, load-more, card testids |
| The Luna Clinic | CQC `1-19271937885` | Registered since, specialisms, RM=NI, provider BBH… |
| 48–98 more hand-labelled clinics | mix of solo / boutique / group / NHS private | Website correctness, CQC match, NOT_REGULATED |

**Gate:** parsers pass fixtures before P1 enrichment work.

---

## Phase 1 — Doctify clinic profile (P0a)

### 1.1 Extract clinic

```json
{
  "clinic_name": "",
  "doctify_url": "",
  "website_url": "",
  "website_class": "own_domain|parent_group|booking_platform|social|missing|unknown",
  "clinic_bio": "",
  "address": "",
  "postcode": "",
  "locations": [],
  "specialties": [],
  "areas_of_expertise": [],
  "listed_specialists": [],
  "listed_specialist_count": 0,
  "review_count": 0,
  "phone": "",
  "generic_email": ""
}
```

### 1.2 Specialist roster (locked selectors)

| Field | Source |
|-------|--------|
| Count | `[data-testid="specialist-link"]` text → e.g. `25 specialists` |
| Cards | `[data-testid="specialist-card"]` inside `[data-testid="specialists-section"]` |
| Name + URL | `[data-testid="specialist-name"]` → `/uk/specialist/{slug}` |
| Specialty | `[data-testid="specialist-specialty"]` |
| Reviews / trust | parse card text |
| Position | order after popularity sort (default) |

**Must:** dismiss cookie CMP; click **Load more specialists** until `len(cards) == listed_specialist_count`.

```json
{
  "name": "Mr Narendra Pisal",
  "title": "Obstetrician & Gynaecologist",
  "specialty": "Obstetrician & Gynaecologist",
  "profile_url": "https://www.doctify.com/uk/specialist/mr-narendra-pisal",
  "review_count": 350,
  "trust_score": 4.99,
  "position_on_page": 0
}
```

### 1.3 Visible clinic size

Do not treat specialist count as employee count.

| Classification | Heuristic |
|----------------|-----------|
| Solo practice | 1 specialist, 1 location |
| Micro clinic | 2–5 specialists |
| Boutique clinic | 6–15 |
| Established clinic | 16–40 |
| Clinic group | Multiple locations or >40 specialists |

Store classification + `size_confidence` + `size_evidence`.

### 1.4 Leadership keyword scan

**Sources:**

1. **Doctify clinic bio** — clinic-brand claims (“founded by…”, “our medical director…”)
2. **Doctify specialist cards / profiles** — when scraped in P0a
3. **`integrated_practitioners.about`** (~24k bios; ~1.4k already contain leadership language)

Keywords: Founder, Co-founder, Owner, Medical director, Clinical director, Managing director, Clinic director, Lead consultant, Established by, Founded by.

**Two valid passes (do both; neither requires the other as a hard prerequisite):**

| Pass | Flow | Use when |
|------|------|----------|
| **A. Clinic-first** | For clinic X → linked specialists / CQC people → scan those bios | Enriching one Doctify account |
| **B. Owner-first** | Scan bios for leadership keywords → extract clinic/org if present → match to clinic → **always persist** (matched or unmatched table) | Bulk discovery; keep emails for later outreach |

Owner-first does **not** need a prior clinic match:

```text
bio leadership hit
  → parse clinic/org name from bio (if any)
  → match to Doctify / clinic_accounts / CQC provider
  → matched: attach evidence + boost founder-led score; link practitioner_id
  → unmatched: upsert gtm_unmatched_owners (keep email, snippet, keywords)
```

**Never drop unmatched hits.** They often have direct professional emails in `integrated_practitioners` — park them neatly for later matching or direct outreach once a clinic link appears.

Provenance: `source: integrated_practitioners`, with snippet + keyword hit.  
Clinic-page explicit claims still outweigh person-bio inference on conflicts.

### 1.5 Supabase schema (day one)

Canonical tables (new migration under `sql/`):

| Table | Role |
|-------|------|
| `gtm_clinic_intelligence` | Per-clinic account record: size, CQC match, founder score, structure, evidence JSONB; FK → `clinic_accounts` |
| `gtm_clinic_people` | Recommended / discovered people on a clinic (role, priority, reasons, LinkedIn/email later) |
| `gtm_match_reviews` | Ambiguous CQC / person matches below threshold |
| `gtm_unmatched_owners` | Owner-first hits with **no clinic link yet** |

`gtm_unmatched_owners` shape (neat, reusable later):

```json
{
  "practitioner_id": "uuid-or-text-key",
  "name": "",
  "email": "",
  "email_confidence": null,
  "phone": "",
  "specialty": "",
  "keyword_hits": ["founder"],
  "bio_snippet": "",
  "parsed_org_name": "",
  "match_status": "unmatched",
  "best_clinic_candidate_id": null,
  "best_match_confidence": null,
  "sources": ["integrated_practitioners"],
  "last_scanned_at": ""
}
```

Rules:

- Upsert on `practitioner_id` (idempotent re-scans)
- Preserve email even when org parse fails
- When a later clinic match succeeds → link into `gtm_clinic_people` and set `match_status=matched`
- Do not auto-email from this table without human review

### P0a acceptance

- Profile enrichment success rate measurable per clinic (not silent stubs)
- On gold set: ≥90% **correct** own website (or correctly classed parent/booking/missing)
- `len(listed_specialists) == listed_specialist_count` on gold set
- Leadership keywords extracted where present

---

## Phase 2 — CQC resolve (P0b)

### 2.1 Match hierarchy (evidence-backed)

Combine **Clinic sales agent lessons** + **GTM_B2B matchConfidence**:

1. Exact postcode  
2. Exact / high-similarity address  
3. Clinic name similarity (normalised; strip Ltd/clinic/centre noise — port GTM_B2B `normaliseName`)  
4. Website domain (Doctify **or** CQC directory website)  
5. Phone  
6. Provider name similarity  
7. Specialty / regulated activity compatibility  

Output:

```json
{
  "cqc_match_status": "matched|ambiguous|not_found|not_applicable",
  "cqc_match_confidence": 0.94,
  "cqc_match_reasons": ["Exact postcode match", "Clinic name similarity: 0.91"],
  "candidates": []
}
```

- Multi-candidate when uncertain  
- Manual review below **0.80**  
- Denominator for “80%” KPI = **likely-regulated** clinics only  

### 2.2 Data sources (two layers)

| Layer | Fields |
|-------|--------|
| **Directory / CQC API** | `cqc_location_id`, `cqc_provider_id`, name, address, postcode, phone, website, service types, provider name, rating, status |
| **Location Overview HTML** | `cqc_registered_since`, specialisms/services list, organisation “run by”, Registered Manager(s), Nominated Individual(s) |

Luna fixture (`1-19271937885`):

- Registered on **1 May 2024**  
- Specialisms: family planning, ToDDI, diagnostics, caring under/over 65  
- Run by **BBH Medical Solutions Ltd** (`1-17077603369`)  
- RM = NI = **Dr Bassel Hamameeh Al Wattar**  

### 2.3 Operating entity

```json
{
  "public_brand": "",
  "regulated_location": "",
  "regulated_provider": "",
  "possible_parent_group": null,
  "cqc_registration_tenure_years": null,
  "active_cqc_location_count": null
}
```

Provider page / directory related locations → `active_cqc_location_count`.

### 2.4 Companies House (from GTM_B2B)

Once `regulated_provider` known:

- Resolve company number  
- Pull active directors → ownership / founder candidates  
- Store under provenance `source: companies-house`

### P0b acceptance

- Gold set: ≥80% **correct** CQC location among likely-regulated clinics  
- Every match has reasons + numeric confidence  
- Uncertain → review queue  
- RM/NI extracted where CQC publishes them  
- Provider ID + registered since present when matched  

---

## Phase 3 — People resolve

### 3.1 Name normalisation

Canonical form: strip Dr/Mr/Mrs/Miss/Ms/Prof; split first / middle / surname.

### 3.2 Match CQC people ↔ Doctify specialists

Evidence: exact first+surname, middle/initial, specialty, same clinic, bio overlap.  
Reject common-name matches without supporting evidence.  
Reuse Doctors agent rapidfuzz + GTM_B2B confidence pattern.

Classify unmatched CQC people: clinician-manager, non-clinical RM, senior provider rep, possible founder, group executive, unresolved.

---

## Phase 4 — Operating structure

### 4.1 Founder-led score (rules)

**Positive:** explicit founder wording (+35); NI on Doctify (+30); RM on Doctify (+20); principal/only specialist (+15); surname in brand (+15); multiple CQC roles (+10); ≤5 specialists / 1 location (+10); bio centres one clinician (+10).

**Negative:** >3 CQC locations (−15); >20 specialists (−10); several RMs (−10); NI is parent-group (−20); hospital setting (−15); explicit corporate ownership (−25).

Bands: 70–100 strongly founder-led; 45–69 probably; 25–44 unclear; 0–24 professionally managed / group.

### 4.2 Structure labels

```text
Solo clinician practice
Clinician-founder boutique clinic
Clinician-led clinic with professional management
Manager-operated independent clinic
Multi-site independent clinic group
Corporate healthcare group
Consultant practice inside another provider
Unclear
```

---

## Phase 5 — Contact strategy

Output up to three roles: `economic_buyer`, `operational_champion`, `clinical_influencer`.

Strategy by structure (founder-led / professionally managed / multi-site / hospital practice) as in original plan.

Rank: Authority 30%, Problem ownership 25%, DocMap relevance 20%, Activity 10%, Contactability 10%, Founder connection 5%.

Every recommendation includes a one-line **reason**.

---

## Phase 6 — Enrichment (P1)

- LinkedIn search queries + manual approval (no auto-connect)  
- Verified work email for top 2–3 people only  
- Channel selection: email / LinkedIn / both / find another DM  
- Reject guessed / unverified / catch-all / personal without validation  

---

## Phase 7 — Outreach (P2)

Personalisation object from specialisms, size, structure, role, clinic evidence, DocMap angle.  
No generic flattery.  
Reuse Gmail draft-only patterns from Doctors Sales Agent / MCP — never auto-send in v1.

---

## Phase 8 — Human review UI (P1)

Review screen: Clinic | CQC | Inference | Recommended contacts | Actions  
(Approve / Reject / Change role / Mark identity wrong / Request research / Generate email / Generate LinkedIn message).

Store feedback for scoring improvements.

---

## Phase 9 — Outcomes (P3)

Track contacted / channel / opened / replied / reply_type / meeting / pilot.  
Analyse by founder vs manager, size, structure, specialty, channel, score.  
Adjust weights from conversions and negatives.

---

## Implementation order

| Priority | Work | Depends on |
|----------|------|------------|
| **P0-schema** | Supabase migrations: `gtm_clinic_intelligence`, `gtm_clinic_people`, `gtm_match_reviews`, `gtm_unmatched_owners` | — |
| **P0a** | Doctify profile + specialists + size + leadership keywords → **upsert Supabase** | P0-schema + gold fixtures |
| **P0a-owners** | Owner-first scan → matched attach / unmatched → `gtm_unmatched_owners` | P0-schema |
| **P0b** | CQC match + location Overview + directory/API → upsert | P0a website/phone for match |
| **P0c** | Person match + founder score + structure + primary contact → upsert | P0a+P0b |
| **P1** | LinkedIn queries, email enrich, review UI, Companies House directors | P0c |
| **P2** | Outreach generation + history/suppression | P1 |
| **P3** | Outcome learning + weight tuning | P2 volume |

**Do not start P1–P3 until P0a + P0b pass gold-set gates.**  
**CSV is export-only from day one — agent reads/writes Supabase.**

---

## MVP acceptance (50–100 clinic gold set)

| Criterion | Target |
|-----------|--------|
| Correct website (or correctly classed) | ≥90% |
| Correct CQC location among likely-regulated | ≥80% |
| All CQC matches have evidence | 100% |
| RM/NI where published | Extracted |
| Founder-led class has visible evidence | 100% of scored |
| ≥1 plausible decision-maker | ≥70% |
| Verified professional email (P1) | ≥50% of selected DMs |
| Every target has selection reason | 100% |

---

## Shared modules to port from GTM_B2B

Implement in `gtm-pipeline/shared/` (Python):

1. `normalise_postcode` / `parse_address`  
2. `normalise_name` (UK clinic suffixes)  
3. `match_confidence(candidate, target)` — phone / name / geo weights  
4. `merge_record` — registry vs contact source authority  
5. CQC API client (`CQC_API_KEY`) — provider enrich  
6. Companies House client — company + officers  
7. Provenance envelope on every staged record  

Keep GTM_B2B for optional Apify/Airtable beachhead if product wants a separate CRM mirror; **Intelligence OS remains system of record for DocMap GTM.**

---

## Legacy cutover

1. Freeze `Clinic sales agent/` behaviour docs from current CSV.  
2. Ship `sql/` GTM tables; agent upserts Supabase on every successful extract.  
3. Optional staging JSONL for debug/replay only — not the store of record.  
4. Compare gold set vs old CSV for parity checks.  
5. Backfill / upsert `clinic_accounts` + contacts from GTM intelligence (replace insert-only P4 as GTM path).  
6. Delete or archive `Clinic sales agent/` after 2–4 weeks of live parity.

---

## Out of scope for this module

- TikTok / Instagram marketing pipeline  
- Patient WhatsApp privacy lanes  
- Automated LinkedIn connection sending  
- Cold-email blast infrastructure  
- Replacing Relationship Desk MCP  

---

## Immediate next steps

1. Create `gtm-pipeline/` package skeleton + shared address/match ports.  
2. Add Supabase SQL migration for GTM tables (including `gtm_unmatched_owners`).  
3. Implement Doctify specialist extract → **upsert** against London Gynaecology fixture.  
4. Implement owner-first scan → matched / `gtm_unmatched_owners`.  
5. Implement CQC location Overview + directory match against Luna fixture → upsert.  
6. Label remaining gold-set clinics.  
7. Only then: person match + founder score.

---

*Data sources: Doctify (public practice pages), CQC register / Public API / location pages, Companies House. Internal use for DocMap B2B targeting; honour opt-outs; no auto-send.*
