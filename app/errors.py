"""Structured error helpers for API responses."""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import Request
from fastapi.responses import JSONResponse


def build_error_payload(code: str, message: str, details: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    payload = {"error": {"code": code, "message": message}}
    if details is not None:
        payload["error"]["details"] = details
    return payload


class AppError(Exception):
    """Application-scoped error for standardized API responses."""

    def __init__(self, status_code: int, code: str, message: str, details: Optional[Dict[str, Any]] = None):
        self.status_code = status_code
        self.payload = build_error_payload(code, message, details)


async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content=exc.payload)


def build_error(code: str, message: str, details: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Alias wrapper to match Phase 9.0 contract."""
    return build_error_payload(code, message, details)


def raise_app_error(status_code: int, code: str, message: str, details: Optional[Dict[str, Any]] = None) -> None:
    """Raise an AppError with a standardized error shape."""
    raise AppError(status_code, code, message, details)


def http_error(status_code: int, code: str, message: str, details: Optional[Dict[str, Any]] = None) -> None:
    """Alias wrapper to raise standardized errors."""
    raise_app_error(status_code, code, message, details)
