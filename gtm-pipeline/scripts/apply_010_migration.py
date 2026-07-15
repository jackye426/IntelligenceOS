"""Apply sql/010_gtm_durable_jobs.sql via Supabase pooler."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import quote, urlparse, urlunparse

from gtm_pipeline import config  # noqa: F401 — load dotenv

import psycopg

SQL_PATH = Path(__file__).resolve().parents[2] / "sql" / "010_gtm_durable_jobs.sql"
PROJECT = "oewczjseteyvyvikxxaz"


def main() -> int:
    raw = os.environ.get("DATABASE_URL") or ""
    if not raw:
        print("DATABASE_URL missing", file=sys.stderr)
        return 1
    # Password may contain [...] which breaks urlparse host detection.
    if raw.startswith("postgresql://") or raw.startswith("postgres://"):
        rest = raw.split("://", 1)[1]
        if "@" in rest:
            creds, hostpart = rest.rsplit("@", 1)
            if ":" in creds:
                user, password = creds.split(":", 1)
            else:
                user, password = creds, ""
            host_only = hostpart.split("/")[0].split(":")[0]
        else:
            print("unparseable DATABASE_URL", file=sys.stderr)
            return 1
    else:
        print("unexpected DATABASE_URL scheme", file=sys.stderr)
        return 1

    pool_user = user if "." in user else f"postgres.{PROJECT}"
    sql = SQL_PATH.read_text(encoding="utf-8")

    for region in ("eu-west-1", "eu-central-1", "us-east-1"):
        host = f"aws-0-{region}.pooler.supabase.com"
        for port in (6543, 5432):
            netloc = f"{pool_user}:{quote(password, safe='')}@{host}:{port}"
            url = urlunparse(("postgresql", netloc, "/postgres", "", "", ""))
            try:
                with psycopg.connect(url, connect_timeout=10) as conn:
                    print(f"CONNECTED {host}:{port} (orig_host={host_only})")
                    conn.execute(sql)
                    conn.commit()
                print("migration_applied")
                return 0
            except Exception as exc:  # noqa: BLE001
                print(f"fail {host}:{port} {type(exc).__name__}: {exc}")
    print("ALL_FAILED", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
