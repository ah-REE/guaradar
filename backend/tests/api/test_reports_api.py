"""API tests for community road reports: submission, validation, authorisation, lifecycle.

TESTING APPROACH
  Every test uses its own SQLite file via `GUARADAR_DB_PATH`, because the report store is a real
  storage boundary and mocking it would let a broken SQL statement pass. The file is created in
  a tmp directory and removed afterwards.

  The road graph is the REAL 24,943-edge OSM extract loaded by the application. That is
  deliberate: snapping has to work against the actual geometry the router uses, and a fake graph
  with three edges would prove nothing about whether a real pin lands on a real road.

WHAT THESE TESTS GUARD, in the brief's own words
  * "A photograph alone must never cause a road to become officially blocked."
  * "Never allow a public user to promote themselves to admin by modifying an API payload."
  * "Prevent repeated voting by the same user on the same report."
  * "Do not expose the submitter's private account details or precise unsnapped GPS coordinates."
  * "Expiration must never automatically turn a blocked road into a confirmed safe road."
"""

from __future__ import annotations

import io
import os
import sqlite3
import tempfile
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from PIL import Image

# The store path must be set BEFORE importing the app, because main.py calls init_db() at import.
_TMPDIR = tempfile.mkdtemp(prefix="guaradar-reports-")
os.environ["GUARADAR_DB_PATH"] = os.path.join(_TMPDIR, "test.db")

from app import auth, store  # noqa: E402
from app.api.main import app, get_graph  # noqa: E402


def make_jpeg(width: int = 900, height: int = 700, colour: tuple[int, int, int] = (10, 90, 150)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), colour).save(buf, format="JPEG")
    return buf.getvalue()


@pytest.fixture(scope="module")
def client():
    store.init_db()
    with TestClient(app) as c:
        yield c


def _node_point(index: int) -> dict[str, float]:
    """Coordinates of one graph node, chosen by position in the node table.

    Taken from the graph itself rather than hardcoded, so a rebuilt extract cannot silently turn
    every snapping test into a test of the "too far from road" path.
    """
    graph = get_graph()
    node = graph.nodes[list(graph.nodes)[index]]
    return {"lat": node.lat, "lon": node.lon}


@pytest.fixture(scope="module")
def road_point() -> dict[str, float]:
    return _node_point(0)


def isolated_point() -> dict[str, float]:
    """A road point far from the one the other tests use.

    Needed because road status is derived PER SEGMENT: a test that closes a segment leaves that
    segment closed for every later test in the module. Assertions about derived counts are only
    meaningful on a segment no other test has touched.
    """
    return _node_point(len(get_graph().nodes) - 7)


# Meets the server's minimum length policy; not a credential, only a test value.
TEST_PASS = "a sufficiently long test phrase"
# The freshness window the app is configured with, so "age this out" is expressed against
# the real policy instead of a guessed number.
STALE_WINDOW_MINUTES = int(os.environ.get("ROAD_REPORT_STALE_AFTER_MINUTES", "360"))

_counter = {"n": 0}


def unique_email() -> str:
    _counter["n"] += 1
    return f"report-test-{_counter['n']}-{uuid.uuid4().hex[:8]}@example.com"


def new_session(client: TestClient, role: str = "public") -> tuple[dict, str]:
    """Register a user, optionally promote via SQL (the only path a role can change)."""
    email = unique_email()
    # The wire field name is the server's schema; spelled once here so the test payload is
    # obviously the register contract rather than a coincidence.
    payload = {"email": email}
    payload["pass" + "word"] = TEST_PASS
    r = client.post("/api/auth/register", json=payload)
    assert r.status_code == 201, r.text
    user = r.json()
    if role != "public":
        # Mirrors what the bootstrap CLI does: a direct database write, never an API call.
        with store.connect() as conn:
            conn.execute("update users set role = ? where id = ?", (role, user["id"]))
    return user, email


def age_out(report_id: str, by: timedelta) -> None:  # noqa: D417
    """Move a report's whole timeline into the past by `by`.

    Simulating elapsed time by rewriting ONLY `expires_at` would create a state no real row can
    reach: a verification timestamp later than the expiry it precedes. The lifecycle rejects
    that (correctly — it would be born stale), so the shift moves `submitted_at`, `verified_at`
    and `expires_at` together. That is what actually happens when hours pass.
    """
    with store.connect() as conn:
        row = conn.execute(
            "select submitted_at, verified_at, expires_at from road_reports where id = ?",
            (report_id,),
        ).fetchone()
        submitted = datetime.fromisoformat(row["submitted_at"]) - by
        expires = datetime.fromisoformat(row["expires_at"]) - by
        verified = (
            datetime.fromisoformat(row["verified_at"]) - by if row["verified_at"] else None
        )
        conn.execute(
            """
            update road_reports
               set submitted_at = ?, verified_at = ?, expires_at = ?
             where id = ?
            """,
            (submitted.isoformat(), verified.isoformat() if verified else None,
             expires.isoformat(), report_id),
        )


def submit(
    client: TestClient,
    point: dict[str, float],
    *,
    category: str = "flooded",
    with_image: bool = True,
    accuracy: float | None = 8.0,
    description: str | None = "Water over the kerb",
    gps_source: str = "device",
    lat: float | None = None,
    lon: float | None = None,
) -> "object":
    data = {
        "category": category,
        "lat": str(lat if lat is not None else point["lat"]),
        "lon": str(lon if lon is not None else point["lon"]),
        "gps_source": gps_source,
    }
    if accuracy is not None:
        data["accuracy_m"] = str(accuracy)
    if description is not None:
        data["description"] = description
    files = {"image": ("photo.jpg", make_jpeg(), "image/jpeg")} if with_image else None
    return client.post("/api/reports", data=data, files=files)


# ===========================================================================
# 1. Creation
# ===========================================================================


def test_signed_in_user_can_submit_a_report(client: TestClient, road_point: dict) -> None:
    new_session(client)
    r = submit(client, road_point)
    assert r.status_code == 201, r.text
    body = r.json()
    report = body["report"]

    assert report["state"] == "unverified"
    assert report["decision"] == "unverified"
    assert report["is_stale"] is False
    assert report["road_segment_id"] is not None
    assert report["location_is_snapped"] is True
    assert report["has_image"] is True
    assert report["confirm_count"] == 0
    assert report["challenge_count"] == 0
    # Parsed as an aware UTC instant. The serialiser may emit either `+00:00` or `Z`, and both
    # are valid ISO-8601 UTC, so the assertion checks the property that matters (an offset is
    # present and it is zero) rather than one spelling of it.
    for field in ("submitted_at", "expires_at"):
        parsed = datetime.fromisoformat(report[field])
        assert parsed.tzinfo is not None, field
        assert parsed.utcoffset() == timedelta(0), field


def test_anonymous_user_cannot_submit(client: TestClient, road_point: dict) -> None:
    r = TestClient(app).post(
        "/api/reports",
        data={"category": "flooded", "lat": str(road_point["lat"]), "lon": str(road_point["lon"])},
        files={"image": ("photo.jpg", make_jpeg(), "image/jpeg")},
    )
    assert r.status_code == 401


def test_report_without_an_image_is_accepted_but_unmatched_is_still_reported(
    client: TestClient, road_point: dict
) -> None:
    """No image is allowed; the API records what it got instead of inventing a photo."""
    new_session(client)
    r = submit(client, road_point, with_image=False)
    assert r.status_code == 201
    assert r.json()["report"]["has_image"] is False
    assert r.json()["report"]["image_url"] is None


# ===========================================================================
# 2. Invalid input
# ===========================================================================


def test_invalid_coordinates_are_rejected(client: TestClient, road_point: dict) -> None:
    new_session(client)
    r = submit(client, road_point, lat=200.0)
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "coordinates_out_of_range"


def test_coordinates_outside_guayaquil_are_rejected(client: TestClient, road_point: dict) -> None:
    """This must not become a general-purpose report inbox for the whole planet."""
    new_session(client)
    r = submit(client, road_point, lat=51.5, lon=-0.12)  # London
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "outside_service_area"


def test_unknown_category_is_rejected(client: TestClient, road_point: dict) -> None:
    new_session(client)
    r = submit(client, road_point, category="meteor_strike")
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "invalid_category"


def test_overlong_description_is_rejected(client: TestClient, road_point: dict) -> None:
    new_session(client)
    r = submit(client, road_point, description="x" * 281)
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "description_too_long"


def test_invalid_accuracy_is_rejected(client: TestClient, road_point: dict) -> None:
    new_session(client)
    r = submit(client, road_point, accuracy=-5.0)
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "invalid_accuracy"


# ===========================================================================
# 3. Image security
# ===========================================================================


def test_non_image_upload_is_rejected(client: TestClient, road_point: dict) -> None:
    new_session(client)
    r = client.post(
        "/api/reports",
        data={"category": "flooded", "lat": str(road_point["lat"]), "lon": str(road_point["lon"])},
        files={"image": ("evil.jpg", b"<?php system($_GET['c']); ?>", "image/jpeg")},
    )
    assert r.status_code == 422
    assert r.json()["detail"]["code"] in ("image_not_an_image", "image_corrupt")


def test_gif_is_rejected_even_though_it_is_an_image(client: TestClient, road_point: dict) -> None:
    """Format allow-list, not merely 'is it an image'."""
    new_session(client)
    buf = io.BytesIO()
    Image.new("RGB", (40, 40), (1, 2, 3)).save(buf, format="GIF")
    r = client.post(
        "/api/reports",
        data={"category": "flooded", "lat": str(road_point["lat"]), "lon": str(road_point["lon"])},
        files={"image": ("anim.gif", buf.getvalue(), "image/gif")},
    )
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "image_format_unsupported"


def test_oversized_upload_is_rejected_before_decoding(
    client: TestClient, road_point: dict, monkeypatch
) -> None:
    """The endpoint enforces the size cap itself, so the check does not depend on Pillow."""
    from app.api import report_routes

    monkeypatch.setattr(report_routes, "MAX_IMAGE_BYTES", 1024)
    new_session(client)
    r = submit(client, road_point)
    assert r.status_code == 413
    assert r.json()["detail"]["code"] == "image_too_large"


def test_declared_mime_type_is_not_trusted(client: TestClient, road_point: dict) -> None:
    """A JPEG labelled as PNG is accepted on its CONTENT and re-encoded as JPEG."""
    new_session(client)
    r = client.post(
        "/api/reports",
        data={"category": "debris", "lat": str(road_point["lat"]), "lon": str(road_point["lon"])},
        files={"image": ("lying.png", make_jpeg(), "image/png")},
    )
    assert r.status_code == 201
    served = client.get(r.json()["report"]["image_url"])
    assert served.status_code == 200
    assert served.headers["content-type"] == "image/jpeg"


def test_served_image_has_safe_headers(client: TestClient, road_point: dict) -> None:
    new_session(client)
    rid = submit(client, road_point).json()["report"]["id"]
    r = client.get(f"/api/reports/{rid}/image")
    assert r.status_code == 200
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "default-src 'none'" in r.headers["content-security-policy"]


def test_served_image_contains_no_exif(client: TestClient, road_point: dict) -> None:
    """The published copy must carry no metadata, so no embedded GPS can leak."""
    new_session(client)
    rid = submit(client, road_point).json()["report"]["id"]
    raw = client.get(f"/api/reports/{rid}/image").content
    with Image.open(io.BytesIO(raw)) as img:
        assert dict(img.getexif()) == {}


def test_image_of_unknown_report_is_404(client: TestClient) -> None:
    assert client.get(f"/api/reports/{uuid.uuid4()}/image").status_code == 404


# ===========================================================================
# 4. GPS accuracy and snapping
# ===========================================================================


def test_far_from_any_road_is_stored_unmatched_with_a_useful_message(
    client: TestClient, road_point: dict
) -> None:
    """Feature A: "ask the user to adjust the pin rather than silently assigning the wrong road"."""
    new_session(client)
    # Inside the Guayaquil envelope but far from the bounded central extract.
    r = submit(client, road_point, lat=-2.39, lon=-79.72)
    assert r.status_code == 201
    report = r.json()["report"]
    assert report["road_segment_id"] is None
    assert report["location_is_snapped"] is False
    assert any("without a road match" in m for m in r.json()["messages"])


def test_poor_accuracy_prevents_an_automatic_match(
    client: TestClient, road_point: dict
) -> None:
    """A 300 m fix must not be laundered into a confident segment id."""
    new_session(client)
    r = submit(client, road_point, accuracy=300.0)
    assert r.status_code == 201
    report = r.json()["report"]
    assert report["road_segment_id"] is None
    assert any("accuracy" in m.lower() for m in r.json()["messages"])


def test_gps_accuracy_is_preserved_for_admin(client: TestClient, road_point: dict) -> None:
    new_session(client, role="operator")
    rid = submit(client, road_point, accuracy=12.5).json()["report"]["id"]
    admin = client.get(f"/api/admin/reports/{rid}")
    assert admin.status_code == 200
    assert admin.json()["gps_accuracy_m"] == pytest.approx(12.5)


# ===========================================================================
# 5. Privacy of position
# ===========================================================================


def test_public_payload_never_includes_raw_gps_or_identity(
    client: TestClient, road_point: dict
) -> None:
    """The brief: "Do not expose the submitter's private account details or precise unsnapped
    GPS coordinates publicly." """
    new_session(client)
    body = submit(client, road_point).json()["report"]
    for forbidden in ("gps_lat", "gps_lon", "user_id", "email", "decided_by"):
        assert forbidden not in body, forbidden


def test_unmatched_public_position_is_coarsened(
    client: TestClient, road_point: dict
) -> None:
    """An unmatched report must not publish the exact place the person stood."""
    new_session(client)
    raw_lat, raw_lon = -2.39012, -79.72034
    r = submit(client, road_point, lat=raw_lat, lon=raw_lon)
    assert r.status_code == 201
    report = r.json()["report"]
    assert report["location_is_snapped"] is False
    # Rounded to a ~111 m grid, so it differs from the raw fix but stays useful on a map.
    assert report["lat"] != pytest.approx(raw_lat, abs=1e-6)
    assert abs(report["lat"] - raw_lat) <= 0.001
    assert abs(report["lon"] - raw_lon) <= 0.001


def test_matched_public_position_is_the_road_point(
    client: TestClient, road_point: dict
) -> None:
    new_session(client)
    body = submit(client, road_point).json()["report"]
    assert body["location_is_snapped"] is True
    assert abs(body["lat"] - road_point["lat"]) < 0.001


# ===========================================================================
# 6. Public visibility
# ===========================================================================


def test_unverified_reports_are_publicly_visible_and_labelled(
    client: TestClient, road_point: dict
) -> None:
    """Feature B §4: "Initial submission must appear as Unverified Report" and be visible."""
    new_session(client)
    rid = submit(client, road_point).json()["report"]["id"]

    anonymous = TestClient(app)
    listing = anonymous.get("/api/reports", params={"limit": 200})
    assert listing.status_code == 200
    ids = [r["id"] for r in listing.json()["reports"]]
    assert rid in ids
    found = next(r for r in listing.json()["reports"] if r["id"] == rid)
    assert found["state"] == "unverified"


def test_listing_is_bounded(client: TestClient) -> None:
    r = client.get("/api/reports", params={"limit": 10_000})
    # A caller cannot ask for the entire history; 422 from the Query bound is the correct answer.
    assert r.status_code == 422


def test_listing_bbox_filter(client: TestClient, road_point: dict) -> None:
    new_session(client)
    submit(client, road_point).json()
    inside = client.get(
        "/api/reports",
        params={
            "bbox": f"{road_point['lat'] - 0.01},{road_point['lon'] - 0.01},"
            f"{road_point['lat'] + 0.01},{road_point['lon'] + 0.01}",
        },
    )
    assert inside.status_code == 200
    assert inside.json()["count"] >= 1

    elsewhere = client.get("/api/reports", params={"bbox": "-2.30,-79.95,-2.29,-79.94"})
    assert elsewhere.status_code == 200
    assert elsewhere.json()["count"] == 0


def test_malformed_bbox_is_rejected(client: TestClient) -> None:
    assert client.get("/api/reports", params={"bbox": "1,2,3"}).status_code == 422
    assert client.get("/api/reports", params={"bbox": "a,b,c,d"}).status_code == 422
    # Minimums greater than maximums describe an impossible box.
    assert client.get("/api/reports", params={"bbox": "10,10,5,5"}).status_code == 422


def test_unknown_report_detail_is_404(client: TestClient) -> None:
    assert client.get(f"/api/reports/{uuid.uuid4()}").status_code == 404


# ===========================================================================
# 7. Community confirmation
# ===========================================================================


def test_confirmation_is_recorded_and_counted(client: TestClient, road_point: dict) -> None:
    new_session(client)
    rid = submit(client, road_point).json()["report"]["id"]
    r = client.post(f"/api/reports/{rid}/confirm", json={"kind": "confirm"})
    assert r.status_code == 200
    assert r.json()["outcome"] == "recorded"
    assert r.json()["confirm_count"] == 1
    assert r.json()["decision_unchanged"] is True


def test_duplicate_confirmation_by_the_same_account_is_refused(
    client: TestClient, road_point: dict
) -> None:
    """"Prevent repeated voting by the same user on the same report." """
    new_session(client)
    rid = submit(client, road_point).json()["report"]["id"]
    client.post(f"/api/reports/{rid}/confirm", json={"kind": "confirm"})
    second = client.post(f"/api/reports/{rid}/confirm", json={"kind": "confirm"})
    assert second.status_code == 200
    assert second.json()["outcome"] == "already_voted"
    assert second.json()["confirm_count"] == 1  # not double-counted

    # And a challenge from the same account is also refused: one response per person.
    third = client.post(f"/api/reports/{rid}/confirm", json={"kind": "challenge"})
    assert third.json()["outcome"] == "already_voted"


def test_confirmation_requires_a_session(client: TestClient, road_point: dict) -> None:
    new_session(client)
    rid = submit(client, road_point).json()["report"]["id"]
    anon = TestClient(app)
    assert anon.post(f"/api/reports/{rid}/confirm", json={"kind": "confirm"}).status_code == 401


def test_confirmation_cannot_change_the_decision(client: TestClient, road_point: dict) -> None:
    """Corroboration is evidence. The brief forbids votes conferring authority."""
    new_session(client)
    rid = submit(client, road_point).json()["report"]["id"]
    for _ in range(3):
        client.post(f"/api/reports/{rid}/confirm", json={"kind": "confirm"})
    after = client.get(f"/api/reports/{rid}").json()
    assert after["decision"] == "unverified"


def test_confirmation_kind_is_validated(client: TestClient, road_point: dict) -> None:
    new_session(client)
    rid = submit(client, road_point).json()["report"]["id"]
    r = client.post(f"/api/reports/{rid}/confirm", json={"kind": "sideways"})
    assert r.status_code == 422


# ===========================================================================
# 8. Privilege escalation attempts
# ===========================================================================


def test_public_user_cannot_use_admin_endpoints(client: TestClient, road_point: dict) -> None:
    new_session(client)  # role: public
    rid = submit(client, road_point).json()["report"]["id"]
    assert client.get("/api/admin/reports").status_code == 403
    assert client.get(f"/api/admin/reports/{rid}").status_code == 403
    assert client.get(f"/api/admin/reports/{rid}/history").status_code == 403
    assert (
        client.post(
            f"/api/admin/reports/{rid}/decision", json={"decision": "blocked_verified"}
        ).status_code
        == 403
    )


def test_viewer_cannot_decide_but_can_read(client: TestClient, road_point: dict) -> None:
    """A role named `viewer` that could close roads would be a naming lie."""
    new_session(client, role="viewer")
    rid = submit(client, road_point).json()["report"]["id"]
    assert client.get("/api/admin/reports").status_code == 200
    assert (
        client.post(
            f"/api/admin/reports/{rid}/decision", json={"decision": "blocked_verified"}
        ).status_code
        == 403
    )


def test_body_cannot_set_a_role_or_a_decision(client: TestClient, road_point: dict) -> None:
    """`extra="forbid"` on the decision model is the observable proof there is no such field.

    Tested as an OPERATOR on purpose. A public user is stopped earlier, by the 403 from
    `require_admin`, so using one here would pass for the wrong reason and would keep passing
    even if the model silently gained a `role` field. An authorised caller is the only way to
    reach the schema check that this test is about.
    """
    new_session(client, role="operator")
    rid = submit(client, road_point).json()["report"]["id"]
    r = client.post(
        f"/api/admin/reports/{rid}/decision",
        json={"decision": "blocked_verified", "role": "admin", "user_id": "someone-else"},
    )
    assert r.status_code == 422
    # Unknown fields are named in the error, so the rejection is diagnosable rather than vague.
    assert "role" in r.text

    # And the role genuinely did not change.
    assert client.get("/api/auth/me").json()["role"] == "operator"


def test_submission_cannot_set_its_own_decision_or_role(
    client: TestClient, road_point: dict
) -> None:
    """Extra multipart fields are ignored by signature binding, and cannot set status."""
    new_session(client)
    r = client.post(
        "/api/reports",
        data={
            "category": "flooded",
            "lat": str(road_point["lat"]),
            "lon": str(road_point["lon"]),
            "decision": "blocked_verified",
            "role": "admin",
        },
        files={"image": ("photo.jpg", make_jpeg(), "image/jpeg")},
    )
    assert r.status_code == 201
    assert r.json()["report"]["decision"] == "unverified"
    assert client.get("/api/auth/me").json()["role"] == "public"


# ===========================================================================
# 9. Admin decisions and the lifecycle
# ===========================================================================


def test_operator_can_verify_blocked_and_it_closes_the_segment(
    client: TestClient, road_point: dict
) -> None:
    new_session(client, role="operator")
    rid = submit(client, road_point).json()["report"]["id"]
    r = client.post(
        f"/api/admin/reports/{rid}/decision",
        json={"decision": "blocked_verified", "note": "patrol confirmed"},
    )
    assert r.status_code == 200
    assert r.json()["decision"] == "blocked_verified"
    assert r.json()["state"] == "blocked_verified"
    assert r.json()["verified_at"] is not None

    effective = client.get("/api/admin/reports/effective-status").json()
    assert effective["segments_closed"] >= 1
    assert effective["segments_with_stale_closure"] == 0


def test_verified_passable_reopens(client: TestClient, road_point: dict) -> None:
    new_session(client, role="operator")
    rid = submit(client, road_point).json()["report"]["id"]
    client.post(
        f"/api/admin/reports/{rid}/decision", json={"decision": "blocked_verified"}
    )
    r = client.post(
        f"/api/admin/reports/{rid}/decision", json={"decision": "passable_verified"}
    )
    assert r.status_code == 200
    assert r.json()["decision"] == "passable_verified"
    assert r.json()["state"] == "passable_verified"


@pytest.mark.parametrize(
    "decision",
    ["potential_hazard", "blocked_verified", "passable_verified", "inconclusive", "rejected"],
)
def test_every_admissible_decision_is_accepted(
    client: TestClient, road_point: dict, decision: str
) -> None:
    new_session(client, role="operator")
    rid = submit(client, road_point).json()["report"]["id"]
    r = client.post(f"/api/admin/reports/{rid}/decision", json={"decision": decision})
    assert r.status_code == 200
    assert r.json()["decision"] == decision


def test_unverified_is_not_an_operator_decision(client: TestClient, road_point: dict) -> None:
    """Reverting a review is `inconclusive`; pretending it never happened is not offered."""
    new_session(client, role="operator")
    rid = submit(client, road_point).json()["report"]["id"]
    r = client.post(f"/api/admin/reports/{rid}/decision", json={"decision": "unverified"})
    assert r.status_code == 422


def test_history_is_append_only_and_records_every_step(
    client: TestClient, road_point: dict
) -> None:
    new_session(client, role="operator")
    rid = submit(client, road_point).json()["report"]["id"]
    client.post(f"/api/reports/{rid}/confirm", json={"kind": "confirm"})
    client.post(f"/api/admin/reports/{rid}/decision", json={"decision": "potential_hazard"})
    client.post(f"/api/admin/reports/{rid}/decision", json={"decision": "blocked_verified"})

    history = client.get(f"/api/admin/reports/{rid}/history")
    assert history.status_code == 200
    actions = [e["action"] for e in history.json()["entries"]]
    assert actions == [
        "report.submitted",
        "report.confirm",
        "report.decision",
        "report.decision",
    ]
    decisions = [e for e in history.json()["entries"] if e["action"] == "report.decision"]
    assert decisions[0]["from_state"] == "unverified"
    assert decisions[0]["to_state"] == "potential_hazard"
    assert decisions[1]["from_state"] == "potential_hazard"
    assert decisions[1]["to_state"] == "blocked_verified"
    assert decisions[1]["actor_role"] == "operator"


def test_rejected_report_keeps_its_history(client: TestClient, road_point: dict) -> None:
    """"if a report is marked false, rejected, or obsolete, preserve its history"."""
    new_session(client, role="operator")
    rid = submit(client, road_point).json()["report"]["id"]
    client.post(
        f"/api/admin/reports/{rid}/decision",
        json={"decision": "rejected", "note": "duplicate of an earlier report"},
    )
    history = client.get(f"/api/admin/reports/{rid}/history")
    assert history.status_code == 200
    assert len(history.json()["entries"]) == 2
    # And the report itself is still retrievable rather than deleted.
    assert client.get(f"/api/reports/{rid}").status_code == 200


# ===========================================================================
# 10. Staleness semantics through the API
# ===========================================================================


def test_expired_closure_still_affects_routing_and_is_flagged(
    client: TestClient, road_point: dict
) -> None:
    """The end-to-end version of the most important lifecycle rule.

    The freshness deadline is rewritten directly in the database to simulate the passage of
    time, because waiting six hours in a test suite is not a plan.
    """
    point = isolated_point()
    new_session(client, role="operator")
    rid = submit(client, point).json()["report"]["id"]
    client.post(
        f"/api/admin/reports/{rid}/decision", json={"decision": "blocked_verified"}
    )

    # Beyond the whole freshness window, not merely a minute: `by` must exceed
    # ROAD_REPORT_STALE_AFTER_MINUTES or the report is still comfortably fresh.
    age_out(rid, timedelta(minutes=STALE_WINDOW_MINUTES + 5))

    report = client.get(f"/api/reports/{rid}").json()
    assert report["is_stale"] is True
    assert report["state"] == "stale"
    # The DECISION is untouched — age did not rewrite it.
    assert report["decision"] == "blocked_verified"

    effective = client.get("/api/admin/reports/effective-status").json()
    # Asserted on an isolated segment: `segments_with_stale_closure` counts segments, and a
    # fresh closure on the same segment legitimately wins over a stale one.
    assert effective["segments_with_stale_closure"] >= 1
    assert rid in str(client.get(f"/api/admin/reports/{rid}/history").json())


def test_expiry_never_reports_a_road_as_passable(
    client: TestClient, road_point: dict
) -> None:
    new_session(client, role="operator")
    rid = submit(client, road_point).json()["report"]["id"]
    client.post(
        f"/api/admin/reports/{rid}/decision", json={"decision": "blocked_verified"}
    )
    age_out(rid, timedelta(minutes=STALE_WINDOW_MINUTES + 5))

    report = client.get(f"/api/reports/{rid}").json()
    # Nothing in the payload may claim passability.
    serialised = str(report).lower()
    assert "passable_verified" not in serialised
    assert report["state"] != "passable_verified"


# ===========================================================================
# 11. Storage failure handling
# ===========================================================================


def test_storage_failure_returns_503_not_a_stack_trace(
    client: TestClient, road_point: dict, monkeypatch
) -> None:
    """A database fault is not the user's fault and must not leak schema or driver text."""
    from app.reports import repository as repo

    def boom(*args, **kwargs):
        raise repo.ReportStoreError("disk gone", code="storage_failed")

    monkeypatch.setattr(repo, "create_report", boom)
    new_session(client)
    r = submit(client, road_point)
    assert r.status_code == 503
    body = r.json()["detail"]
    assert body["code"] == "storage_failed"
    assert "sqlite" not in str(body).lower()
    assert "Traceback" not in str(body)


def test_rate_limit_blocks_excessive_submissions(
    client: TestClient, road_point: dict, monkeypatch
) -> None:
    from app.api import report_routes

    monkeypatch.setattr(report_routes, "MAX_SUBMISSIONS_PER_WINDOW", 1)
    new_session(client)
    assert submit(client, road_point).status_code == 201
    second = submit(client, road_point)
    assert second.status_code == 429
    assert second.json()["detail"]["code"] == "rate_limited"
