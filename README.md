# DocMap Intelligence OS

Internal intelligence platform for **DocMap**: clinic outreach and account intelligence, a hosted MCP for Claude, TikTok marketing ETL, and background data workers - one monorepo, shared Supabase store.

**Live web preview:** [intelligence-os-web.vercel.app](https://intelligence-os-web.vercel.app)  
**Hosted MCP:** `https://mcp.docmap.co.uk/mcp`

## What you get

- **Clinic OS (Next.js)** - outreach / accounts UI over `clinic_accounts` and related tables
- **MCP server** - TikTok tools, decision log, document search, Gmail draft outreach (`confirmed` required)
- **Marketing pipeline** - TikTok catalog to transcripts / OCR / comments to component extract to Supabase
- **Data worker** - Railway cron for TikTok refresh and metric layers
- **Ingestion pipeline** - clinic CSV seed into Supabase with embeddings

Living status and phase checklist: [`STATUS.md`](STATUS.md). Master plan: [`docs/MASTER_PLAN.md`](docs/MASTER_PLAN.md).

## Repository map

| Path | Role |
|------|------|
| App / UI (Next.js root) | Clinic outreach dashboard |
| `mcp-server/` | Hosted MCP for Claude / team tooling |
| `marketing-pipeline/` | TikTok ETL + component extraction |
| `data-worker/` | Railway cron jobs |
| `ingestion-pipeline/` | Clinic CSV to Supabase |
| `docs/` | Deploy, MCP onboarding, execution plans |
| `gtm-pipeline/`, `relationship-desk-mcp/` | Adjacent GTM / relationship experiments |

## Quick start

### 1. Web app

```bash
npm install
cp .env.example .env.local   # set SUPABASE_*, OPENROUTER_API_KEY, SESSION_PASSWORD, etc.
npm run dev
```

### 2. TikTok marketing pipeline

```bash
cd marketing-pipeline
pip install -e .
python -m marketing_pipeline tiktok extract-components
python -m marketing_pipeline tiktok sync-supabase
```

Details: [`marketing-pipeline/README.md`](marketing-pipeline/README.md).

### 3. Team MCP (Claude)

See [`docs/MCP_ONBOARDING.md`](docs/MCP_ONBOARDING.md) and [`docs/DEPLOY.md`](docs/DEPLOY.md).

## Notable env (TikTok)

Copy `.env.example` to `.env.local`. Common model knobs:

- `MODEL_OCR` - vision OCR (default Gemini Flash)
- `MODEL_COMPONENTS` - component cards (default DeepSeek flash)

## Docs index

| Doc | Topic |
|-----|--------|
| [`STATUS.md`](STATUS.md) | Current prod health and next steps |
| [`docs/DEPLOY.md`](docs/DEPLOY.md) | Railway / Vercel / MCP deploy |
| [`docs/MCP_ONBOARDING.md`](docs/MCP_ONBOARDING.md) | Connect Claude to DocMap MCP |
| [`docs/MASTER_PLAN.md`](docs/MASTER_PLAN.md) | Phased product plan |
| [`docs/EXECUTION_PLAN_VIDEO_COMPONENTS.md`](docs/EXECUTION_PLAN_VIDEO_COMPONENTS.md) | Component extract plan |

## Status

Ops and TikTok M3 paths are largely live (MCP healthy, clinic import seeded). Instagram module and full dashboard Vercel promotion are still in flight - see `STATUS.md` for the dated checklist.
