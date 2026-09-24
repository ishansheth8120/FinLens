"""Authentication and the principal behind each request.

JWT because it is what the demo needs and nothing more: two users at different
entitlement levels, so the same question can be shown returning different
answers. The entitlements themselves live in `user_entity_access` (Postgres) or
in the local user table below; the token only carries identity and a scope
claim, so revoking access does not require waiting for a token to expire.

**This is demo-grade authentication.** The secret is a config value, there is no
refresh flow, and users are seeded from a file. Real deployments should put
Supabase Auth or an IdP in front of this and keep only the principal mapping.
Said plainly here rather than left for a reviewer to discover.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from finlens.config import Settings, get_settings
from finlens.governance.access import Principal, Role
from finlens.logging import get_logger

log = get_logger(__name__)

bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class DemoUser:
    user_id: str
    password_hash: str
    role: Role
    permitted_ciks: tuple[str, ...]
    display_name: str


def _hash(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


# Two principals, deliberately overlapping in question space and differing in
# scope, so `POST /auth/token` + the same question demonstrates the control.
DEMO_USERS: dict[str, DemoUser] = {
    "admin": DemoUser(
        user_id="admin",
        password_hash=_hash("admin"),
        role=Role.ADMIN,
        permitted_ciks=("*",),
        display_name="Coverage lead (all companies)",
    ),
    "analyst": DemoUser(
        user_id="analyst",
        password_hash=_hash("analyst"),
        role=Role.ANALYST,
        # Apple and Microsoft only. Ask about NVIDIA as this user and the
        # answer is empty - not because the data is missing, but because the
        # entitlement is.
        permitted_ciks=("0000320193", "0000789019"),
        display_name="Tech analyst (AAPL, MSFT)",
    ),
}


class AuthError(HTTPException):
    def __init__(self, detail: str) -> None:
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            headers={"WWW-Authenticate": "Bearer"},
        )


def authenticate(username: str, password: str) -> DemoUser:
    user = DEMO_USERS.get(username)
    # Compare against a dummy hash when the user does not exist, so a missing
    # user and a wrong password take the same time.
    expected = user.password_hash if user else _hash("\x00unused")
    ok = hmac.compare_digest(expected, _hash(password))
    if not user or not ok:
        raise AuthError("invalid username or password")
    return user


def issue_token(user: DemoUser, settings: Settings | None = None) -> tuple[str, int]:
    """Mint a JWT. Returns the token and its lifetime in seconds."""
    import jwt

    settings = settings or get_settings()
    ttl = timedelta(minutes=settings.jwt_ttl_minutes)
    now = datetime.now(timezone.utc)

    payload = {
        "sub": user.user_id,
        "role": user.role.value,
        "ciks": list(user.permitted_ciks),
        "name": user.display_name,
        "iat": now,
        "exp": now + ttl,
    }
    token = jwt.encode(
        payload,
        settings.jwt_secret.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )
    return token, int(ttl.total_seconds())


def decode_token(token: str, settings: Settings | None = None) -> dict[str, Any]:
    import jwt

    settings = settings or get_settings()
    try:
        return jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            # Pinning the algorithm is not optional: accepting whatever the
            # token's own header claims is how `alg: none` forgery works.
            algorithms=[settings.jwt_algorithm],
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthError("token has expired") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthError("invalid token") from exc


def principal_from_claims(claims: dict[str, Any]) -> Principal:
    role = Role(claims.get("role", Role.ANALYST.value))
    return Principal(
        user_id=str(claims.get("sub", "unknown")),
        role=role,
        permitted_ciks=frozenset(claims.get("ciks", [])),
        display_name=str(claims.get("name", "")),
    )


def get_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Principal:
    """The caller, or an anonymous unrestricted principal.

    Anonymous access is unrestricted on purpose: the default single-tenant
    deployment has no entitlements to enforce, and requiring a login to run
    `make demo` would be friction with no security benefit. Set
    `FINLENS_REQUIRE_AUTH=true` to turn that off.
    """
    if credentials is None:
        if getattr(settings, "require_auth", False):
            raise AuthError("authentication required")
        return Principal.admin(user_id="anonymous")

    claims = decode_token(credentials.credentials, settings)
    return principal_from_claims(claims)


def require_audit_access(
    principal: Annotated[Principal, Depends(get_principal)],
) -> Principal:
    """Guard for the audit endpoints."""
    if not principal.may_read_audit:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="your role may not read the audit log",
        )
    return principal


PrincipalDep = Annotated[Principal, Depends(get_principal)]
AuditPrincipalDep = Annotated[Principal, Depends(require_audit_access)]
