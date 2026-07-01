# DocMap MCP Runbook

Operational procedures for the MCP server and data worker.

## Rotate MCP_AUTH_TOKEN

1. Generate a new long random token in the team password manager.
2. Update `MCP_AUTH_TOKEN` in Railway for the MCP service.
3. Redeploy the MCP service.
4. Update Claude Desktop / client headers for all team members.
5. Verify `/mcp` rejects the old token and accepts the new one.
6. Old tokens should be treated as compromised after rotation.

## Disable privileged tools

`draft_outreach_email` is not implemented in the current build. If enabled in a future release:

1. Remove Gmail credentials from the MCP Railway service.
2. Feature-flag or remove the tool registration in `mcp-server/main.py`.
3. Redeploy and confirm the tool no longer appears in MCP discovery.

## Rerun ingestion

### Content tracker

```bash
python scripts/ingest-content-tracker.py
```

### TikTok catalog, transcripts, comments

```bash
python scripts/ingest-tiktok.py
```

### HCA SQLite migration

Requires `Appointment utilization rate/hca-monitor/data/hca_monitor.db`:

```bash
python scripts/ingest-hca-sqlite.py
```

Jobs are idempotent — safe to rerun. Check `data_ingestion_runs` for row counts and errors.

## Inspect failed ingestion runs

In Supabase SQL editor:

```sql
select job_name, status, started_at, finished_at, rows_seen,
       rows_inserted, rows_updated, error
from data_ingestion_runs
order by started_at desc
limit 20;
```

For local debugging, run the matching script directly and read the stack trace.

## Backfill embeddings

1. Ensure `OPENROUTER_API_KEY` is set in `.env.local`.
2. Run the relevant ingestion script (content tracker or TikTok).
3. For doctor recommendation events, use the existing TypeScript seeder:

```bash
npx tsx scripts/seed-embeddings.ts
```

4. Verify with:

```sql
select entity_type, count(*)
from document_embeddings
group by entity_type
order by count(*) desc;
```

## MCP audit review

```sql
select tool_name, action_type, success, request_summary, created_at
from mcp_tool_audit_log
order by created_at desc
limit 50;
```

Investigate any `success = false` rows before expanding tool access.

## Apply schema migration 004

If MCP tables or citation columns are missing, run in order:

1. `sql/001_clinic_intelligence.sql`
2. `sql/002_embeddings.sql`
3. `sql/003_doctor_outreach.sql`
4. `sql/004_mcp_sources.sql`

## Railway deployment checklist

### MCP service (web)

- Root directory: `mcp-server`
- Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
- Health check path: `/health`

### Data worker (background)

- Root directory: `data-worker`
- Start command: `python main.py`
- No public HTTP port required

## Incident response

| Symptom | Likely cause | Action |
|---------|--------------|--------|
| 401 on all MCP calls | Wrong or missing token | Rotate token, update clients |
| Empty `search_knowledge` results | No embeddings ingested | Rerun ingestion scripts |
| `get_appointment_availability` empty | HCA DB not migrated | Generate/copy SQLite, run HCA ingest |
| High OpenRouter spend | Repeated full re-ingestion | Check scheduler logs, fix idempotency issue |

## Privacy boundaries

- Do not ingest WhatsApp or Gmail content until privacy review is complete.
- MCP tools return cited chunks only — never full threads.
- Patient demand tool uses metadata tags, not raw message bodies.
