"""Token validation.

* ``entra``: RS256 tokens issued by Microsoft Entra ID, keys fetched from the tenant's JWKS endpoint, audience and
  issuer enforced. Roles come from the ``roles`` claim (app roles); the claims-tenant comes from ``tenant_id``.
* ``dev``: HS256 tokens signed with a local secret, for laptops and tests. Refused when ``environment=prod``.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

import jwt
from fastapi import Depends, Header, HTTPException, status

from claimlens.container import Container
from claimlens.domain.models import Role
from claimlens.security import safe_id
from claimlens.services import Principal
from claimlens_api.deps import get_container


@lru_cache
def _jwks(tenant: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(
        f"https://login.microsoftonline.com/{tenant}/discovery/v2.0/keys", cache_keys=True
    )


def _decode(token: str, c: Container) -> dict[str, Any]:
    s = c.settings
    if s.auth_mode == "dev":
        return jwt.decode(token, s.dev_jwt_secret, algorithms=["HS256"], audience="claimlens-dev")
    key = _jwks(s.entra_tenant_id).get_signing_key_from_jwt(token).key
    return jwt.decode(
        token,
        key,
        algorithms=["RS256"],
        audience=s.entra_audience,
        issuer=f"https://login.microsoftonline.com/{s.entra_tenant_id}/v2.0",
        options={"require": ["exp", "iat", "aud", "iss"]},
    )


def principal_from_claims(claims: dict[str, Any]) -> Principal:
    roles = [r for r in claims.get("roles", []) if r in {x.value for x in Role}]
    if len(roles) != 1:
        raise ValueError("token must carry exactly one claimlens role")
    subject = str(claims.get("oid") or claims.get("sub") or "")
    tenant = str(claims.get("tenant_id") or "")
    return Principal(
        subject=safe_id(subject, "subject"),
        tenant_id=safe_id(tenant, "tenant"),
        role=Role(roles[0]),
    )


def current_principal(
    authorization: str | None = Header(default=None), c: Container = Depends(get_container)
) -> Principal:
    unauthorized = HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        "invalid or missing token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not authorization or not authorization.lower().startswith("bearer "):
        raise unauthorized
    try:
        return principal_from_claims(_decode(authorization[7:].strip(), c))
    except (jwt.PyJWTError, ValueError):
        raise unauthorized from None
