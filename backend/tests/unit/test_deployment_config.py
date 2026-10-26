"""Tests for deployment configuration: cookie flags, CORS allow-list, and the blueprint.

These exist because the failure modes here are SILENT. A non-Secure cookie on an https origin
does not raise — sign-in appears to succeed and then does not stick. A CORS list missing the
frontend origin does not raise either; every browser request just fails. Neither shows up in the
existing 841 tests, which all run against localhost.

What is asserted:
  * the cookie flag is off by default (so local http works) and on when configured
  * a malformed flag fails loudly rather than quietly leaving cookies insecure
  * the CORS list never accepts a wildcard, and accepts explicit origins
  * `render.yaml` is valid YAML and carries the variables the app actually reads
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]
ROOT = BACKEND.parent
APP = BACKEND / "app"


def run_python(code: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    """Run a snippet in a fresh interpreter, so module-level env reads happen for real.

    Necessary because `COOKIE_SECURE` and the CORS list are computed at import time; patching
    `os.environ` afterwards would test nothing.
    """
    full_env = {**os.environ, "GUARADAR_DB_PATH": os.path.join("/tmp", "cfg-test.db")}
    for key in ("GUARADAR_COOKIE_SECURE", "GUARADAR_CORS_ORIGINS"):
        full_env.pop(key, None)
    if env:
        full_env.update(env)
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        env=full_env,
        timeout=120,
    )


# ===========================================================================
# 1. Cookie flags
# ===========================================================================


def test_cookie_is_not_secure_by_default() -> None:
    """Local development runs over http, where a Secure cookie is rejected."""
    out = run_python("from app.api.auth_routes import COOKIE_SECURE; print(COOKIE_SECURE)")
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "False"


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
def test_cookie_is_secure_when_enabled(value: str) -> None:
    out = run_python(
        "from app.api.auth_routes import COOKIE_SECURE; print(COOKIE_SECURE)",
        env={"GUARADAR_COOKIE_SECURE": value},
    )
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "True"


@pytest.mark.parametrize("value", ["0", "false", "no", "off"])
def test_cookie_is_insecure_when_explicitly_disabled(value: str) -> None:
    out = run_python(
        "from app.api.auth_routes import COOKIE_SECURE; print(COOKIE_SECURE)",
        env={"GUARADAR_COOKIE_SECURE": value},
    )
    assert out.stdout.strip() == "False"


def test_malformed_cookie_flag_fails_loudly() -> None:
    """A typo must not silently leave production cookies insecure."""
    out = run_python(
        "from app.api.auth_routes import COOKIE_SECURE; print(COOKIE_SECURE)",
        env={"GUARADAR_COOKIE_SECURE": "maybe"},
    )
    assert out.returncode != 0
    assert "GUARADAR_COOKIE_SECURE" in (out.stderr + out.stdout)


def test_login_and_register_share_one_cookie_helper() -> None:
    """Two call sites that could drift is how an intermittent auth bug happens."""
    text = (APP / "api" / "auth_routes.py").read_text(encoding="utf-8")
    assert "def set_session_cookie" in text
    # Exactly ONE `set_cookie(` call may exist in the module, and it must be the one inside the
    # helper. The helper itself calls `response.set_cookie(...)`, so counting occurrences is the
    # right check — excluding the helper's own line would be wrong.
    assert text.count("set_cookie(") == 1, (
        f"expected one central call, found {text.count('set_cookie(')}"
    )
    # And both auth flows go through it.
    assert text.count("set_session_cookie(response, token)") == 2


def test_cookie_is_httponly_and_lax() -> None:
    """httponly keeps it away from JS; Lax survives the proxy hop and blocks cross-site POST."""
    text = (APP / "api" / "auth_routes.py").read_text(encoding="utf-8")
    start = text.index("def set_session_cookie")
    # Slice to the end of the function: the next top-level `def` is a reliable terminator.
    rest = text[start + 10 :]
    nxt = rest.find("\ndef ")
    helper = rest[: nxt if nxt != -1 else 800]
    assert "httponly=True" in helper
    assert 'samesite="lax"' in helper


# ===========================================================================
# 2. CORS
# ===========================================================================


def test_cors_always_includes_local_dev() -> None:
    """A deployed API must still be usable from a developer's machine."""
    out = run_python(
        "from app.api.main import _cors_origins; print(','.join(_cors_origins()))"
    )
    assert out.returncode == 0, out.stderr
    assert "http://localhost:5173" in out.stdout


def test_cors_accepts_explicit_extra_origins() -> None:
    out = run_python(
        "from app.api.main import _cors_origins; print(','.join(_cors_origins()))",
        env={"GUARADAR_CORS_ORIGINS": "https://guaradar.vercel.app,https://example.org/"},
    )
    assert out.returncode == 0, out.stderr
    assert "https://guaradar.vercel.app" in out.stdout
    # A trailing slash is normalised, because browsers never send one in Origin.
    assert "https://example.org" in out.stdout
    assert "https://example.org/" not in out.stdout


def test_cors_refuses_a_wildcard() -> None:
    """`*` with auth cookies is the classic misconfiguration; refuse it at startup."""
    out = run_python(
        "from app.api.main import _cors_origins; _cors_origins()",
        env={"GUARADAR_CORS_ORIGINS": "*"},
    )
    assert out.returncode != 0
    assert "must not contain" in (out.stderr + out.stdout)


def test_credentials_stay_disallowed_cross_origin() -> None:
    """The proxy design makes cookies same-origin, so this must not quietly become True.

    If it ever does, a cross-site page can drive authenticated requests. The deployment shape is
    what makes this safe, so the assertion documents the coupling.
    """
    text = (APP / "api" / "main.py").read_text(encoding="utf-8")
    # The live argument, not a mention in prose. Comments here deliberately NAME the dangerous
    # setting in order to explain why it is avoided, so the check must target the call.
    assert "allow_credentials=False" in text
    assert not re.search(r"^\s*allow_credentials=True", text, re.M)


def test_cors_is_an_allow_list_not_a_pattern() -> None:
    text = (APP / "api" / "main.py").read_text(encoding="utf-8")
    assert "allow_origin_regex" not in text


# ===========================================================================
# 3. Render blueprint
# ===========================================================================


def test_render_blueprint_exists_and_is_valid_yaml() -> None:
    path = ROOT / "render.yaml"
    assert path.exists(), "render.yaml is required for a Render blueprint deploy"
    text = path.read_text(encoding="utf-8")
    # Parsed with the stdlib-adjacent reader the project already depends on via pydantic?
    # No: use PyYAML only if available, otherwise assert structure textually so the test never
    # becomes an undeclared dependency.
    try:
        import yaml  # type: ignore

        doc = yaml.safe_load(text)
        services = doc["services"]
        assert isinstance(services, list) and services
        svc = services[0]
        assert svc["rootDir"] == "backend"
        assert "uvicorn" in svc["startCommand"]
    except ImportError:
        assert "rootDir: backend" in text
        assert "uvicorn" in text


def test_render_blueprint_sets_the_variables_the_app_reads() -> None:
    """A blueprint that omits GUARADAR_COOKIE_SECURE deploys a service where login silently fails."""
    text = (ROOT / "render.yaml").read_text(encoding="utf-8")
    for key in ("GUARADAR_COOKIE_SECURE", "GUARADAR_DB_PATH", "GUARADAR_CORS_ORIGINS"):
        assert key in text, key


def test_render_blueprint_commits_no_secret_values() -> None:
    """Secrets are `sync: false`, so Render prompts in its UI and nothing lands in the repo."""
    text = (ROOT / "render.yaml").read_text(encoding="utf-8")
    for secret in (
        "SUPABASE_SERVICE_ROLE_KEY",
        "OPENTOPOGRAPHY_API_KEY",
        "SENTRY_DSN",
        "GUARADAR_PG_DSN",
    ):
        assert secret in text, secret
    # No `value:` immediately following a secret key.
    for secret in ("GUARADAR_PG_DSN", "SUPABASE_SERVICE_ROLE_KEY", "OPENTOPOGRAPHY_API_KEY"):
        block = re.search(rf"- key: {secret}\n(\s+)value:", text)
        assert block is None, f"{secret} has a committed value"


def test_render_blueprint_says_storage_is_ephemeral() -> None:
    """Render's free disk is ephemeral; the file must not imply durability."""
    text = (ROOT / "render.yaml").read_text(encoding="utf-8").lower()
    assert "ephemeral" in text


# ===========================================================================
# 4. Vercel config
# ===========================================================================


def test_vercel_config_proxies_api() -> None:
    """The whole point of the shape: /api goes to Render so cookies stay same-origin."""
    path = ROOT / "vercel.json"
    assert path.exists()
    import json

    doc = json.loads(path.read_text(encoding="utf-8"))
    rewrites = doc.get("rewrites", [])
    assert any(r.get("source", "").startswith("/api") for r in rewrites), rewrites
    dest = next(r["destination"] for r in rewrites if r["source"].startswith("/api"))
    assert dest.startswith("https://"), dest


def test_vercel_config_has_a_placeholder_that_must_be_replaced() -> None:
    """A placeholder is better than a guessed URL: it fails visibly, and the docs say to change it."""
    import json

    doc = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
    dest = next(r["destination"] for r in doc["rewrites"])
    assert "REPLACE-WITH" in dest.upper(), (
        "the destination should still be a placeholder so it cannot silently target the wrong host"
    )


def test_vercel_build_points_at_the_frontend() -> None:
    import json

    doc = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
    assert doc["outputDirectory"] == "frontend/dist"
    assert "frontend" in doc["buildCommand"]


# ===========================================================================
# 5. Deployment documentation
# ===========================================================================


def test_deployment_doc_exists_and_names_the_required_variables() -> None:
    path = ROOT / "docs" / "DEPLOYMENT.md"
    assert path.exists(), "deployment steps must be written down, not remembered"
    text = path.read_text(encoding="utf-8")
    for name in (
        "GUARADAR_COOKIE_SECURE",
        "GUARADAR_CORS_ORIGINS",
        "GUARADAR_DB_PATH",
        "vercel.json",
        "render.yaml",
    ):
        assert name in text, name


def test_deployment_doc_states_the_ephemeral_storage_limit() -> None:
    text = (ROOT / "docs" / "DEPLOYMENT.md").read_text(encoding="utf-8").lower()
    assert "ephemeral" in text
    # And must not describe SQLite as durable.
    assert "lost on restart" in text or "lost whenever" in text or "does not survive" in text
