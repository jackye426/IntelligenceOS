# DocMap Intelligence OS

Internal intelligence platform for **DocMap**. It is a monorepo of tools that started as **manual ops** - talking to patients and clinics, reading reviews, watching TikTok comments, drafting outreach by hand - and were productised so the same judgement scales.

**Live web preview:** [intelligence-os-web.vercel.app](https://intelligence-os-web.vercel.app)  
**Hosted MCP:** `https://mcp.docmap.co.uk/mcp`

## How to read this repo

Two layers:

1. **Platform packages** - Next.js clinic UI, MCP, marketing ETL, workers (run in production)
2. **Absorbed project folders** - earlier standalone tools kept here for convenience; several also have **their own GitHub repos** for clear ownership and READMEs

### Platform packages

| Path | Role |
|------|------|
| App / UI (Next.js root) | Clinic outreach / accounts dashboard |
| `mcp-server/` | Hosted MCP for Claude (TikTok tools, search, Gmail drafts) |
| `marketing-pipeline/` | Production TikTok ETL + Supabase sync |
| `data-worker/` | Railway cron jobs |
| `ingestion-pipeline/` | Clinic CSV -> Supabase + embeddings |
| `gtm-pipeline/` | GTM / CQC account intelligence |
| `relationship-desk-mcp/` | Gmail relationship memory MCP |
| `docs/` | Deploy, MCP onboarding, execution plans |

### Absorbed projects (also on GitHub)

These folders are the "we did this manually, then automated it" toolkit:

| Folder in this repo | Standalone repo | What it is |
|---------------------|-----------------|------------|
| `Clinic sales agent/` | [clinic-sales-agent](https://github.com/jackye426/clinic-sales-agent) | Doctify discovery, enrichment, CQC match, outreach drafts |
| `Carousel agents V2/` | [carousel-agent](https://github.com/jackye426/carousel-agent) | Selection-first social carousels from documents |
| `Doctors Sales Agent/` | [doctor-sales-agent](https://github.com/jackye426/doctor-sales-agent) | Doctor onboarding email drafts from WhatsApp recommendations |
| `Negative Review analysis/` | [negative-review-analysis](https://github.com/jackye426/negative-review-analysis) | Google negative-review themes for clinics |
| `Social media analysis/` | [social-media-analysis](https://github.com/jackye426/social-media-analysis) | TikTok metrics / transcripts / performance hypotheses |

Related product (separate org repo): [synaptic-docmap/triage_tool](https://github.com/synaptic-docmap/triage_tool) - WhatsApp / specialist triage for patients. Ranking research: [ranking_algo](https://github.com/jackye426/ranking_algo).

Living status: [`STATUS.md`](STATUS.md). Master plan: [`docs/MASTER_PLAN.md`](docs/MASTER_PLAN.md).

## Quick start

### Web app

```bash
npm install
cp .env.example .env.local
npm run dev
```

### TikTok marketing pipeline (production path)

```bash
cd marketing-pipeline
pip install -e .
python -m marketing_pipeline tiktok extract-components
python -m marketing_pipeline tiktok sync-supabase
```

### Team MCP (Claude)

See [`docs/MCP_ONBOARDING.md`](docs/MCP_ONBOARDING.md) and [`docs/DEPLOY.md`](docs/DEPLOY.md).

## Notable env (TikTok)

Copy `.env.example` to `.env.local`:

- `MODEL_OCR` - vision OCR (default Gemini Flash)
- `MODEL_COMPONENTS` - component cards (default DeepSeek flash)

## Docs index

| Doc | Topic |
|-----|--------|
| [`STATUS.md`](STATUS.md) | Prod health and next steps |
| [`docs/DEPLOY.md`](docs/DEPLOY.md) | Railway / Vercel / MCP |
| [`docs/MCP_ONBOARDING.md`](docs/MCP_ONBOARDING.md) | Connect Claude to DocMap MCP |
| [`docs/MASTER_PLAN.md`](docs/MASTER_PLAN.md) | Phased product plan |
