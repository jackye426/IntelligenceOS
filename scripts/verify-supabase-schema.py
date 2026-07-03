"""Verify core Supabase tables and RPC exist."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env.local")
load_dotenv(ROOT / ".env")

url = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")
if not url or not key:
    print("ERROR: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY required")
    sys.exit(1)

client = create_client(url, key)

TABLES = [
    "content_posts",
    "document_embeddings",
    "mcp_tool_audit_log",
    "data_ingestion_runs",
    "clinic_accounts",
    "doctor_outreach",
]

errors = 0
for table in TABLES:
    try:
        pk = "practitioner_id" if table == "doctor_outreach" else "id"
        count = client.table(table).select(pk, count="exact").limit(1).execute().count
        print(f"OK  {table} (rows~{count})")
    except Exception as exc:  # noqa: BLE001
        print(f"MISSING {table}: {exc}")
        errors += 1

try:
    client.rpc(
        "match_documents",
        {
            "query_embedding": [0.0] * 1536,
            "match_count": 1,
            "filter_type": None,
            "max_sensitivity": "confidential",
        },
    ).execute()
    print("OK  match_documents RPC")
except Exception as exc:  # noqa: BLE001
    print(f"MISSING match_documents: {exc}")
    errors += 1

sys.exit(1 if errors else 0)
