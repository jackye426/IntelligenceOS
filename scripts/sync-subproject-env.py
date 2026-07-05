#!/usr/bin/env python3
"""Copy rotated keys from root .env.local into subproject .env files.

Preserves project-specific vars (paths, models, tuning). Does not commit anything.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def parse_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, _, v = s.partition("=")
        out[k.strip()] = v.strip()
    return out


def format_env(lines: list[str]) -> str:
    return "\n".join(lines).rstrip() + "\n"


def pooler_url(direct: str, project_ref: str = "oewczjseteyvyvikxxaz") -> str:
    """Build Supabase pooler URL from direct postgres URL."""
    m = re.match(r"postgresql://postgres:([^@]+)@db\.([^.]+)\.supabase\.co", direct)
    if not m:
        return ""
    password, ref = m.group(1), m.group(2)
    password = password.strip("[]")
    return (
        f"postgresql://postgres.{ref}:{password}"
        f"@aws-1-eu-north-1.pooler.supabase.com:5432/postgres"
    )


def main() -> None:
    local = parse_env(ROOT / ".env.local")
    if not local:
        raise SystemExit("Root .env.local missing or empty")

    supabase_url = (local.get("SUPABASE_URL") or local.get("NEXT_PUBLIC_SUPABASE_URL") or "").strip()
    service_key = (
        local.get("SUPABASE_SERVICE_ROLE_KEY")
        or local.get("SUPABASE_KEY")
        or ""
    ).strip()
    openrouter = (local.get("OPENROUTER_API_KEY") or "").strip()
    database_url = (local.get("DATABASE_URL") or "").strip()
    database_url = database_url.replace(":[", ":").replace("]@", "@")  # [pass] notation
    pooler = pooler_url(database_url) if database_url else ""

    if not supabase_url or not service_key or not openrouter:
        raise SystemExit("Missing SUPABASE_URL, service key, or OPENROUTER_API_KEY in .env.local")

    # --- Clinic sales agent ---
    clinic_path = ROOT / "Clinic sales agent" / ".env"
    clinic_lines = [
        "# Synced from root .env.local — do not commit",
        f"OPENROUTER_API_KEY={openrouter}",
        "",
        "GOOGLE_CREDENTIALS_PATH=credentials/gmail-credentials.json",
        "GOOGLE_TOKEN_PATH=credentials/token.json",
        "",
        f"NEXT_PUBLIC_SUPABASE_URL={supabase_url}",
        f"SUPABASE_KEY={service_key}",
        "SUPABASE_PRACTITIONERS_TABLE=integrated_practitioner_with_phin",
    ]
    if database_url:
        clinic_lines += [
            f"supabase_database_url={database_url}",
            f"SUPABASE_DATABASE_POOLER_URL={pooler}",
        ]
    clinic_path.write_text(format_env(clinic_lines), encoding="utf-8")
    print(f"Updated {clinic_path.relative_to(ROOT)}")

    # --- Doctors Sales Agent (preserve local paths + tuning) ---
    doc_path = ROOT / "Doctors Sales Agent" / ".env"
    existing = parse_env(doc_path)
    keep = [
        "SUGGESTED_DOCTORS_PATH",
        "PRACTITIONERS_PATH",
        "HISTORY_PATH",
        "MODEL",
        "FUZZY_THRESHOLD",
        "COOLDOWN_DAYS",
        "MEETING_LINK",
        "GOOGLE_CREDENTIALS_PATH",
        "GOOGLE_TOKEN_PATH",
    ]
    doc_lines = []
    for key in keep:
        if existing.get(key):
            doc_lines.append(f"{key}={existing[key]}")
    doc_lines += [
        "",
        "# Supabase + OpenRouter synced from root .env.local",
        f"SUPABASE_URL={supabase_url}",
        f"NEXT_PUBLIC_SUPABASE_URL={supabase_url}",
        f"SUPABASE_KEY={service_key}",
        "SUPABASE_PRACTITIONERS_TABLE=integrated_practitioner_with_phin",
        f"OPENROUTER_API_KEY={openrouter}",
    ]
    if database_url:
        doc_lines += [
            f"supabase_database_url={database_url}",
            f"SUPABASE_DATABASE_POOLER_URL={pooler}",
        ]
    doc_path.write_text(format_env(doc_lines), encoding="utf-8")
    print(f"Updated {doc_path.relative_to(ROOT)}")

    # --- Carousel agents V2 ---
    carousel_path = ROOT / "Carousel agents V2" / ".env"
    carousel_path.write_text(
        format_env([f"OPENROUTER_API_KEY={openrouter}"]),
        encoding="utf-8",
    )
    print(f"Updated {carousel_path.relative_to(ROOT)}")

    # --- Negative Review analysis ---
    neg_path = ROOT / "Negative Review analysis" / ".env"
    neg_path.write_text(
        format_env([f"OPENROUTER_API_KEY={openrouter}"]),
        encoding="utf-8",
    )
    print(f"Updated {neg_path.relative_to(ROOT)}")

    print("Done. Gmail token.json files unchanged — re-auth if Gmail fails.")


if __name__ == "__main__":
    main()
