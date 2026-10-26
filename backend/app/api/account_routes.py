"""Account-administration API — the backend for the console's Accounts screen.

MOUNTED ON A ROUTER, ALWAYS BEHIND A ROLE DEPENDENCY
  Every handler here depends on `require_admin(...)`, so the role is resolved from the session
  row server-side before the handler body runs. A hidden frontend screen is not the control; this
  is.

TWO GATES, BOTH SERVER-SIDE
  * Route gate — at least `viewer` to read, `operator` to create or manage. Enforced by
    `require_admin`, identical to every other admin route.
  * Rule gate — `app/accounts.py` then refuses any grant at or above the actor's own role, and
    refuses disabling the last usable admin. So an `operator` who reaches `create_account` still
    cannot produce an `admin`.

NO PASSWORD EVER LEAVES
  `change_passphrase` accepts one; nothing returns one. `AccountOut` has no field for it, and the
  database read uses an explicit column list. A test asserts the response body contains no hash
  and no passphrase.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import status as http_status
from pydantic import BaseModel, Field

from app import accounts as accounts_svc
from app import auth as auth_svc
from app.api.auth_routes import require_admin
from app.auth import AuthError, User
from app.accounts import AccountError

admin_accounts_router = APIRouter(prefix="/api/admin/accounts", tags=["admin-accounts"])

_admin_viewer = require_admin("viewer")
_admin_operator = require_admin("operator")


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class AccountOut(BaseModel):
    """One account as the console may see it.

    There is deliberately no passphrase or hash field. The schema is the guarantee: a response
    cannot leak what it has no slot for.
    """

    id: str
    email: str
    role: str
    disabled: bool
    created_at: str
    phone_e164: str | None = None
    sms_opt_in: bool = False
    last_active_at: str | None = None


class AccountListOut(BaseModel):
    schema_version: str = "1"
    accounts: list[AccountOut]
    stats: dict[str, int]
    # What the CALLER may do, decided server-side, so the UI does not have to guess from role
    # strings and cannot disagree with the server about its own permissions.
    can_create: list[str] = Field(
        default_factory=list,
        description="Roles this caller may grant. `admin` is absent for everyone: only the "
        "bootstrap CLI can create an admin.",
    )
    actor_role: str
    notes: list[str] = Field(default_factory=list)


class CreateAccountIn(BaseModel):
    """`extra="forbid"` so a payload cannot smuggle in a field the schema does not offer."""

    email: str = Field(max_length=254)
    passphrase: str = Field(
        max_length=200,
        description="At least 12 characters. Length matters more than symbols.",
    )
    role: Literal["viewer", "operator", "publisher"]

    model_config = {"extra": "forbid"}


class DisableIn(BaseModel):
    disabled: bool
    model_config = {"extra": "forbid"}


class ChangePassphraseIn(BaseModel):
    passphrase: str = Field(max_length=200)
    model_config = {"extra": "forbid"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _out(account: accounts_svc.AccountRow) -> AccountOut:
    return AccountOut(
        id=account.id,
        email=account.email,
        role=account.role,
        disabled=account.disabled,
        created_at=account.created_at,
        phone_e164=account.phone_e164,
        sms_opt_in=account.sms_opt_in,
        last_active_at=account.last_active_at,
    )


def _http(exc: AuthError) -> HTTPException:
    """Translate a rule violation into its documented status code with a stable code."""
    return HTTPException(
        status_code=getattr(exc, "status_code", 400),
        detail={"code": getattr(exc, "code", "account_error"), "message": str(exc)},
    )


def _grantable(actor: User) -> list[str]:
    """Which roles THIS caller may grant, computed from the same rule the write path uses.

    Derived rather than hardcoded, so the form can never offer a role the server would refuse.
    """
    return [
        role
        for role in accounts_svc.CREATABLE_ROLES
        if accounts_svc._rank(role) < accounts_svc._rank(actor.role)
    ]


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


@admin_accounts_router.get("", response_model=AccountListOut)
def list_accounts(
    user: Annotated[User, Depends(_admin_viewer)],
    limit: int = Query(default=200, ge=1, le=500),
) -> AccountListOut:
    accounts = accounts_svc.list_accounts(limit=limit)
    stats = accounts_svc.account_stats()
    return AccountListOut(
        accounts=[_out(a) for a in accounts],
        stats=stats,
        can_create=_grantable(user),
        actor_role=user.role,
        notes=[
            "Roles are fixed when an account is created. There is no way to change a role, so "
            "there is no way to escalate one.",
            "Disabling an account keeps it and its history; nothing is deleted.",
            "Only the bootstrap CLI can create an admin account.",
        ],
    )


@admin_accounts_router.get("/capabilities")
def capabilities(user: Annotated[User, Depends(_admin_viewer)]) -> dict[str, Any]:
    """What this caller may do, for a client that wants it without loading the whole list.

    DECLARED BEFORE `/{user_id}` ON PURPOSE. FastAPI matches routes in declaration order, so a
    dynamic path first would capture the literal "capabilities" and answer 404 "no such account"
    — a confusing failure that looks like a missing feature rather than a routing mistake.
    """
    return {
        "actor_role": user.role,
        "can_create": _grantable(user),
        "bootstrap_only": [accounts_svc.BOOTSTRAP_ONLY_ROLE],
        "creatable_roles": list(accounts_svc.CREATABLE_ROLES),
    }


@admin_accounts_router.get("/{user_id}", response_model=AccountOut)
def get_account(user_id: str, user: Annotated[User, Depends(_admin_viewer)]) -> AccountOut:
    account = accounts_svc.get_account(user_id)
    if account is None:
        raise HTTPException(status_code=404, detail="no such account")
    return _out(account)


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------


@admin_accounts_router.post(
    "",
    response_model=AccountOut,
    status_code=http_status.HTTP_201_CREATED,
    summary="Create a staff account",
)
def create_account(
    payload: CreateAccountIn, user: Annotated[User, Depends(_admin_operator)]
) -> AccountOut:
    """Create a staff account. Cannot create anything at or above the caller's own role."""
    try:
        account, detail = accounts_svc.create_account(
            user, email=payload.email, passphrase=payload.passphrase, role=payload.role
        )
    except AccountError as exc:
        raise _http(exc) from exc
    except AuthError as exc:
        raise _http(exc) from exc

    auth_svc.audit(user, "account.create", subject=account.id, detail=detail)
    return _out(account)


@admin_accounts_router.post("/{user_id}/disabled", response_model=AccountOut)
def set_disabled(
    user_id: str,
    payload: DisableIn,
    user: Annotated[User, Depends(_admin_operator)],
) -> AccountOut:
    """Enable or disable an account.

    A POST with an explicit body rather than a DELETE: disabling is a reversible state change,
    and the route should not look like something that destroys a record.
    """
    try:
        account = accounts_svc.set_disabled(user, user_id, disabled=payload.disabled)
    except AccountError as exc:
        raise _http(exc) from exc

    auth_svc.audit(
        user,
        "account.disable" if payload.disabled else "account.enable",
        subject=user_id,
        detail=f"role={account.role}",
    )
    return _out(account)


@admin_accounts_router.post("/{user_id}/passphrase", response_model=AccountOut)
def change_passphrase(
    user_id: str,
    payload: ChangePassphraseIn,
    user: Annotated[User, Depends(_admin_operator)],
) -> AccountOut:
    """Reset an account's passphrase and revoke its sessions.

    Offered because a staff member who cannot sign in cannot do their job, and the alternative
    is editing the database by hand. The response contains the account, never the passphrase.
    """
    try:
        account = accounts_svc.set_password(
            user, user_id, new_passphrase=payload.passphrase
        )
    except AccountError as exc:
        raise _http(exc) from exc
    except AuthError as exc:
        raise _http(exc) from exc

    auth_svc.audit(user, "account.passphrase_reset", subject=user_id, detail="sessions revoked")
    return _out(account)
