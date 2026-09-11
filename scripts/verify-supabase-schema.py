"""Verify core Supabase tables and RPC exist."""

from __future__ import annotations

import os
import sys
from collections import Counter
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


def fetch_all(table: str, columns: str, *, page_size: int = 1000):
    rows = []
    while True:
        page = (
            client.table(table)
            .select(columns)
            .range(len(rows), len(rows) + page_size - 1)
            .execute()
            .data
            or []
        )
        rows.extend(page)
        if len(page) < page_size:
            return rows


try:
    posts = [
        row
        for row in fetch_all(
            "content_posts",
            "platform_post_id, platform, account_handle, owner_scope, post_url",
        )
        if row.get("platform") == "tiktok"
    ]
    account_counts = Counter(str(row.get("account_handle") or "<missing>") for row in posts)
    print(f"OK  TikTok account counts: {dict(sorted(account_counts.items()))}")

    bad_scope = []
    bad_url = []
    for row in posts:
        account = str(row.get("account_handle") or "")
        expected_scope = "docmap" if account == "docmap" else f"peer:{account}"
        if not account or row.get("owner_scope") != expected_scope:
            bad_scope.append(str(row.get("platform_post_id")))
        url = str(row.get("post_url") or "")
        if url and f"/@{account}/" not in url:
            bad_url.append(str(row.get("platform_post_id")))

    if bad_scope or bad_url:
        print(
            "INVALID TikTok isolation: "
            f"bad_scope={len(bad_scope)} bad_url={len(bad_url)}"
        )
        errors += 1
    else:
        print("OK  TikTok account_handle, owner_scope and post_url agree")

    embedding_counts = Counter(
        str(row.get("owner_scope") or "<missing>")
        for row in fetch_all("document_embeddings", "owner_scope")
    )
    print(f"OK  embedding scope counts: {dict(sorted(embedding_counts.items()))}")
except Exception as exc:  # noqa: BLE001
    print(f"INVALID account isolation audit: {exc}")
    errors += 1

try:
    client.rpc(
        "match_documents",
        {
            "query_embedding": [0.0] * 1536,
            "match_count": 1,
            "filter_type": None,
            "max_sensitivity": "confidential",
            # Required since sql/013: the unscoped overloads were dropped so that
            # peer-library chunks cannot leak into DocMap retrieval.
            "filter_owner_scope": "docmap",
        },
    ).execute()
    print("OK  match_documents RPC")
except Exception as exc:  # noqa: BLE001
    print(f"MISSING match_documents: {exc}")
    errors += 1

sys.exit(1 if errors else 0)
