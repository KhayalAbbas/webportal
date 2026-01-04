"""
Deterministic JSON serialization utilities.

Used for hashing enrichment payloads to enforce idempotency.
"""

import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any


def _canonical_default(value: Any) -> Any:
    """Serialize unsupported types into stable JSON-friendly values."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, set):
        return sorted(value)
    raise TypeError(f"Type {type(value)} not serializable")


def canonical_dumps(value: Any) -> str:
    """Return deterministic JSON with sorted keys and tight separators."""
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=_canonical_default,
        ensure_ascii=True,
    )


def canonical_hash(value: Any) -> str:
    """Compute SHA-256 hash of canonical JSON representation."""
    return hashlib.sha256(canonical_dumps(value).encode("utf-8")).hexdigest()