#!/usr/bin/env python3
"""Relink orphaned evidence rows to source_documents by normalized URL.

This script repairs non-manual evidence that lost source_document_id during
migration. It matches company_prospect_evidence rows (with source_url set and
no source_document_id) to source_documents in the same tenant/run using a
normalized URL key. When a match is found, it updates source_document_id and
source_content_hash.

Usage:
    python scripts/maintenance/relink_evidence_by_url.py

Environment variables (same as app/database defaults):
    DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD
"""

import os
from typing import Dict, Tuple
from urllib.parse import urlparse, unquote

import psycopg2
from dotenv import load_dotenv


def normalize_url(url: str) -> str:
    """Normalize URLs for matching (scheme/host lower, trim ports/slash, sorted query)."""
    if not url:
        return ""

    parsed = urlparse(url.strip())
    if not parsed.scheme or not parsed.netloc:
        return ""

    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()

    # Remove default ports
    if scheme == "http" and netloc.endswith(":80"):
        netloc = netloc[:-3]
    if scheme == "https" and netloc.endswith(":443"):
        netloc = netloc[:-4]

    path = unquote(parsed.path or "/")
    path = path.rstrip("/") or "/"

    query = parsed.query
    if query:
        parts = sorted([p for p in query.split("&") if p])
        query = "&".join(parts)

    normalized = f"{scheme}://{netloc}{path}"
    if query:
        normalized = f"{normalized}?{query}"
    return normalized


def connect_db():
    load_dotenv()
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", 5432),
        database=os.getenv("DB_NAME", "ats_db"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", "postgres"),
    )


def main():
    conn = connect_db()
    cur = conn.cursor()

    print("=== Relinking orphaned evidence by URL ===")

    cur.execute(
        """
        SELECT cpe.id, cpe.tenant_id, cp.company_research_run_id, cpe.source_url
        FROM company_prospect_evidence cpe
        JOIN company_prospects cp ON cp.id = cpe.company_prospect_id
        WHERE cpe.source_document_id IS NULL
          AND cpe.source_url IS NOT NULL
          AND cpe.source_type != 'manual_list'
        """
    )
    orphan_rows = cur.fetchall()
    print(f"Found {len(orphan_rows)} orphaned evidence rows with URLs.")

    cur.execute(
        """
        SELECT id, tenant_id, company_research_run_id, url, content_hash
        FROM source_documents
        WHERE url IS NOT NULL
        """
    )
    doc_rows = cur.fetchall()
    print(f"Loaded {len(doc_rows)} source_documents with URLs for matching.")

    doc_index: Dict[Tuple[str, str, str], Tuple[str, str]] = {}
    for doc_id, tenant_id, run_id, url, content_hash in doc_rows:
        normalized = normalize_url(url)
        if not normalized:
            continue
        key = (str(tenant_id), str(run_id), normalized)
        doc_index[key] = (str(doc_id), content_hash)

    matched = 0
    updated = 0
    missing = 0
    missing_samples = []

    for evidence_id, tenant_id, run_id, src_url in orphan_rows:
        normalized = normalize_url(src_url)
        key = (str(tenant_id), str(run_id), normalized)
        if not normalized or key not in doc_index:
            missing += 1
            if len(missing_samples) < 5:
                missing_samples.append((str(evidence_id), str(tenant_id), str(run_id), src_url))
            continue

        matched += 1
        doc_id, content_hash = doc_index[key]
        cur.execute(
            """
            UPDATE company_prospect_evidence
            SET source_document_id = %s,
                source_content_hash = %s
            WHERE id = %s
            """,
            (doc_id, content_hash, evidence_id),
        )
        updated += cur.rowcount

    conn.commit()
    print(f"Matched {matched} evidence rows; updated {updated} records.")
    print(f"Unmatched: {missing}")
    if missing_samples:
        print("Sample unmatched evidence (id, tenant_id, run_id, url):")
        for sample in missing_samples:
            print(f"  {sample}")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
