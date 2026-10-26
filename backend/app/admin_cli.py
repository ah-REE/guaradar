"""Bootstrap and administration CLI (shell access required).

    # create the first admin — the only way an admin account can come into existence
    python -m app.admin_cli create-user --email ops@example.com --role admin

    # add an operator
    python -m app.admin_cli create-user --email field@example.com --role operator

    # inspect who exists (roles and consent state only, never hashes)
    python -m app.admin_cli list-users

WHY THIS IS A CLI AND NOT AN ENDPOINT
  The brief requires real role-based authorization. The simplest way to guarantee that no HTTP
  caller can ever mint an admin is for **no endpoint to exist** that grants a role. Creating one
  therefore requires shell access to the server, which is a materially higher bar than a request
  with a bearer token.

  `POST /api/auth/register` hardcodes `role='public'` and has no role field. A test proves an
  attacker cannot escalate by adding one.

PASSWORD INPUT
  The password is read from stdin (or a prompt), never from an argument, so it does not land in
  shell history or in `ps` output.
"""

from __future__ import annotations

import argparse
import getpass
import sys

from app.auth import ROLE_ORDER, AuthError, audit, create_user
from app.store import connect, init_db


def _read_password() -> str:
    if sys.stdin.isatty():
        first = getpass.getpass("password: ")
        second = getpass.getpass("repeat password: ")
        if first != second:
            print("passwords do not match", file=sys.stderr)
            raise SystemExit(2)
        return first
    # piped: read a single line, which lets a script feed it without echoing
    return sys.stdin.readline().rstrip("\n")


def cmd_create_user(args: argparse.Namespace) -> int:
    if args.role not in ROLE_ORDER:
        print(f"role must be one of {ROLE_ORDER}", file=sys.stderr)
        return 2
    init_db()
    password = _read_password()
    try:
        user = create_user(args.email, password, role=args.role)
    except AuthError as exc:
        print(f"failed: {exc}", file=sys.stderr)
        return 1
    audit(None, "user.bootstrap", subject=user.id, detail=f"role={user.role} via=cli")
    print(f"created {user.email} with role {user.role}")
    if user.role != "public":
        print("  an admin account exists now; sign in at / and use the Admin tab")
    return 0


def cmd_list_users(_: argparse.Namespace) -> int:
    init_db()
    with connect() as conn:
        rows = conn.execute(
            "select email, role, sms_opt_in, phone_e164, disabled, created_at "
            "from users order by created_at"
        ).fetchall()
    if not rows:
        print("no users yet")
        return 0
    print(f"{'email':34} {'role':10} {'sms':4} {'disabled':9} created")
    for r in rows:
        phone = "set" if r["phone_e164"] else "-"
        print(
            f"{r['email']:34} {r['role']:10} "
            f"{('yes/' + phone) if r['sms_opt_in'] else 'no':8} "
            f"{'yes' if r['disabled'] else 'no':9} {r['created_at'][:19]}"
        )
    return 0


def cmd_disable_user(args: argparse.Namespace) -> int:
    init_db()
    with connect() as conn:
        row = conn.execute("select id from users where email = ?", (args.email,)).fetchone()
        if not row:
            print("no such user", file=sys.stderr)
            return 1
        conn.execute("update users set disabled = 1 where id = ?", (row["id"],))
        conn.execute("delete from sessions where user_id = ?", (row["id"],))
    audit(None, "user.disable", subject=row["id"], detail="via=cli")
    print(f"disabled {args.email} and revoked its sessions")
    return 0


def cmd_sms_config(_: argparse.Namespace) -> int:
    """Report whether SMS credentials are present. Never prints their values."""
    from app.sms.gateway import describe_config

    cfg = describe_config()
    print(f"mode: {cfg['mode']}")
    for key in ("username_set", "password_set", "device_id_set", "base_url_set"):
        print(f"  {key}: {cfg[key]}")
    if not cfg["configured"]:
        print("\nSMS is in DRY-RUN: no message can leave this machine.")
        print("To enable real sending, set these server-side and restart:")
        for name in cfg["required_env"]:
            print(f"  {name}")
        for name in cfg["optional_env"]:
            print(f"  {name}  (optional)")
        print("\nThe account credentials come from the SMS Gateway app/web dashboard;")
        print("they are exchanged for a JWT at send time and are never exposed to the browser.")
    else:
        print("\ncredentials are present; sending would hit the live gateway")
        print("NOTE: a successful send still requires a paired Android device online.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Guaradar administration CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("create-user", help="create a user with an explicit role")
    p.add_argument("--email", required=True)
    p.add_argument("--role", default="public", choices=ROLE_ORDER)
    p.set_defaults(func=cmd_create_user)

    p = sub.add_parser("list-users", help="list accounts (no password material)")
    p.set_defaults(func=cmd_list_users)

    p = sub.add_parser("disable-user", help="disable an account and revoke its sessions")
    p.add_argument("--email", required=True)
    p.set_defaults(func=cmd_disable_user)

    p = sub.add_parser("sms-config", help="report SMS configuration state")
    p.set_defaults(func=cmd_sms_config)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
