# DocMap Intelligence OS

Monorepo for DocMap internal intelligence: clinic OS (Next.js), hosted MCP for Claude, TikTok marketing pipeline, and data workers.

## What’s in this repo

| Path | Role |
|------|------|
| `app/` | Next.js clinic outreach / accounts UI |
| `mcp-server/` | Hosted MCP (`https://mcp.docmap.co.uk/mcp`) — TikTok tools, decision log, components read API |
| `marketing-pipeline/` | TikTok ETL: catalog, transcripts, OCR, comments, **component extract**, Supabase sync |
| `data-worker/` | Railway cron for TikTok refresh / metric layers (Studio Playwright = internal-only; see Deploy) |
| `ingestion-pipeline/` | Clinic CSV → Supabase seed |
| `docs/` | Deploy, MCP onboarding, execution plans |

## TikTok marketing (quick start)

See [`marketing-pipeline/README.md`](marketing-pipeline/README.md).

```bash
cd marketing-pipeline
pip install -e .
python -m marketing_pipeline tiktok extract-components   # MODEL_COMPONENTS (DeepSeek flash by default)
python -m marketing_pipeline tiktok sync-supabase
```

- Team Claude setup: [`docs/MCP_ONBOARDING.md`](docs/MCP_ONBOARDING.md)
- Component extract plan: [`docs/EXECUTION_PLAN_VIDEO_COMPONENTS.md`](docs/EXECUTION_PLAN_VIDEO_COMPONENTS.md)
- Deploy: [`docs/DEPLOY.md`](docs/DEPLOY.md)
- Living status: [`STATUS.md`](STATUS.md)

## Env

Copy `.env.example` → `.env.local`. Notable TikTok models:

- `MODEL_OCR` — vision OCR (default Gemini Flash)
- `MODEL_COMPONENTS` — component cards (default `deepseek/deepseek-v4-flash`)
