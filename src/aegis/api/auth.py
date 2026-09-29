from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Final

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from aegis.settings import settings

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
_TOKEN_VERSION: Final = "a1"


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=512)


class Identity(BaseModel):
    email: str
    name: str
    role: str
    organization: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: int
    identity: Identity


def _identity() -> Identity:
    return Identity(
        email=settings.auth_email,
        name=settings.auth_display_name,
        role=settings.auth_role,
        organization=settings.auth_organization,
    )


def _b64url_decode(segment: str) -> bytes:
    padding = "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(segment + padding)


def _sign(payload: dict[str, object]) -> str:
    body = (
        base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode())
        .decode()
        .rstrip("=")
    )
    signature = hmac.new(settings.auth_secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{_TOKEN_VERSION}.{body}.{signature}"


def issue_access_token() -> tuple[str, int]:
    expires_at = int(time.time()) + settings.auth_session_ttl_s
    token = _sign({"sub": settings.auth_email, "role": settings.auth_role, "exp": expires_at})
    return token, expires_at


def validate_access_token(token: str) -> Identity | None:
    try:
        version, body, signature = token.split(".", 2)
        if version != _TOKEN_VERSION:
            return None
        expected = hmac.new(
            settings.auth_secret.encode(), body.encode(), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return None
        payload = json.loads(_b64url_decode(body).decode())
        if int(payload["exp"]) < int(time.time()):
            return None
        if payload["sub"] != settings.auth_email:
            return None
        return _identity()
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest) -> LoginResponse:
    email = payload.email.strip().lower()
    expected = settings.auth_email.strip().lower()
    if not hmac.compare_digest(email, expected) or not hmac.compare_digest(
        payload.password, settings.auth_password
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid corporate credentials"
        )
    token, expires_at = issue_access_token()
    return LoginResponse(access_token=token, expires_at=expires_at, identity=_identity())


@router.get("/me", response_model=Identity)
def me() -> Identity:
    # The route is protected by the application authentication middleware.
    return _identity()
