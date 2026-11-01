from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from functools import lru_cache

import jwt
from fastapi import HTTPException, Request, status


@dataclass(frozen=True)
class Principal:
    user_id: str
    issuer: str
    subject: str
    email: str | None = None
    is_preview: bool = False


@lru_cache(maxsize=1)
def _jwks_client():
    url = os.getenv("OIDC_JWKS_URL")
    if not url:
        raise RuntimeError("OIDC_JWKS_URL is required when OIDC is enabled")
    return jwt.PyJWKClient(url, cache_jwk_set=True, lifespan=300)


def oidc_enabled() -> bool:
    return bool(os.getenv("OIDC_ISSUER") and os.getenv("OIDC_AUDIENCE") and os.getenv("OIDC_JWKS_URL"))


def verify_bearer_token(token: str) -> Principal:
    issuer = os.getenv("OIDC_ISSUER")
    audience = os.getenv("OIDC_AUDIENCE")
    if not (issuer and audience and os.getenv("OIDC_JWKS_URL")):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "OIDC is not completely configured")
    try:
        signing_key = _jwks_client().get_signing_key_from_jwt(token).key
        claims = jwt.decode(
            token,
            signing_key,
            algorithms=["RS256", "ES256"],
            audience=audience,
            issuer=issuer,
            options={"require": ["exp", "iat", "sub", "iss", "aud"]},
            leeway=30,
        )
    except (jwt.PyJWTError, RuntimeError, ValueError) as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired access token") from exc
    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token subject is missing")
    stable = hashlib.sha256(f"{issuer}\x00{subject}".encode()).hexdigest()
    email = claims.get("email")
    return Principal(
        user_id=stable,
        issuer=issuer,
        subject=subject,
        email=email if isinstance(email, str) else None,
        is_preview=False,
    )


def get_current_principal(request: Request) -> Principal:
    # The Basic-auth identity exists only in the isolated single-operator preview.
    preview = getattr(request.state, "principal", None)
    if preview:
        return Principal(**preview)
    if not oidc_enabled():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Configure OIDC_ISSUER, OIDC_AUDIENCE and OIDC_JWKS_URL for organisation identity",
        )
    authorization = request.headers.get("authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Bearer access token required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return verify_bearer_token(token)
