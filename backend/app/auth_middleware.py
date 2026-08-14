"""Logto OIDC JWT 验证：从 Authorization Bearer token 提取用户 sub。

Logto SPA 使用 PKCE，前端拿到 id_token/access_token 后通过 Bearer 头传给后端。
后端用 Logto JWKS 公钥验证签名，提取 sub 作为 user_id。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import jwt
from jwt import PyJWKClient
from fastapi import Header, HTTPException, status


@dataclass
class LogtoConfig:
    endpoint: str
    app_id: str


# Logto Cloud signs JWTs with EC keys (ES384); legacy installs may use RS256.
_LOGTO_JWT_ALGORITHMS = ("RS256", "RS384", "RS512", "ES256", "ES384", "ES512")


def _load_logto_config() -> LogtoConfig | None:
    endpoint = os.environ.get("LOGTO_ENDPOINT", "").strip()
    app_id = os.environ.get("LOGTO_APP_ID", "").strip()
    if not endpoint or not app_id:
        return None
    return LogtoConfig(endpoint=endpoint, app_id=app_id)


@lru_cache(maxsize=1)
def _get_jwks_client(endpoint: str) -> PyJWKClient:
    """Create a PyJWKClient that fetches and caches JWKS from Logto."""
    url = f"{endpoint.rstrip('/')}/oidc/jwks"
    return PyJWKClient(url, cache_keys=True, lifespan=3600)


def _decode_token(token: str, config: LogtoConfig) -> dict[str, Any]:
    """Verify JWT signature and return claims."""
    try:
        unverified = jwt.decode(token, options={"verify_signature": False})
        issuer = unverified.get("iss", f"{config.endpoint.rstrip('/')}/oidc")
        client = _get_jwks_client(config.endpoint)
        signing_key = client.get_signing_key_from_jwt(token)
        header_alg = jwt.get_unverified_header(token).get("alg")
        algorithms = (
            [header_alg]
            if header_alg in _LOGTO_JWT_ALGORITHMS
            else list(_LOGTO_JWT_ALGORITHMS)
        )
        # Verify audience against this app's client_id when the token carries one.
        # This prevents a token minted for a different Logto app from being used here.
        expected_aud = config.app_id
        decoded = jwt.decode(
            token,
            key=signing_key.key,
            algorithms=algorithms,
            audience=expected_aud,
            issuer=issuer,
            options={"verify_aud": True},
        )
        return decoded
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="token expired",
        )
    except jwt.InvalidAudienceError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid token audience",
        )
    except jwt.InvalidIssuerError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid token issuer",
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid token",
        )
    except Exception as exc:
        # Network errors, JWKS fetch failures, key parsing errors
        if "jwks" in str(exc).lower() or "fetch" in str(exc).lower():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="auth service temporarily unavailable",
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="token verification failed",
        )


def _extract_user_id(authorization: str | None) -> str | None:
    """Core extraction logic. Returns sub or None (anonymous)."""
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    token = authorization.split(" ", 1)[1].strip()
    config = _load_logto_config()
    if config is None:
        return None
    claims = _decode_token(token, config)
    return claims.get("sub")


def get_current_user_id(authorization: str | None = Header(default=None)) -> str | None:
    """Optional auth dependency. Returns user_id or None (anonymous browse)."""
    try:
        return _extract_user_id(authorization)
    except HTTPException:
        # Invalid/expired Bearer on optional endpoints → treat as anonymous.
        return None


def require_current_user_id(authorization: str | None = Header(default=None)) -> str:
    """Required auth dependency. Raises 401 if not authenticated."""
    sub = _extract_user_id(authorization)
    if not sub:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="authentication required",
        )
    return sub
