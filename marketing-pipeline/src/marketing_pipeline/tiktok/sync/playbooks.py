"""Embed marketing playbooks and comment digest into document_embeddings."""

from __future__ import annotations

import re
import uuid
from pathlib import Path

from marketing_pipeline import config
from marketing_pipeline.shared.embeddings import upsert_embedding_chunks

PLAYBOOK_ENTITY = "marketing_playbook"
DIGEST_ENTITY = "marketing_comment_digest"
DIGEST_ENTITY_ID = str(uuid.uuid5(uuid.NAMESPACE_URL, "tiktok-comments-digest:v1"))


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not match:
        return {}, text
    meta: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            meta[key.strip()] = value.strip()
    body = text[match.end() :]
    return meta, body


def _embed_markdown_file(path: Path, *, slug: str, dry_run: bool) -> int:
    meta, body = _parse_frontmatter(path.read_text(encoding="utf-8"))
    status = meta.get("status", "approved")
    if status == "draft":
        return 0
    if "_drafts" in path.parts:
        return 0

    entity_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"playbook:{slug}"))
    if dry_run:
        return 1
    return upsert_embedding_chunks(
        entity_type=PLAYBOOK_ENTITY,
        entity_id=entity_id,
        text=body.strip(),
        source_table="marketing_playbooks",
        source_title=path.name,
        source_url=None,
        metadata={"slug": slug, "status": status, "source": "marketing_pipeline"},
    )


def sync_playbooks(*, dry_run: bool = False, skip_embed: bool = False) -> dict[str, int]:
    counts = {"playbooks": 0, "digest_chunks": 0}

    if skip_embed:
        return counts

    if config.PLAYBOOKS_DIR.exists():
        for path in sorted(config.PLAYBOOKS_DIR.rglob("*.md")):
            if path.name.startswith("."):
                continue
            slug = str(path.relative_to(config.PLAYBOOKS_DIR)).replace("\\", "/")
            written = _embed_markdown_file(path, slug=slug, dry_run=dry_run)
            if written:
                counts["playbooks"] += 1

    digest = config.ALL_COMMENTS_TXT
    if digest.exists() and not dry_run:
        counts["digest_chunks"] = upsert_embedding_chunks(
            entity_type=DIGEST_ENTITY,
            entity_id=DIGEST_ENTITY_ID,
            text=digest.read_text(encoding="utf-8"),
            source_table="marketing_playbooks",
            source_title="ALL_COMMENTS.txt",
            source_url=None,
            metadata={"source": "marketing_pipeline"},
        )
    elif digest.exists():
        counts["digest_chunks"] = 1

    return counts
