# Spire appointment utilization — investigation (Aug 2026)

## Question

Can we reuse the HCA monitor approach (repeated public slot snapshots → lifecycle →
utilisation proxy) for Spire consultants?

**Short answer: yes — and Spire is easier than HCA.**

## Sample consultant

- Profile: https://www.spirehealthcare.com/consultant-profiles/mr-simon-phillips-c4069414/
- `ConsultantId` (meta tag): `C4069414` (also in URL slug: `...-c4069414`)
- Booking widget: embedded **COBPS** Angular calendar (`cobpsCalendar`)
- API base: `https://appointments.spirehealthcare.com` (hidden input `cobpsBaseUrl`)

## Public APIs (no login, no Playwright required)

Verified with direct HTTP (`Accept: application/json`):

| Endpoint | Purpose |
|----------|---------|
| `GET .../LocationApi/GetAvailableLocations?consultantId={id}&locationId=` | Hospitals where consultant books online |
| `GET .../AppointmentApi/GetFirstAppointmentsForLocation?consultantId={id}&month={m}&year={y}&locationId={loc}` | **One earliest slot per day** that has availability (calendar month view) |
| `GET .../AppointmentApi/GetAppointmentsForLocationAndDate?consultantId={id}&day={d}&month={m}&year={y}&locationId={loc}` | **All slots** on a specific day |

Simon Phillips @ Cardiff (`locationId=CDF`), probe results:

- Locations API → 1 hospital (Cardiff)
- Sep 2026 month → 10 days with at least one slot
- 8 Sep 2026 day detail → 1 slot at 10:00 (£175, 30 min)

Slot payload shape:

```json
{
  "Amount": 175.0,
  "Currency": "GBP",
  "Duration": 30,
  "OrganisationUnit": "CDF_CON",
  "SAPDateTime": {
    "DateTime": "2026-09-08T10:00:00",
    "Date": "20260908",
    "Time": "10:0000"
  }
}
```

## Comparison to HCA monitor

| | HCA | Spire |
|---|-----|-------|
| Slot source | `GetLDBConsultantSlots` (intercept + replay) | COBPS Umbraco REST APIs |
| Auth / anti-bot | Incapsula cookie required | None observed on read APIs |
| Browser | Playwright (at least for cookie / first run) | **Optional** (profile → consultant ID only) |
| Funding routes | insured / self-pay separate | Self-pay + PMI (PMI may block online book) |
| Appt types | initial + follow-up (merge flags) | New vs follow-up (follow-up often phone-only) |
| Utilisation logic | Same lifecycle (`visible` → `disappeared`) | **Reusable as-is** |

## Recommended scrape strategy

1. **Discover** `consultantId` from profile URL slug (`-c{id}`) or `<meta name="ConsultantId">`
2. **Locations** → `GetAvailableLocations`
3. For each month in 60-day lookahead:
   - `GetFirstAppointmentsForLocation` → days with any availability
4. For each day returned:
   - `GetAppointmentsForLocationAndDate` → full slot list for that day
5. Upsert into same `appointment_slots` schema as HCA (new `source_system = spire_monitor`)
6. Run 3×/day; disappearance ≈ booking proxy (same T-48h caveats)

## Caveats

- `GetFirstAppointmentsForLocation` is **not** the full slot inventory — must fan out per day.
- PMI / insurance path may differ; self-pay path is the HCA analogue.
- Follow-up appointments may be phone-only for some consultants (UI message on profile).
- Rate limits unknown — still use polite delays (no need for Bright Data).
- Consultant ID casing: use uppercase from meta (`C4069414`), lowercase slug also worked in probe.

## Next step

Run `python probe_api.py` in this folder, then fork `hca-monitor` storage/analysis with a
thin `spire-monitor/scraper/api_client.py` instead of Playwright.
