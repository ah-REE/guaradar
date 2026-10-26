"""INAMHI bulletin and forecast-comparison routes (M14).

CACHING
  INAMHI is a public institution's web server, not a CDN. The bulletin is issued a few times a
  day, so fetching a 600 kB PDF on every page view would be both slow and rude. Responses are
  cached in-process for `BULLETIN_CACHE_TTL_S` (15 minutes) and the payload reports
  `cached` and `cache_age_s`, so freshness is visible rather than assumed.

  The cache stores the *parsed* Bulletin plus its fetch time. A failure is cached too, but for a
  shorter period (`FAILURE_CACHE_TTL_S`), so a transient outage does not pin an error to the
  screen for a full TTL while still avoiding a hammering retry loop.

  Deliberately in-process and therefore per-worker. With multiple uvicorn workers each would hold
  its own cache; that is acceptable for a prototype (at worst a few extra fetches) and is stated
  here rather than glossed over.

NO FABRICATION
  * If INAMHI cannot be read, the response has `ok=false`, a specific `error`, and the official
    `source_url` so the user can go and look. No values are synthesised.
  * The comparison endpoint never upgrades "inside a published band" into "verified".
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from fastapi import Depends, Query

from app.api.models import (
    BulletinOut,
    ComparisonOut,
    DayComparisonOut,
    Provenance,
    RainfallBandOut,
    RegionBandsOut,
)
from app.ingest.comparison import GUAYAQUIL_REGION, compare
from app.ingest.inamhi import (
    ADVERTENCIA_PDF,
    MODELOS_NUMERICOS,
    PORTAL_ALERTAS,
    PORTAL_BOLETINES,
    PORTAL_PRONOSTICO,
    Bulletin,
    fetch_bulletin,
)
from app.ingest.openmeteo import DailyRain
from app.simulate.sensors import data_mode as _data_mode
from app.api.models import SourceRef

BULLETIN_CACHE_TTL_S = 15 * 60
FAILURE_CACHE_TTL_S = 60

# url -> (bulletin, stored_at_monotonic)
_CACHE: dict[str, tuple[Bulletin, float]] = {}


def clear_cache() -> None:
    """Test hook. Application code never calls this."""
    _CACHE.clear()


def get_bulletin(url: str, now: datetime, *, force: bool = False) -> tuple[Bulletin, bool, float | None]:
    """Return (bulletin, cached, cache_age_s)."""
    entry = _CACHE.get(url)
    if entry is not None and not force:
        bulletin, stored = entry
        age = time.monotonic() - stored
        ttl = BULLETIN_CACHE_TTL_S if bulletin.ok else FAILURE_CACHE_TTL_S
        if age < ttl:
            return bulletin, True, round(age, 1)

    bulletin = fetch_bulletin(now=now, url=url)
    _CACHE[url] = (bulletin, time.monotonic())
    return bulletin, False, None


def bulletin_provenance(bulletin: Bulletin, cached: bool, cache_age: float | None) -> Provenance:
    notes: list[str] = [
        "Parsed from the official INAMHI PDF linked below; there is no INAMHI JSON API.",
        "INAMHI publishes regional bands, not a value for Guayaquil.",
    ]
    if cached:
        notes.append(f"served from cache, {cache_age:.0f}s old (TTL {BULLETIN_CACHE_TTL_S}s)")
    if bulletin.error:
        notes.append(bulletin.error)
    notes.extend(bulletin.warnings)

    return Provenance(
        chip="verified" if bulletin.ok else "no_data",
        fetched_at=bulletin.fetched_at,
        stale_after_s=BULLETIN_CACHE_TTL_S,
        simulated=False,  # an official bulletin is not simulated data
        # The mode is derived, not set by hand: the forecast may be live while sensors are
        # simulated, which is exactly MIXED. Passing facts keeps it impossible to mislabel.
        data_mode=_data_mode(external_live=bulletin.ok, any_simulated=True),
        sources=[SourceRef(name="INAMHI official bulletin", model_run_at=None)],
        notes=notes,
    )


def to_bulletin_out(
    bulletin: Bulletin, cached: bool, cache_age: float | None
) -> BulletinOut:
    return BulletinOut(
        ok=bulletin.ok,
        source_url=bulletin.source_url,
        source_name=bulletin.source_name,
        bulletin_number=bulletin.bulletin_number,
        status=bulletin.status,
        issued_at=bulletin.issued_at,
        issued_text=bulletin.issued_text,
        valid_from=bulletin.valid_from,
        valid_until=bulletin.valid_until,
        validity_text=bulletin.validity_text,
        threat_level=bulletin.threat_level,
        phenomenon=bulletin.phenomenon,
        affected_regions=list(bulletin.affected_regions),
        regions=[
            RegionBandsOut(
                region=r.region,
                bands=[
                    RainfallBandOut(level=b.level, low_mm=b.low_mm, high_mm=b.high_mm)
                    for b in r.bands
                ],
            )
            for r in bulletin.regions
        ],
        recommendations=list(bulletin.recommendations),
        is_quantitative=bulletin.is_quantitative,
        fetched_at=bulletin.fetched_at,
        pdf_last_modified=bulletin.pdf_last_modified,
        cached=cached,
        cache_age_s=cache_age,
        error=bulletin.error,
        warnings=list(bulletin.warnings),
        provenance=bulletin_provenance(bulletin, cached, cache_age),
    )


def build_comparison_out(
    days: tuple[DailyRain, ...],
    bulletin: Bulletin | None,
    *,
    region: str,
    provenance: Provenance,
) -> ComparisonOut:
    cmp = compare(days, bulletin, region=region)
    return ComparisonOut(
        comparable=cmp.comparable,
        reason=cmp.reason,
        explanation_en=cmp.explanation_en,
        explanation_es=cmp.explanation_es,
        region=cmp.region,
        days=[
            DayComparisonOut(
                date=d.day,
                forecast_mm=d.forecast_mm,
                matching_levels=[b.level for b in d.matching_bands],
                published_bands=[
                    RainfallBandOut(level=b.level, low_mm=b.low_mm, high_mm=b.high_mm)
                    for b in d.published_bands
                ],
            )
            for d in cmp.days
        ],
        disclaimers_en=list(cmp.disclaimers_en),
        disclaimers_es=list(cmp.disclaimers_es),
        bulletin_source_url=cmp.bulletin_source_url,
        bulletin_issued_at=cmp.bulletin_issued_at,
        bulletin_valid_from=cmp.bulletin_valid_from,
        bulletin_valid_until=cmp.bulletin_valid_until,
        notes=list(cmp.notes),
        provenance=provenance,
    )


# Official links, exposed so the UI never hardcodes a URL that could rot.
def official_links() -> dict[str, Any]:
    return {
        "pronostico": PORTAL_PRONOSTICO,
        "boletines": PORTAL_BOLETINES,
        "alertas": PORTAL_ALERTAS,
        "modelos_numericos": MODELOS_NUMERICOS,
        "advisory_pdf": ADVERTENCIA_PDF,
        "default_region": GUAYAQUIL_REGION,
    }
