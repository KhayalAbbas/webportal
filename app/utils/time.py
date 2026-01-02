from datetime import datetime, timezone


def utc_now() -> datetime:
    """Return a timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    """Return an ISO 8601 string for the current UTC time."""
    return utc_now().isoformat()
