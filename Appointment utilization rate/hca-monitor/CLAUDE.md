# HCA Appointment Availability Monitor

Playwright-based scraper that tracks publicly visible appointment slots on HCA Healthcare UK's
consultant booking flow. Stores slot lifecycle data to compute appointment utilisation metrics.
Compliant: public pages only, no login, no patient details, no booking holds.

---

## What it does

1. Navigates the HCA booking flow for each configured consultant
2. For each appointment type (initial / follow-up) × each booking-flow location, intercepts
   the `GetLDBConsultantSlots` API call that HCA fires on page load
3. Replays that API call for every week in the 60-day lookahead window (~10 API calls per
   location per appointment type, no UI interaction beyond initial navigation)
4. Merges initial and follow-up records into a single row per physical slot time, with
   `available_for_initial` and `available_for_follow_up` boolean flags
5. Persists slot lifecycle (first seen, last seen, disappeared, expired) to SQLite
6. Run 3× per day; over time the disappearance of slots indicates bookings, enabling
   utilisation rate calculation at T-21d / T-14d / T-7d / T-3d / T-48h windows

---

## Entry points

| Command | Purpose |
|---------|---------|
| `python run_once.py` | Single end-to-end scrape run |
| `python run_once.py --trace` | Same + writes a Playwright trace zip to `logs/` for debugging |
| `python scheduler.py` | Continuous 3×/day runner (07:00 / 13:00 / 19:00 Europe/London) |
| `python scheduler.py --test-interval 2` | Same but fires every 2 minutes — useful for validating cadence |
| `python -m analysis.capacity_benchmark` | Print three-layer private outpatient footprint report to stdout |
| `python -m reports.renderer` | Render all HTML reports to `output/` (capacity benchmark + decay) |

---

## Configuration

All config lives in `.env` (copy `.env.example` to get started):

| Variable | Default | Description |
|----------|---------|-------------|
| `PLAYWRIGHT_HEADLESS` | `false` | Set `true` for unattended/server runs |
| `DB_PATH` | `data/hca_monitor.db` | SQLite file path |
| `LOG_LEVEL` | `INFO` | Python logging level |
| `MAX_LOOKAHEAD_DAYS` | `60` | How far ahead to scan for slots |
| `SLOW_MO_MS` | `200` | Playwright slow_mo (ms) — prevents race conditions |
| `SCREENSHOT_DIR` | `data/screenshots/` | Debug screenshot destination |

Consultants are configured in `config/settings.py` under `Settings.consultants`.

---

## Project structure

```
hca-monitor/
├── run_once.py               # Manual / cron single-run entry point
├── scheduler.py              # 3×/day continuous runner
├── config/
│   └── settings.py           # All config + constants
├── db/
│   ├── engine.py             # SQLAlchemy engine + session factory
│   ├── models.py             # ORM table definitions
│   └── migrations.py         # create_all() + in-place schema migration (v1→v2)
├── scraper/
│   ├── browser.py             # Playwright context manager
│   ├── profile_extractor.py   # Scrapes consultant profile page (name, locations, fees)
│   ├── booking_navigator.py   # Drives the multi-step HCA booking flow (browser path)
│   ├── direct_api_scraper.py  # Calls GetLDBConsultantSlots directly using stored GUIDs
│   ├── network_interceptor.py # Captures XHR/fetch responses, identifies slot API calls
│   ├── slot_extractor.py      # Parses GetLDBConsultantSlots JSON → SlotRecord list
│   ├── calendar_navigator.py  # Replays slot API for every week in lookahead window
│   └── screenshot_manager.py  # Saves debug screenshots to data/screenshots/
├── storage/
│   ├── slot_lifecycle.py     # INSERT new / UPDATE seen / mark disappeared or expired
│   ├── scrape_run.py         # Opens and closes scrape_run records
│   └── guid_store.py         # Stores and retrieves (consultantGUID, locationGUID) pairs
├── analysis/
│   ├── metrics.py                # Availability decay metrics at T-windows
│   ├── capacity_benchmark.py     # Three-layer theoretical capacity benchmark (CLI-runnable)
│   ├── hours_comparison.py       # Published hours vs observed online slots
│   └── dataframes.py             # Reusable pandas query helpers
├── reports/
│   └── renderer.py           # Jinja2 HTML report builder
├── data/
│   ├── hca_monitor.db        # SQLite database (gitignored)
│   └── screenshots/          # Debug screenshots (gitignored)
└── logs/                     # Scrape + scheduler logs (gitignored)
```

---

## Scraper flow (per consultant)

`run_once.py` routes each consultant to one of two paths based on whether their GUIDs are
already stored in `booking_guids`:

### Path A — Direct API (consultants with stored GUIDs)

```
T&C page load (domcontentloaded, no clicks) — sets Incapsula session cookie
  └── For each (location × funding_route) in booking_guids:
        └── For each appointment type (initial / follow-up):
              └── For each week in lookahead window:
                    └── GET GetLDBConsultantSlots?consultantGUID=…&locationGUID=…&dateFrom=…
                          └── Parse SlotRecord list
```

One lightweight page load per consultant; ~10 API calls per (location × appt type).
No `slow_mo`, no location card navigation, no calendar pagination UI.

### Path B — Full browser flow (new consultants, no stored GUIDs)

```
Profile page
  └── Click "Book online"
        └── Accept T&C
              └── Select appointment type (initial / follow-up)
                    └── Location selection page
                          └── For each location card:
                                └── Click card → slot calendar page loads
                                      └── GetLDBConsultantSlots API fires (intercepted)
                                            └── Replay API for weeks 1–10 (direct HTTP)
                                                  └── Parse SlotRecord list
                                      └── Go back → next location card
```

After a browser-flow run, `guid_store.populate_from_slots()` extracts GUIDs from the
`source_url` values stored on `AppointmentSlot` rows, upserts them into `booking_guids`,
and the consultant switches to Path A on the next run.

Key implementation details:
- **Session cookie** (`direct_api_scraper.py`): visiting the T&C URL
  `https://www.hcahealthcare.co.uk/finder/step-terms-and-conditions?slug={slug}` with
  `wait_until="domcontentloaded"` sets the `incap_ses_*` Incapsula cookie required by the API.
  Without it, the API returns 200 OK with an empty slots array — no error, just silent failure.
- **API replay** (`calendar_navigator.py`): uses `page.context.request.get(url)` to replay
  `GetLDBConsultantSlots` with modified `dateFrom`/`dateTo` per week. Shares browser session
  cookies. The most recent intercepted call is used (reversed scan) so each location gets its
  own `locationGUID`, not the first location's.
- **Location card detection** (`booking_navigator.py`): anchors on weekday-date labels
  ("Friday, 29 May 2026") visible in every card via JS bounding-rect scan. Works for cards
  that lack a "View location on Google Maps" link.
- **T&C acceptance**: URL-checked; clicks the exact-text "Accept" button with
  `scroll_into_view_if_needed()`. Cookie-related buttons are excluded by pattern.
- **Slot deduplication**: initial and follow-up records for the same `slot_datetime` are
  merged into one DB row before persistence.

---

## Database schema

### `appointment_slots` — core table

| Column | Type | Notes |
|--------|------|-------|
| `slot_id` | PK | |
| `consultant_id` | FK → consultants | |
| `consultant_name` | string | |
| `location_name` | string | Booking-flow name (differs from profile page name) |
| `funding_route` | string | `insured` / `self-pay` / `unknown` |
| `slot_datetime` | DateTime UTC | Naive UTC stored in SQLite |
| `slot_date` | string YYYY-MM-DD | London display date |
| `slot_time` | string HH:MM | London display time |
| `available_for_initial` | bool | Can this slot be booked as an initial consultation? |
| `available_for_follow_up` | bool | Can this slot be booked as a follow-up? |
| `first_seen_at` | DateTime | When first observed |
| `last_seen_at` | DateTime | Most recent scrape it appeared in |
| `times_seen_count` | int | How many scrapes it has appeared in |
| `current_status` | string | `visible` / `disappeared` / `expired_visible` / `unknown` |

**Unique key**: `(consultant_id, location_name, funding_route, slot_datetime)`

### Status lifecycle

```
                     ┌─────────────────────────────┐
   slot appears ────>│         visible              │
                     └──────────────┬──────────────┘
                                    │  absent from next scrape
                    ┌───────────────┴────────────────┐
                    │  slot_datetime > now + 48h?     │
                    └───────────────┬────────────────┘
                          yes │           │ no
                              ▼           ▼
                        disappeared   expired_visible
                        (likely         (within booking
                         booked)         window, may be
                                         phone-only)
```

### `booking_guids` — GUID cache for direct API path

| Column | Type | Notes |
|--------|------|-------|
| `guid_id` | PK | |
| `consultant_id` | FK → consultants | |
| `location_name` | string | Booking-flow location name |
| `funding_route` | string | `insured` / `self-pay` / `unknown` |
| `consultant_guid` | string | UUID used as `consultantGUID` query param |
| `location_guid` | string | UUID used as `locationGUID` query param |
| `discovered_at` | DateTime | When first extracted |

**Unique key**: `(consultant_id, location_name, funding_route)`

Seeded automatically at startup by `guid_store.populate_from_slots()`, which scans
`source_url` values in `appointment_slots` for `GetLDBConsultantSlots` URLs and parses
the GUIDs from their query strings.

### Other tables

- **`consultants`** — name, profile_url, specialty, GMC number, fees
- **`consultant_locations`** — locations from the profile page (not booking flow)
- **`scrape_runs`** — one row per `run_once.py` invocation; status + notes
- **`booking_snapshots`** — one row per (run × location); appointment_types present, page_url

---

## Data model: physical slots vs appointment-type compatibility

HCA exposes the same physical appointment time through two filters:
- `isFollowOnAppointment=false` (initial)
- `isFollowOnAppointment=true` (follow-up)

For Michael Adamczyk, follow-up is always the **superset** — every initial-compatible slot is
also follow-up-compatible, plus 2–3 late-day slots that are follow-up only. This means:

- **Unique physical slot times** = follow-up count
- **Do not sum initial + follow-up** — that double-counts

### Theoretical maximum capacity (Adamczyk)

Clinic structure observed from slot times:
- Morning: 09:00 – 11:40 = 9 slots at 20-min intervals
- Lunch break: 11:40 – 13:20 (no slots)
- Afternoon: 13:20 – 16:40 = 11 slots at 20-min intervals
- **Total: 20 slots per clinic day**

Adamczyk works Fridays only, alternating between two locations:
- Women's Health Centre – 272 Kings Road (odd Fridays in the observed window)
- Battersea and Nine Elms Outpatients (even Fridays)

Near-term dates (within 2 weeks) typically have 2–5 visible slots (mostly booked).
Dates 4+ weeks out typically show 16–19 visible slots (not yet booked).

---

## Analysis modules

### `analysis/capacity_benchmark.py` — Three-layer private outpatient footprint

Run via `python -m analysis.capacity_benchmark`. Produces a report structured as:

**Layer 1 — Clinic-day footprint**: which days of the week and locations the consultant works;
average clinic days/week over the 60-day lookahead window.

**Layer 2 — Slot supply per clinic day**: visible slot count per active date; median and modal
slots per clinic day.

**Layer 3 — Theoretical capacity benchmark**: compares observed visible HCA public online slot
supply to a hypothetical 5-day full-time outpatient schedule.

```
Observed visible HCA public online capacity : ~13 slots/week
Theoretical full-time outpatient schedule   : 5 days/week x 19 slots/day = 95 slots/week
Visible HCA capacity share of theoretical   : 13.7%
```

**Terminology rules** (enforced in code and reports):

| Use this | Not this | Reason |
|----------|----------|--------|
| visible HCA public online capacity | utilisation rate | utilisation requires bookings data |
| private outpatient footprint | schedule utilisation | footprint = observed clinic pattern |
| share of theoretical full-time capacity | occupancy rate | no booking confirmation yet |
| disappeared (status) | booked | disappearance is a proxy, not confirmed |

Utilisation rate (booked / capacity) will become meaningful once multiple scrape runs
accumulate enough slot disappearance history (T-21d / T-14d / T-7d / T-3d / T-48h windows).
That analysis lives in `analysis/metrics.py`.

### `analysis/metrics.py` — Availability decay metrics

`compute_decay_metrics(session, consultant_id, location_name, funding_route)` — computes
T-window slot counts and pct_visible survival rates per (location, funding_route) combination.
Requires ≥3 scrape runs to produce meaningful pct_visible figures.

`compute_all_metrics(session, consultant_id)` — runs the above for every
(location, funding_route) combo observed for a consultant.

---

## Adding a new consultant

1. Add an entry to `Settings.consultants` in `config/settings.py`:
   ```python
   {"name": "Jane Smith", "profile_url": "https://www.hcahealthcare.co.uk/finder/stepconsultantprofile/jane-smith"}
   ```
2. Run `python run_once.py` headful first. The new consultant has no stored GUIDs so it takes
   the full browser path (`booking_navigator.py`). `GetLDBConsultantSlots` URLs are captured
   and stored as `source_url` on the resulting `AppointmentSlot` rows.
3. On the **next** run, `guid_store.populate_from_slots()` seeds `booking_guids` from those
   `source_url` values and the consultant switches to the direct API path automatically.
4. Check logs for `Direct API path: N location/funding combos known` to confirm the switch.
   If still on the browser path after two runs, check `source_url` values in `appointment_slots`
   contain `GetLDBConsultantSlots` — if not, the intercept may have missed. Check screenshots.

---

## Logs and screenshots

- `logs/scrape_YYYYMMDD.log` — per-day rolling log from `run_once.py`
- `logs/scheduler.log` — continuous scheduler log
- `data/screenshots/` — PNG per calendar page: `{timestamp}_{location}_{type}_p{n}.png`
  Useful for debugging slot extraction and flow navigation issues.

---

## Key known constraints

- Slot datetimes are stored as **naive UTC** in SQLite (SQLite has no native timezone type).
  All comparisons in `slot_lifecycle.py` use `.replace(tzinfo=None)`.
- Booking-flow **location names differ** from profile-page location names. The DB stores
  the booking-flow name (e.g. "Battersea and Nine Elms Outpatients"), not the profile name
  (e.g. "The Lister Hospital").
- The `GetLDBConsultantSlots` API requires an Incapsula session cookie (`incap_ses_*`) set
  during booking flow navigation. Unauthenticated calls return 200 OK with an empty slots
  array — no error, just silent failure. A single `goto()` of the T&C page is sufficient.
- Slots within T-48h are marked `expired_visible`, not `disappeared`, because HCA may
  switch those to phone-only booking; their absence doesn't confirm a booking.
