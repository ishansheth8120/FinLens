"""Token issuance and identity.

`POST /auth/token` with one of the demo users, then send the bearer token to
`/ask`. Two users with different entitlements is the whole point: the same
question against the same data returns different answers.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from finlens.api.auth import DEMO_USERS, PrincipalDep, authenticate, issue_token

router = APIRouter(prefix="/auth", tags=["auth"])


class TokenRequest(BaseModel):
    username: str = Field(examples=["analyst"])
    password: str = Field(examples=["analyst"])


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    role: str
    scope: str


class WhoAmI(BaseModel):
    user_id: str
    role: str
    display_name: str
    unrestricted: bool
    permitted_ciks: list[str]
    scope: str


@router.post("/token", response_model=TokenResponse, summary="Exchange credentials for a token")
def token(request: TokenRequest) -> TokenResponse:
    user = authenticate(request.username, request.password)
    access_token, expires_in = issue_token(user)
    return TokenResponse(
        access_token=access_token,
        expires_in=expires_in,
        role=user.role.value,
        scope=user.display_name,
    )


@router.get("/me", response_model=WhoAmI, summary="The current principal")
def me(principal: PrincipalDep) -> WhoAmI:
    return WhoAmI(
        user_id=principal.user_id,
        role=principal.role.value,
        display_name=principal.display_name,
        unrestricted=principal.unrestricted,
        permitted_ciks=sorted(principal.permitted_ciks),
        scope=principal.scope_description(),
    )


@router.get("/demo-users", summary="The seeded demo principals")
def demo_users() -> list[dict[str, object]]:
    """Listed so the UI can offer a login picker.

    Passwords are printed because these are fixed demo accounts on public data
    with no write access. Do not copy this pattern anywhere real.
    """
    return [
        {
            "username": name,
            "password": name,
            "role": user.role.value,
            "scope": user.display_name,
            "permitted_ciks": list(user.permitted_ciks),
        }
        for name, user in DEMO_USERS.items()
    ]
