# DocMap MCP Team Setup

This guide explains how internal team members connect Claude Desktop (or another MCP client) to the hosted DocMap Intelligence MCP server.

## Prerequisites

- An internal MCP auth token (stored in the team password manager, not in this repo)
- Hosted MCP URL: **`https://mcp.docmap.co.uk/mcp`**
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
| `MCP_ALLOWED_HOSTS` | Comma-separated Host headers for MCP SDK DNS rebinding (optional; defaults include `mcp.docmap.co.uk`) |
| `MCP_DNS_REBINDING_PROTECTION` | Default `true`; set `false` only if behind trusted proxy + Bearer auth |
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
      "url": "https://mcp.docmap.co.uk/mcp",
      "headers": {
        "Authorization": "Bearer YOUR_MCP_AUTH_TOKEN"
      }
    }
  }
}
```

## Health check

```bash
curl https://mcp.docmap.co.uk/health
```

Authenticated MCP requests must include:

```
Authorization: Bearer <MCP_AUTH_TOKEN>
```

Unauthenticated requests to `/mcp` return `401 Unauthorized`.

## Troubleshooting

### `421 Invalid Host header` / Claude "error connecting"

MCP Python SDK 1.26+ blocks POST `/mcp` when the `Host` header is not allowlisted (DNS rebinding protection). GET `/health` can still return 200.

**Fix (already in repo):** `mcp-server` sets `transport_security` with `mcp.docmap.co.uk` allowed. Redeploy the MCP Railway service after pulling latest `main`.

**Railway env (optional):** add your `*.up.railway.app` hostname if testing without custom domain:

```
MCP_ALLOWED_HOSTS=mcp.docmap.co.uk,intelligenceos-production.up.railway.app
```

**Verify after deploy:**

```bash
python scripts/test_mcp_hosted.py
```

Expect `initialize: OK 200` (not HTTP 421).

### Stale DNS CNAME

If `mcp.docmap.co.uk` CNAME points to a deleted Railway service (`404 Application not found` on `*.up.railway.app`), regenerate the Railway domain in **Networking** and update the CNAME + TXT at your DNS provider.

## First-use verification

After ingestion has run at least once:

1. Call `search_knowledge` with a content topic (e.g. endometriosis).
2. Confirm results include `source_title`, `source_url`, and short snippets only.
3. Call `get_content_performance` and confirm rows return from `content_posts`.
4. Check `mcp_tool_audit_log` in Supabase for logged tool calls.
