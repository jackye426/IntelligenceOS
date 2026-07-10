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
   - `SKIP_STUDIO_LISTEN=false` (default; Studio Playwright 2×/week — needs login profile on volume)
   - Optional rate caps: `STUDIO_LISTEN_RECENT=12`, `STUDIO_LISTEN_SETTLE_MS=5000`, `STUDIO_LISTEN_PAUSE_MS=10000`
5. Deploy → logs should show `Transcription enabled on worker` and `Data worker ready`

**Cron (UTC):**
- Daily 03:30 — comments → **transcribe new videos** → export → sync → playbooks
- Every 3h (:15) — Display API metric snapshots (skipped until OAuth configured)
- Tue/Fri 05:45 — Studio Playwright insight capture (≤12 recent videos, ~10s pause between pages)
- Weekly Sun 02:00 — full refresh (catalog, stats, transcribe, OCR) → export → sync

**Studio login profile:** Run `python -m marketing_pipeline tiktok studio-listen --login` locally once, then copy `marketing-pipeline/tiktok/data/.tiktok_studio_profile/` onto the Railway volume at `$MARKETING_DATA_DIR/.tiktok_studio_profile/`. Without it the job skips safely.

**Volume (recommended):** Mount persistent storage at `/app/marketing-data` so transcripts survive redeploys. First boot seeds from GitHub `main` if empty.

## Vercel: Next.js app

**Use the CLI from repo root** — the dashboard import flow may force Vercel Services
(`data-worker`, `mcp-server`). Those stay on Railway only; do not add
`experimentalServices` or multi-service `vercel.json`.

### 1. Create project via CLI (PowerShell, repo root)

```powershell
npx vercel@latest login
npx vercel@latest
```

Prompts:

```text
Link to existing project?  No
Project name?             intelligence-os-web
Detected Next.js          Yes
Customize settings?       No
```

This links `.vercel/` locally (gitignored). Root `package.json` + `vercel.json` deploy as **Next.js only**.

### 2. Environment variables

Vercel dashboard → project **intelligence-os-web** → **Settings → Environment Variables** (Production):

| Variable | Notes |
|----------|--------|
| `NEXT_PUBLIC_SUPABASE_URL` | Supabase project URL |
| `SUPABASE_URL` | Same URL |
| `SUPABASE_KEY` | **Service role** — required (`lib/supabase.ts` reads this name) |
| `SUPABASE_SERVICE_ROLE_KEY` | Same value (optional duplicate) |
| `OPENROUTER_API_KEY` | Ask DocMap + embeddings |
| `SESSION_PASSWORD` | Cookie signing (32+ chars) |
| `INTERNAL_PASSWORD` | Password typed at `/login` |

Optional: `OPENROUTER_MODEL`, `OPENROUTER_EMBEDDING_MODEL`, `SUPABASE_PRACTITIONERS_TABLE`.

Do **not** set MCP/worker vars here unless you know you need them.

### 3. Connect GitHub + production deploy

```powershell
npx vercel@latest git connect
npx vercel@latest --prod
```

`git connect` uses the repo’s existing Git remote. Future pushes to `main` auto-deploy this project only.

### 4. Verify

- `/login` loads
- Login with `INTERNAL_PASSWORD`
- `/accounts` shows clinic rows (1,662 in prod)
- `/pipeline`, `/ask` load

**Not on Vercel:** `mcp-server/`, `data-worker/` (Railway), Playwright worker (`npm run worker` — local or future Railway worker).

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
