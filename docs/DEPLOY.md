# Deployment Guide — Intelligence OS

Pre-flight decisions: see [`MASTER_PLAN.md`](MASTER_PLAN.md).

## Topology

| Service | Platform | Root directory | Start command |
|---------|----------|----------------|---------------|
| Next.js app | **Vercel** | repo root | `next start` (auto) |
| MCP server | **Railway** | `mcp-server/` | `uvicorn main:app --host 0.0.0.0 --port $PORT` |
| Data worker | **Railway** | `data-worker/` | `python main.py` |

## Railway: MCP server

1. New service → connect GitHub repo `jackye426/IntelligenceOS`
2. Set **Root Directory** = `mcp-server`
3. Variables:
   - `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`
   - `OPENROUTER_API_KEY`
   - `MCP_AUTH_TOKEN` (generate strong random)
   - `MCP_ALLOWED_ORIGINS` (comma-separated, optional)
   - `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, `GMAIL_REFRESH_TOKEN` (for draft tool)
4. Deploy → verify `GET /health` → `{"status":"ok","service":"docmap-mcp"}`
5. MCP URL: `https://<service>.up.railway.app/mcp` (see team setup doc)

## Railway: data-worker

1. New service → same repo
2. Set **Root Directory** = `data-worker`
3. Variables:
   - `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`
   - `OPENROUTER_API_KEY`
   - `SKIP_CONTENT_TRACKER=true`
   - `SKIP_HCA=true`
4. Deploy → check logs for `Data worker ready` and cron registration

**Cron (UTC):**
- Daily 03:30 — TikTok `refresh-comments` → export → sync
- Weekly Sun 02:00 — full `refresh` + OCR

## Vercel: Next.js app

1. Import repo → framework Next.js (auto-detected)
2. Variables:
   - `NEXT_PUBLIC_SUPABASE_URL`, `SUPABASE_URL`
   - `SUPABASE_SERVICE_ROLE_KEY` (server routes only)
   - `OPENROUTER_API_KEY`
   - `SESSION_PASSWORD`
3. Deploy → verify `/login` loads

**Not on Vercel:** Playwright worker (`worker/index.ts`) — run locally until a dedicated Railway worker is needed.

## Post-deploy verification

```bash
# MCP health
curl https://<mcp-host>/health

# Schema check (local, with .env.local)
python scripts/verify-supabase-schema.py

# TikTok pipeline tests
pytest marketing-pipeline/tests/
```

## Human-only steps

- **A1:** Rotate any exposed Supabase/OpenRouter/Google credentials
- **A2:** Confirm SQL 001–004 applied in Supabase SQL editor
