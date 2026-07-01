# DocMap MCP Team Setup

This guide explains how internal team members connect Claude Desktop (or another MCP client) to the hosted DocMap Intelligence MCP server.

## Prerequisites

- An internal MCP auth token (stored in the team password manager, not in this repo)
- The hosted MCP URL from Railway (placeholder: `https://docmap-mcp-production.up.railway.app/mcp`)
- Supabase migrations `001` through `004` applied in the shared project

## Environment variables (Railway — MCP service)

| Variable | Purpose |
|----------|---------|
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_SERVICE_ROLE_KEY` | Service role key for read queries |
| `OPENROUTER_API_KEY` | Query embedding for `search_knowledge` |
| `OPENROUTER_EMBEDDING_MODEL` | Default: `openai/text-embedding-3-small` |
| `MCP_AUTH_TOKEN` | Required bearer token for every request |
| `MCP_ALLOWED_ORIGINS` | Comma-separated browser origins (optional) |
| `MCP_MAX_SENSITIVITY` | Default: `confidential` |
| `PORT` | Set automatically by Railway |

## Environment variables (Railway — data worker)

| Variable | Purpose |
|----------|---------|
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_SERVICE_ROLE_KEY` | Service role key for ingestion writes |
| `OPENROUTER_API_KEY` | Embedding generation |
| `OPENROUTER_EMBEDDING_MODEL` | Default: `openai/text-embedding-3-small` |

## Local development

1. Copy `.env.example` to `.env.local` and fill in real values.
2. Run SQL migrations in Supabase (see `sql/`).
3. Install and run ingestion:

```bash
cd data-worker
pip install -r requirements.txt
cd ..
python scripts/ingest-content-tracker.py
```

4. Start the MCP server locally:

```bash
cd mcp-server
pip install -r requirements.txt
python main.py
```

The local endpoint is `http://127.0.0.1:8000/mcp`.

## Claude Desktop configuration

Add a remote MCP server entry (exact UI varies by Claude Desktop version):

```json
{
  "mcpServers": {
    "docmap-intelligence": {
      "url": "https://YOUR-RAILWAY-MCP-URL/mcp",
      "headers": {
        "Authorization": "Bearer YOUR_MCP_AUTH_TOKEN"
      }
    }
  }
}
```

## Health check

```bash
curl http://127.0.0.1:8000/health
```

Authenticated MCP requests must include:

```
Authorization: Bearer <MCP_AUTH_TOKEN>
```

Unauthenticated requests to `/mcp` return `401 Unauthorized`.

## First-use verification

After ingestion has run at least once:

1. Call `search_knowledge` with a content topic (e.g. endometriosis).
2. Confirm results include `source_title`, `source_url`, and short snippets only.
3. Call `get_content_performance` and confirm rows return from `content_posts`.
4. Check `mcp_tool_audit_log` in Supabase for logged tool calls.
