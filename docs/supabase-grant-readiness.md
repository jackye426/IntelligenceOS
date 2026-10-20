# Explicit backend grants and rebuild readiness

Supabase's October 30 default-privilege change affects newly created public tables,
not existing grants. RLS does not replace table privileges; service_role bypasses
RLS but still needs privileges. See the [upstream notice](https://github.com/orgs/supabase/discussions/45329).

## Scope and contract

Every table creation in `sql/` now enables RLS and declares service_role access.
`tests/sql/grant-contract.json` records the intended operations, including four
read-only views and the externally supplied integrated_practitioners read path.
No anon/authenticated grants or global default-privilege restoration are added.
No TRUNCATE, REFERENCES, TRIGGER or blanket ALL grants are added. These tables
use UUID/text keys, so there are no new identity/serial sequences to grant.
Future sequence-backed inserts must add and test narrowly scoped sequence access.

Operation rationale:
- SELECT/INSERT/UPDATE supports backend upserts and returned representations in
  app/, lib/, worker/, mcp-server/, gtm-pipeline/ and marketing-pipeline/.
- Clinic source/observation/contact/interaction records, pipeline history, audit
  events, metric snapshots and creator profile snapshots use SELECT/INSERT only.
- DELETE is limited to content_posts (purge), document_embeddings (rebuild),
  creator_videos (prune), and gtm_outreach_cohort_members (replace membership).
- Cohort definitions are seeded by migration; the application only reads/updates.
- Doctor outreach/recommendation ingestion is described in SQL 003 as an external
  sync upsert. Email/call/patient metadata and relationship memory retain intended
  backend ingestion/upsert operations, even where this repository only reads.
- Some creator tables describe planned ingestion workflows, not observed live
  requests. Review the manifest whenever workflows change; it is an explicit
  capability contract, not a claim every permission has been seen in production.

This patch does not revoke old table grants. Existing authenticated policies in
historical SQL are also preserved; a policy alone does not confer SQL privileges.
It is not a remediation of all existing exposure. Privileged pgmq wrappers belong
in agent-swarm, not this repository (which uses pg-boss directly).

## Tests

```
npm ci --prefix tests/sql
npm test --prefix tests/sql
```

The pinned PGlite PostgreSQL/vector harness needs no credentials/network/database.
It executes the complete sorted SQL chain with no automatic role grants, checks
all eight table privileges for anon/authenticated/service_role and RLS, then
exercises synthetic backend insert/update/delete and denied client-role access.
Source mutation fixtures reject missing grants/RLS, undeclared future tables,
broad ALL and client-role grants. A pre-existing stray semicolon before LIMIT in
SQL 012 prevented clean replay; this patch fixes it and full-chain replay covers it.

Two minimal external prerequisites are supplied only in the disposable harness:
integrated_practitioner_with_phin(id text) for SQL 003's FK, and
integrated_practitioners(id uuid) for SQL 016. Their real schemas/importers are not
owned here. IMPORTANT: integrated_practitioner_with_phin is also the default
PRACTITIONERS_TABLE in mcp-server/common/config.py, read by
mcp-server/tools/search_practitioners.py using service_role. Its owning importer
must provision an explicit SELECT grant and appropriate RLS before that MCP read
path is ready. This patch deliberately does not infer or change that external
table's permission contract; its test fixture has no backend grant. Thus this is
repository-chain/privilege verification, not a complete
production restore or PostgREST/API certification. No live rows or queues are used.

## Review and deployment

This is a review-only change; it does not deploy SQL or change production.
For a new disposable staging project, provision the real external source tables,
confirm service-role application clients, apply the ordered SQL chain, and run
API smoke tests with synthetic data under each real JWT role. Do not substitute a
minimal test fixture for real source schemas or run historical backfills on an
existing production database merely to install grants.

For an existing project, current grants remain unchanged by the October 30
change. Inventory current ACLs/owners/RLS and compare against the manifest before
preparing any separate forward migration. Production grant/security changes need
explicit action-time approval of the exact SQL and project; this PR does not
supply that approval. Do not merge a deployment workflow that automatically
applies security changes. No production rollback is required for this code-only
patch; reverting source does not undo SQL that a human later chooses to deploy.

Coverage exclusions: historical project okpbevwdqgzmnrowifcn was absent from the
accessible Supabase inventory, synaptic-docmap/triage_tool was inaccessible, and
unmatched Company Brain/source tables are not created by this SQL chain. Nothing
here certifies or remediates those systems. Existing projects retain grants, so
passing a fresh-build test does not prove existing-role access is least privilege.
