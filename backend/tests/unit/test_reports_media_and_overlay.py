"""Tests for snapping, image intake, and the report→routing overlay.

Three separate concerns, kept in one file because they share one fixture: the real road graph.
Each section states the failure mode it exists to prevent, because a test whose purpose is not
written down gets deleted by the next person who finds it inconvenient.
"""

from __future__ import annotations

import io
import os
import tempfile
from datetime import datetime, timedelta, timezone

import pytest
from PIL import Image
from PIL.TiffImagePlugin import IFDRational

os.environ.setdefault(
    "GUARADAR_DB_PATH", os.path.join(tempfile.mkdtemp(prefix="guaradar-snap-"), "t.db")
)

from app.routing.graph import (  # noqa: E402
    STATUS_AFFECTED,
    STATUS_CLOSED,
    STATUS_OPEN,
    EdgeStatus,
    StatusIndex,
)
from app.reports.images import (  # noqa: E402
    ALLOWED_FORMATS,
    DEFAULT_MAX_BYTES,
    ImageRejected,
    has_exif_gps,
    process_image,
    validate_size,
)
from app.reports.snapping import (  # noqa: E402
    DEFAULT_SNAP_THRESHOLD_M,
    point_to_segment_m,
    public_location,
    snap_to_road,
)

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def graph():
    from app.api.main import get_graph

    return get_graph()


def jpeg_with_gps(width: int = 2400, height: int = 1800) -> bytes:
    """A real JPEG carrying a GPS EXIF block, as a phone camera would produce."""
    img = Image.new("RGB", (width, height), (120, 60, 30))
    exif = img.getexif()
    exif[0x0112] = 1  # orientation: a harmless metadata example
    gps = exif.get_ifd(0x8825)
    gps[1] = "S"
    gps[2] = (IFDRational(2), IFDRational(9), IFDRational(44))
    gps[3] = "W"
    gps[4] = (IFDRational(79), IFDRational(52), IFDRational(48))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif, quality=95)
    return buf.getvalue()


# ===========================================================================
# 1. Snapping
# ===========================================================================


def test_point_on_a_node_snaps_with_zero_distance(graph) -> None:
    node = graph.nodes[next(iter(graph.nodes))]
    result = snap_to_road(graph, node.lat, node.lon)
    assert result.matched is True
    assert result.edge_id is not None
    assert result.distance_m < 5.0


def test_snapped_point_is_published_not_the_submitter_position(graph) -> None:
    """The public location must be a point on the road, not where the person stood."""
    node = graph.nodes[next(iter(graph.nodes))]
    # Offset the fix by ~20 m; still within the 50 m threshold.
    lat = node.lat + 20.0 / 111_320.0
    result = snap_to_road(graph, lat, node.lon)
    assert result.matched is True
    lat_pub, lon_pub, snapped = public_location(lat, node.lon, result)
    assert snapped is True
    # Published lat differs from the raw fix, and is near the road.
    assert lat_pub != pytest.approx(lat, abs=1e-7)


def test_far_away_position_is_not_matched(graph) -> None:
    result = snap_to_road(graph, -2.39, -79.72)
    assert result.matched is False
    assert result.edge_id is None
    assert "no road segments exist near this position" in result.reason


# A point inside the extract's bounding box that is genuinely away from any road.
#
# MEASURED, not assumed: Guayaquil's street grid is dense, so "400 m north of a node" usually
# lands on the NEXT street and matches perfectly well — which made the first version of this
# test assert the opposite of the truth. This coordinate was found by scanning the bbox for
# points whose nearest segment is far away, and its distance is asserted below so a rebuilt
# extract that fills the gap fails loudly instead of silently weakening the test.
BLANK_SPOT = (-2.18198, -79.92975)
BLANK_SPOT_ROAD_DISTANCE_M = 815.6  # measured against this extract


def test_blank_spot_is_still_a_blank_spot(graph) -> None:
    """Guards the fixture itself: if the extract changes, the threshold test must be revisited."""
    result = snap_to_road(graph, *BLANK_SPOT, threshold_m=2000.0)
    assert result.distance_m > 500, (
        f"the fixture point is now only {result.distance_m:.0f} m from a road; pick another"
    )


def test_position_beyond_the_threshold_is_refused(graph) -> None:
    """The threshold is a real boundary, not a suggestion."""
    result = snap_to_road(graph, *BLANK_SPOT)
    assert result.matched is False
    assert "matching limit" in result.reason
    assert result.distance_m > DEFAULT_SNAP_THRESHOLD_M


def test_threshold_is_configurable(graph) -> None:
    """The same position matches when the configured limit is large enough."""
    loose = snap_to_road(graph, *BLANK_SPOT, threshold_m=2000.0)
    assert loose.matched is True
    assert loose.distance_m == pytest.approx(BLANK_SPOT_ROAD_DISTANCE_M, abs=5.0)


def test_poor_accuracy_blocks_the_match_even_when_very_close(graph) -> None:
    """A confident-looking segment id from a 300 m fix would be worse than no match."""
    node = graph.nodes[next(iter(graph.nodes))]
    result = snap_to_road(graph, node.lat, node.lon, accuracy_m=300.0)
    assert result.matched is False
    assert result.accuracy_rejected is True
    assert "accuracy" in result.reason


def test_good_accuracy_does_not_block(graph) -> None:
    node = graph.nodes[next(iter(graph.nodes))]
    assert snap_to_road(graph, node.lat, node.lon, accuracy_m=5.0).matched is True


def test_out_of_range_coordinates_raise(graph) -> None:
    with pytest.raises(ValueError):
        snap_to_road(graph, 91.0, 0.0)
    with pytest.raises(ValueError):
        snap_to_road(graph, 0.0, 181.0)


def test_zero_threshold_is_rejected(graph) -> None:
    with pytest.raises(ValueError):
        snap_to_road(graph, -2.19, -79.9, threshold_m=0.0)


def test_point_to_segment_clamps_to_the_endpoint() -> None:
    """A point beside an endpoint must not project off the end of the road."""
    dist, lat, lon = point_to_segment_m(0.0, 0.0, 0.0, 0.0, 0.0, 0.001)
    assert dist == pytest.approx(0.0, abs=0.5)
    assert lon == pytest.approx(0.0, abs=1e-9)


def test_point_to_segment_handles_a_degenerate_segment() -> None:
    """The artifact contains 0.1 m segments; identical endpoints must not divide by zero."""
    dist, lat, lon = point_to_segment_m(-2.19, -79.90, -2.19, -79.90, -2.19, -79.90)
    assert dist == pytest.approx(0.0, abs=0.5)


def test_unmatched_public_location_is_coarsened() -> None:
    lat, lon, snapped = public_location(-2.39012, -79.72034, None)
    assert snapped is False
    assert abs(lat - (-2.39012)) <= 0.001
    assert abs(lon - (-79.72034)) <= 0.001


# ===========================================================================
# 2. Image intake
# ===========================================================================


def test_metadata_and_gps_are_stripped() -> None:
    """The published copy must carry no EXIF, so no embedded GPS can reach a public response."""
    raw = jpeg_with_gps()
    assert has_exif_gps(raw) is True
    stored = process_image(raw)
    assert stored.metadata_stripped is True
    assert has_exif_gps(stored.data) is False
    with Image.open(io.BytesIO(stored.data)) as img:
        assert dict(img.getexif()) == {}


def test_output_is_resized_within_the_cap() -> None:
    stored = process_image(jpeg_with_gps(4000, 3000))
    assert max(stored.width, stored.height) <= 1280
    # Aspect ratio preserved (4:3 within rounding).
    assert abs(stored.width / stored.height - 4 / 3) < 0.01


def test_small_image_is_not_upscaled() -> None:
    buf = io.BytesIO()
    Image.new("RGB", (320, 240), (1, 2, 3)).save(buf, format="JPEG")
    stored = process_image(buf.getvalue())
    assert (stored.width, stored.height) == (320, 240)


def test_output_is_always_jpeg() -> None:
    for fmt in ("PNG", "WEBP"):
        buf = io.BytesIO()
        Image.new("RGB", (900, 700), (4, 5, 6)).save(buf, format=fmt)
        stored = process_image(buf.getvalue())
        assert stored.content_type == "image/jpeg"
        assert fmt in ALLOWED_FORMATS  # accepted as input


def test_alpha_is_flattened_not_turned_black() -> None:
    """A transparent PNG converted naively would render as a black rectangle."""
    buf = io.BytesIO()
    Image.new("RGBA", (400, 300), (255, 255, 255, 0)).save(buf, format="PNG")
    stored = process_image(buf.getvalue())
    with Image.open(io.BytesIO(stored.data)) as img:
        # Composited onto white, so the pixel is light rather than black.
        r, g, b = img.convert("RGB").getpixel((10, 10))
        assert r > 200 and g > 200 and b > 200


def test_sha256_is_deterministic_for_the_same_pixels() -> None:
    """Two identical inputs must hash identically, or dedupe and caching become guesswork."""
    raw = jpeg_with_gps(800, 600)
    assert process_image(raw).sha256 == process_image(raw).sha256


@pytest.mark.parametrize("fmt", ["GIF", "BMP", "TIFF"])
def test_unsupported_but_valid_image_formats_are_refused(fmt: str) -> None:
    buf = io.BytesIO()
    Image.new("RGB", (60, 60), (7, 8, 9)).save(buf, format=fmt)
    with pytest.raises(ImageRejected) as exc:
        process_image(buf.getvalue())
    assert exc.value.code == "image_format_unsupported"


def test_non_image_bytes_are_refused() -> None:
    with pytest.raises(ImageRejected) as exc:
        process_image(b"<script>alert(1)</script>" * 10)
    assert exc.value.code in ("image_not_an_image", "image_corrupt")


def test_truncated_image_is_refused() -> None:
    raw = jpeg_with_gps()
    with pytest.raises(ImageRejected) as exc:
        process_image(raw[: len(raw) // 3])
    assert exc.value.code in ("image_corrupt", "image_not_an_image")


def test_empty_payload_is_refused() -> None:
    with pytest.raises(ImageRejected) as exc:
        process_image(b"")
    assert exc.value.code == "image_empty"


def test_oversize_payload_is_refused_before_decoding() -> None:
    big = b"\xff" * (DEFAULT_MAX_BYTES + 1)
    with pytest.raises(ImageRejected) as exc:
        process_image(big)
    assert exc.value.code == "image_too_large"


def test_size_message_is_human_readable() -> None:
    """A 100-byte limit must not render as \"0.0 MB\"."""
    with pytest.raises(ImageRejected) as exc:
        validate_size(b"x" * 200, max_bytes=100)
    assert "B" in exc.value.message
    assert "0.0 MB" not in exc.value.message


def test_validate_size_rejects_a_nonsense_limit() -> None:
    with pytest.raises(ValueError):
        validate_size(b"abc", max_bytes=0)


def test_gif_with_animated_frames_cannot_smuggle_through() -> None:
    """Multi-frame input is a known image-parser attack surface; the allow-list refuses it."""
    frames = [
        Image.new("RGB", (40, 40), (i * 20, 0, 0)) for i in range(4)
    ]
    buf = io.BytesIO()
    frames[0].save(buf, format="GIF", save_all=True, append_images=frames[1:])
    with pytest.raises(ImageRejected) as exc:
        process_image(buf.getvalue())
    assert exc.value.code == "image_format_unsupported"


# ===========================================================================
# 3. Status overlay merging
# ===========================================================================


def _status_index(*records: tuple[int, str, bool]) -> StatusIndex:
    statuses = [
        EdgeStatus(edge_id=eid, status=st, set_at=NOW - timedelta(minutes=5), verified=ver)
        for eid, st, ver in records
    ]
    return StatusIndex(statuses, now=NOW, freshness=timedelta(minutes=30))


def test_report_closure_wins_over_a_seeded_open() -> None:
    """The higher-risk reading must win: routing through a citizen-documented closure is worse."""
    from app.api.main import merge_statuses

    base = _status_index((1, STATUS_OPEN, True))
    merged = merge_statuses(base, {1: (STATUS_CLOSED, True)}, NOW)
    assert merged.status_of(1) == STATUS_CLOSED
    assert merged.is_closed(1) is True


def test_citizen_passable_cannot_lift_a_verified_closure() -> None:
    """Lifting a closure is an operator decision, not a vote. This is the core of feature C §5."""
    from app.api.main import merge_statuses

    base = _status_index((2, STATUS_CLOSED, True))
    merged = merge_statuses(base, {2: (STATUS_OPEN, True)}, NOW)
    assert merged.status_of(2) == STATUS_CLOSED
    assert merged.is_closed(2) is True


def test_stale_report_closure_closes_but_is_not_verified() -> None:
    """Requirement D.9: keep the exclusion, drop the freshness claim."""
    from app.api.main import merge_statuses

    base = _status_index((3, STATUS_OPEN, True))
    merged = merge_statuses(base, {3: (STATUS_CLOSED, False)}, NOW)
    assert merged.is_closed(3) is True
    assert merged.is_verified(3) is False  # lowers coverage


def test_unverified_caution_does_not_close_but_penalises() -> None:
    from app.api.main import merge_statuses

    base = _status_index((4, STATUS_OPEN, True))
    merged = merge_statuses(base, {4: (STATUS_AFFECTED, False)}, NOW)
    assert merged.is_closed(4) is False
    assert merged.status_of(4) == STATUS_AFFECTED
    # Affected carries a cost multiplier, so the router prefers alternatives without refusing.
    assert merged.cost_factor(4) > 1.0


def test_overlay_applies_to_an_edge_the_base_has_no_record_for() -> None:
    """A report about a road the seed generator skipped must not be ignored."""
    from app.api.main import merge_statuses

    base = _status_index((5, STATUS_OPEN, True))
    merged = merge_statuses(base, {6: (STATUS_CLOSED, True)}, NOW)
    assert merged.is_closed(6) is True
    # And the untouched edge is unchanged.
    assert merged.status_of(5) == STATUS_OPEN


def test_merge_preserves_the_original_freshness_window() -> None:
    from app.api.main import merge_statuses

    base = StatusIndex(
        [EdgeStatus(7, STATUS_OPEN, NOW, True)], now=NOW, freshness=timedelta(minutes=5)
    )
    merged = merge_statuses(base, {7: (STATUS_AFFECTED, True)}, NOW)
    assert merged.freshness_window() == timedelta(minutes=5)


def test_empty_overlay_leaves_status_untouched() -> None:
    from app.api.main import merge_statuses

    base = _status_index((8, STATUS_OPEN, True), (9, STATUS_CLOSED, True))
    merged = merge_statuses(base, {}, NOW)
    assert merged.status_of(8) == STATUS_OPEN
    assert merged.is_closed(9) is True


# ===========================================================================
# 4. No elevation/terrain is involved yet
# ===========================================================================


def test_route_response_does_not_claim_terrain_influence() -> None:
    """Feature F/G are out of scope for this pass, so nothing may imply they are active.

    A future pass that adds terrain must update this test rather than delete it: the point is
    that the claim and the code stay in step.
    """
    from app.api.main import app

    paths = {getattr(r, "path", "") for r in app.routes}
    assert not any("terrain" in p for p in paths)
