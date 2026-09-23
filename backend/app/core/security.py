"""
Baseline auth for the demo: a single shared bearer token from settings.

This intentionally is NOT a full multi-tenant auth system — the spec asks
for "basic authentication or access control for uploaded knowledge bases
if the demo supports multiple users." Phase 6 (production hardening) is
where this gets replaced with per-user JWTs and per-document ACLs without
touching any other layer, because every route depends on `require_auth`
rather than checking tokens inline.
"""

from fastapi import Header, HTTPException, status

from app.config import settings


def require_auth(authorization: str | None = Header(default=None)) -> None:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed Authorization header.",
        )
    token = authorization.removeprefix("Bearer ").strip()
    if token != settings.api_auth_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token.")
