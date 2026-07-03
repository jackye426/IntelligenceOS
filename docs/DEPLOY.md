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

Railway’s default builder is **Railpack** (Nixpacks is deprecated). Root Directory must be `data-worker` — not repo root.

`requirements.txt` installs `marketing-pipeline[media]` from GitHub `main` (yt-dlp + faster-whisper). `Aptfile` adds `ffmpeg` and `git`.

**Do not enable Dockerfile** for this service.

1. In the same Railway project → **+ New** → **GitHub Repo** → `jackye426/IntelligenceOS`
2. **Settings → General → Root Directory** = `data-worker`
3. **Settings → Build → Builder** = **Railpack** (default; not Dockerfile)
4. Variables:
   - `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`
   - `OPENROUTER_API_KEY`
   - `SKIP_CONTENT_TRACKER=true`
   - `SKIP_HCA=true`
   - `MARKETING_DATA_DIR=/app/marketing-data` — **mount a Railway volume** here
   - `WHISPER_MODEL=small` (optional)
   - `SKIP_TRANSCRIBE=false` (default; set `true` to disable Whisper on worker)
5. Deploy → logs should show `Transcription enabled on worker` and `Data worker ready`

**Cron (UTC):**
- Daily 03:30 — comments → **transcribe new videos** → export → sync → playbooks
- Weekly Sun 02:00 — full refresh (catalog, stats, transcribe, OCR) → export → sync

**Volume (recommended):** Mount persistent storage at `/app/marketing-data` so transcripts survive redeploys. First boot seeds from GitHub `main` if empty.

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

MCP build logs should show `pip install` and Python, not Node/Next.js.

**Data worker:** use Root Directory `data-worker` + **Railpack**. If `marketing-pipeline` is missing at runtime, confirm `requirements.txt` includes the git dependency. **`"/marketing-pipeline": not found`** — Dockerfile was enabled with wrong context; use Railpack instead.
