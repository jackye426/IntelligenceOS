# DocMap Clinic Outreach Intelligence

Internal, human-reviewed MVP for turning a clinic website and prior interaction notes into a structured outreach workspace.

This first commit is intentionally dependency-light: open `index.html` directly in a browser. It gives the team a usable product skeleton before choosing the production stack.

## What is included

- Clinic account list and account detail workspace
- Practitioner/contact, service, location, pricing, and observation sections
- Source-linked evidence ledger
- Pipeline board with MVP stages
- Outreach composer with review gate and claim checks
- Local-only persistence through `localStorage`
- JSON export for the selected account

## Run

Open `index.html` in a browser.

No install step is required.

## Product boundaries

- Internal users only
- No automated email sending
- No patient medical data ingestion
- No broad crawling beyond a submitted clinic URL
- All clinic-specific claims must remain traceable to source evidence or manual notes

## Recommended production path

Use this static MVP to validate workflow, then move to a full-stack app with:

- Authenticated internal route namespace
- Database-backed account, source, observation, contact, interaction, draft, stage-history, and task entities
- Server-side single-domain ingestion with SSRF protection
- Structured AI extraction with citations
- Human approval before outreach leaves the system

See `docs/architecture.md` for the conceptual schema and rollout plan.
