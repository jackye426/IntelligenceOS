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

**Claude Desktop does not support `"url"` in `claude_desktop_config.json`.** It only accepts stdio servers (`command` + `args`). Use the **`mcp-remote`** bridge to connect to our hosted Streamable HTTP server.

**Windows config file:** `%APPDATA%\Claude\claude_desktop_config.json`  
**macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`

Requires **Node.js 18+** on the machine (Claude Desktop uses system Node for `npx`).

```json
{
  "mcpServers": {
    "docmap-intelligence": {
      "command": "npx",
      "args": [
        "-y",
        "mcp-remote@latest",
        "https://mcp.docmap.co.uk/mcp",
        "--transport",
        "http-only",
        "--header",
        "Authorization:${DOCMAP_MCP_AUTH}"
      ],
      "env": {
        "DOCMAP_MCP_AUTH": "Bearer YOUR_MCP_AUTH_TOKEN"
      }
    }
  }
}
```

**Windows note:** put the full `Bearer …` value in `env`, not in `args` (Claude Desktop mangles spaces in args). Use `Authorization:${DOCMAP_MCP_AUTH}` with no space before `${…}`.

Restart Claude Desktop completely after editing. You should see a hammer/tools icon when the connector loads.

**Verify from terminal (optional):**

```bash
npx -y -p mcp-remote@latest mcp-remote-client https://mcp.docmap.co.uk/mcp --transport http-only --header "Authorization:Bearer YOUR_TOKEN"
```

Expect `Connected successfully!` and a tools list.

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

### Claude "MCP server could not be loaded"

**Cause:** `"url"` / `"headers"` entries in `claude_desktop_config.json` are **invalid** — Claude Desktop skips them at startup.

**Fix:** Use the `mcp-remote` stdio bridge (see Claude Desktop configuration above). Do not use `"url"` directly.

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
