# Clinic Outreach Intelligence Architecture Notes

## Executive Summary

This repo starts from an empty workspace, so there are no existing code paths to reuse. The current implementation is a front-end MVP that models the core workflow and data boundaries without introducing infrastructure too early.

Confirmed facts:

- There was no existing app, database schema, auth model, queue, AI wrapper, or route tree in the workspace at creation time.
- The static MVP lives in `index.html`, `styles.css`, and `app.js`.
- Account data is local-only and stored under `docmap.clinic-intel.accounts.v1` in `localStorage`.

Assumptions:

- Production will be internal-only.
- A later version may move to Next.js or another full-stack framework.
- AI generation will require provider and model choices that are not yet present in this repo.

## Current Architecture Map

- UI shell: `index.html`
- Styling and responsive layout: `styles.css`
- State, seeded data, rendering, local persistence: `app.js`
- Product and setup notes: `README.md`
- Conceptual architecture: `docs/architecture.md`

No package manager, deployment target, database, ORM, auth provider, storage provider, queue, analytics, or LLM integration is configured yet.

## Reusable MVP Components

- Account list: `#accountList` rendered by `renderAccountList()` in `app.js`
- Account profile: `#accountDetail` rendered by `renderAccountDetail()` in `app.js`
- Evidence ledger: `#evidenceLedger` rendered by `renderResearch()` in `app.js`
- Pipeline board: `#pipelineBoard` rendered by `renderPipeline()` in `app.js`
- Outreach composer: `#outreachView` rendered by `renderOutreach()` in `app.js`
- Review gate: `#reviewNotice` and claim checks in `renderOutreach()`

## Conceptual Schema

### ClinicAccount

Purpose: Internal sales account for a clinic.

Fields:

- `id`
- `name`
- `websiteUrl`
- `ownerUserId`
- `pipelineStage`
- `fitScore`
- `salesAngle`
- `nextAction`
- `nextActionDueAt`
- `createdAt`
- `updatedAt`
- `deletedAt`

Indexes:

- `websiteUrl`
- `ownerUserId`
- `pipelineStage`
- `nextActionDueAt`

Needs soft deletion: Yes.

### ClinicSource

Purpose: Captured source page, manual note, thread, or meeting note used as evidence.

Fields:

- `id`
- `clinicAccountId`
- `type`: `website_page`, `manual_note`, `email_thread`, `meeting_note`
- `url`
- `title`
- `capturedAt`
- `rawText`
- `contentHash`
- `approvedForUse`

Indexes:

- `clinicAccountId`
- `contentHash`
- `url`

Needs source attribution: Core requirement.

### ClinicResearchRun

Purpose: Tracks ingestion and extraction attempts.

Fields:

- `id`
- `clinicAccountId`
- `status`: `queued`, `fetching`, `extracting`, `needs_review`, `approved`, `failed`
- `submittedUrl`
- `allowedDomain`
- `startedAt`
- `finishedAt`
- `error`
- `createdByUserId`

Indexes:

- `clinicAccountId`
- `status`
- `createdByUserId`

### ClinicObservation

Purpose: Evidence-backed patient journey or sales observation.

Fields:

- `id`
- `clinicAccountId`
- `sourceId`
- `category`: `patient_journey`, `pricing`, `service`, `contact_route`, `positioning`
- `text`
- `confidence`
- `reviewStatus`: `draft`, `approved`, `rejected`

Indexes:

- `clinicAccountId`
- `sourceId`
- `reviewStatus`

### ClinicContact

Purpose: Person or route associated with the account.

Fields:

- `id`
- `clinicAccountId`
- `name`
- `role`
- `email`
- `phone`
- `sourceId`
- `confidence`
- `reviewStatus`

Indexes:

- `clinicAccountId`
- `email`
- `role`

### ClinicInteraction

Purpose: Prior emails, meetings, notes, and owner activity.

Fields:

- `id`
- `clinicAccountId`
- `type`: `manual_note`, `email_thread`, `meeting_note`, `call`, `system_event`
- `body`
- `occurredAt`
- `createdByUserId`
- `sourceId`

Indexes:

- `clinicAccountId`
- `occurredAt`

### OutreachDraft

Purpose: Human-reviewed outreach copy.

Fields:

- `id`
- `clinicAccountId`
- `subject`
- `body`
- `tone`
- `status`: `draft`, `approved`, `sent_elsewhere`, `archived`
- `generatedFromRunId`
- `approvedByUserId`
- `approvedAt`

Indexes:

- `clinicAccountId`
- `status`

### PipelineStageHistory

Purpose: Immutable event log for stage movement.

Fields:

- `id`
- `clinicAccountId`
- `fromStage`
- `toStage`
- `changedByUserId`
- `changedAt`
- `reason`

Indexes:

- `clinicAccountId`
- `changedAt`
- `toStage`

### AccountTask

Purpose: Next action and follow-up tracking.

Fields:

- `id`
- `clinicAccountId`
- `ownerUserId`
- `title`
- `status`: `open`, `done`, `cancelled`
- `dueAt`
- `completedAt`

Indexes:

- `ownerUserId`
- `status`
- `dueAt`

## Recommended Routes and Screens

- `/internal/clinic-intelligence/accounts`: account list
- `/internal/clinic-intelligence/accounts/:id`: account profile
- `/internal/clinic-intelligence/accounts/:id/research`: sources, runs, observations
- `/internal/clinic-intelligence/accounts/:id/outreach`: draft composer and claim checks
- `/internal/clinic-intelligence/pipeline`: pipeline view

Use an authenticated internal namespace. Do not mix clinic-intelligence entities with patient-facing or clinic-facing entities unless a deliberate integration boundary is added.

## Ingestion Constraints

Recommended MVP flow:

1. Accept one user-submitted clinic URL.
2. Resolve and validate the hostname.
3. Reject private, loopback, link-local, and internal IP ranges.
4. Fetch only HTTPS pages from the same registered domain.
5. Cap pages, bytes, redirects, and execution time.
6. Store extracted text and source metadata before AI extraction.
7. Require human review before observations or drafts are approved.

Security risks:

- SSRF through arbitrary URL fetches
- Confidential data leakage from manual notes or email imports
- Unsupported AI claims about clinic services, pricing, practitioners, or patient journey
- Accidental processing of patient medical data
- Crawling pages outside the submitted clinic domain

## AI Implementation Assessment

No current AI provider exists in this repo.

Recommended extraction pattern:

- Parse pages into source records first.
- Ask the model for structured JSON only.
- Require every extracted field and observation to include `sourceId` and a short evidence span.
- Reject unsupported claims in validation.
- Treat contact roles, sales angle, and outreach as draft suggestions until approved.

Suggested outputs:

- `profile`: services, locations, practitioners, pricing, contact routes
- `observations`: category, text, confidence, source IDs
- `salesAngle`: concise positioning with source support
- `outreachDraft`: subject and body with claim references

Cost drivers:

- Number of pages fetched
- HTML-to-text size
- Number of extraction passes
- Outreach generation retries
- Embedding or retrieval, if later added

## Testing and Rollout Plan

Current static MVP:

- Smoke test by opening `index.html`
- Validate account creation, research queue, pipeline update, draft edit, approval, and export
- Confirm localStorage persistence after refresh

Production rollout:

- Unit tests for URL validation, pipeline transitions, claim/source validation, and schema parsing
- Integration tests for ingestion, extraction, persistence, and permissions
- End-to-end tests for account creation through approved draft
- Feature flag the internal route namespace
- Start with seeded internal accounts and manual notes before enabling URL fetch
- Log research runs, stage changes, draft approvals, and rejected AI claims
- Roll back by disabling the feature flag and pausing research workers

## Open Questions

- Which production framework should this live in?
- Which auth provider identifies internal users?
- Which database and ORM should back the MVP?
- Which AI provider and model should be approved?
- Should existing DocMap emails be imported manually, via upload, or through a future mailbox integration?
- What jurisdictions and privacy controls apply to clinic outreach notes?

## Implementation Phases

1. Validate workflow using the static MVP.
2. Choose production framework, auth, database, and deployment target.
3. Add internal account schema and permission boundary.
4. Build single-domain source ingestion with SSRF controls.
5. Add structured extraction and citation validation.
6. Add outreach draft generation with approval workflow.
7. Add pipeline history, tasks, and observability.
8. Pilot with a small internal account set.

## Capability Table

| Area | Existing capability | Reuse / Extend / Build | Key files | Risk |
| ---- | ------------------- | ---------------------- | --------- | ---- |
| Account workspace | Static seeded UI | Extend | `index.html`, `app.js` | Low |
| Evidence ledger | Static source records | Extend | `app.js` | Medium |
| Pipeline | Static board and stages | Extend | `app.js` | Low |
| Outreach composer | Local draft editor | Extend | `app.js` | Medium |
| Auth | None | Build | None | High |
| Database | None | Build | None | High |
| URL ingestion | None | Build | None | High |
| AI extraction | None | Build | None | High |
| Audit history | Static interaction list | Build | `app.js` | Medium |
| Automated email | Excluded | Do not build | None | High |
