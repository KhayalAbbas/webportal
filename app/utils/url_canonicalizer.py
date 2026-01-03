"""URL canonicalization utilities for research pipelines."""

from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit


def canonicalize_url(raw_url: str, default_scheme: str = "http") -> str:
    """Return a normalized, deterministic URL for deduping.

    Rules:
    - Add a default scheme when missing.
    - Lowercase scheme/host.
    - Drop query/params/fragment.
    - Remove default ports (80/443) and collapse duplicate slashes.
    - Normalize path to a stable representation without trailing slash (except root).
    """
    if not raw_url or not raw_url.strip():
        raise ValueError("empty_url")

    url_text = raw_url.strip()
    parsed = urlsplit(url_text)

    # Handle bare hosts without scheme (e.g., example.com/path)
    if not parsed.scheme and not parsed.netloc and parsed.path:
        parsed = urlsplit(f"{default_scheme}://{url_text}")

    scheme = (parsed.scheme or default_scheme).lower()
    host = (parsed.hostname or "").lower()
    if not host:
        raise ValueError("invalid_host")

    port = parsed.port
    netloc = host
    if port and not (scheme == "http" and port == 80) and not (scheme == "https" and port == 443):
        netloc = f"{host}:{port}"

    path = parsed.path or "/"
    path = re.sub(r"/+", "/", path)
    if not path.startswith("/"):
        path = f"/{path}"
    # Strip trailing slash unless root
    if path != "/":
        path = path.rstrip("/") or "/"

    normalized = (scheme, netloc, path or "/", "", "")
    return urlunsplit(normalized)
