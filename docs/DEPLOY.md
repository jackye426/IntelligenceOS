# Deployment Guide — Intelligence OS

Pre-flight decisions: see [`MASTER_PLAN.md`](MASTER_PLAN.md).

## Topology

| Service | Platform | Root directory | Start command |
|---------|----------|----------------|---------------|
| Next.js app | **Vercel** | repo root | `next start` (auto) |
| MCP server | **Railway** | `mcp-server/` | `uvicorn main:app --host 0.0.0.0 --port $PORT` |
| Data worker | **Railway** | `data-worker/` | `python main.py` |

## Railway: MCP server

**Important:** Railway must **not** build from the repo root (that triggers a Next.js build and will fail). Each service needs its own **Root Directory**.

1. New service → connect GitHub repo `jackye426/IntelligenceOS`
2. Open the service → **Settings** → **General** → **Root Directory** = `mcp-server`
3. Variables:
   - `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`
   - `OPENROUTER_API_KEY`
   - `MCP_AUTH_TOKEN` (generate strong random)
   - `MCP_ALLOWED_ORIGINS` (comma-separated, optional)
   - `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, `GMAIL_REFRESH_TOKEN` (for draft tool)
4. Deploy → verify `GET /health` → `{"status":"ok","service":"docmap-mcp"}`
5. MCP URL: `https://mcp.docmap.co.uk/mcp` (see team setup doc)

## Railway: data-worker

Railway’s `data-worker` root build **cannot** see `../marketing-pipeline` (sibling folder is outside the build context). Use **one** of these options:

### Option A — Nixpacks (keep Root Directory = `data-worker`)

Default in repo: `nixpacks.toml` installs `marketing-pipeline` from GitHub `main`.

1. In the same Railway project → **+ New** → **GitHub Repo** → `jackye426/IntelligenceOS`
2. **Settings → General → Root Directory** = `data-worker`
3. Variables:
   - `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`
   - `OPENROUTER_API_KEY`
   - `SKIP_CONTENT_TRACKER=true`
   - `SKIP_HCA=true`
4. Deploy → check logs for `Data worker ready` and cron registration

### Option B — Dockerfile (same commit as deploy; recommended for prod)

1. **Settings → General → Root Directory** = `.` (repo root, not `data-worker`)
2. **Settings → Build → Builder** = Dockerfile
3. **Dockerfile path** = `data-worker/Dockerfile`
4. Same variables as Option A

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

## Troubleshooting: "Build failed" on first Railway deploy

If the service is named after the repo (`IntelligenceOS`) and the build log shows `npm install`, `next build`, or Playwright:

1. You are building the **whole monorepo** — wrong for MCP/worker.
2. **Settings → General → Root Directory** → set `mcp-server` (or `data-worker` for the worker).
3. Click **Redeploy** (or delete the failed service and add a new one with the correct root).

MCP build logs should show `pip install -r requirements.txt` and Python 3.11, not Node/Next.js.

**Data worker:** `ERROR: ../marketing-pipeline is not a valid editable requirement` means Root Directory is `data-worker` but the old `requirements.txt` referenced a sibling path. Redeploy after pulling latest `main`, or switch to Dockerfile (Option B in DEPLOY.md).
