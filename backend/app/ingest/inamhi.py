"""INAMHI official bulletin adapter.

WHAT I ACTUALLY FOUND, AND WHY THIS IS BUILT THIS WAY
  Inspected before writing any code (2026-10-26):

  * `servicios.inamhi.gob.ec` is a **WordPress site**. `robots.txt` disallows only `/wp-admin/`
    and points to a sitemap, so the public pages are crawlable.
  * `/wp-json/wp/v2/posts` returns `[]` and `/feed/` returns zero `<item>` elements. There is
    **no populated machine-readable feed** for bulletins or alerts.
  * `/boletines/` links **PDF files** hosted on `www.inamhi.gob.ec`, e.g.
    `pronostico/advertencia.pdf`. That file is genuinely live: `Last-Modified` was the previous
    day, and its text is the current bulletin ("Boletín Meteorológico Nro. 83", issued
    2026-10-25 14:00, valid 16:00 25 Oct → 23:00 28 Oct).

  So there is **no JSON API for INAMHI**. Inventing one, or scraping HTML tables that do not
  exist, would be a fiction. What IS available is an official, machine-fetchable PDF whose text
  layer contains structured fields. This adapter reads those fields.

THE HONESTY RULES THIS ENFORCES
  1. **Every extracted field is optional.** If a regex does not match, the value is `None` and a
     warning is emitted. A missing threat level is rendered as unknown, never as "low".
  2. **Rainfall is a RANGE, not a point.** The bulletin publishes
     `Precipitación acumulada diaria (mm/24h)` as bands per region (e.g. Litoral
     `10 – 18 / 19 – 41 / 42 – 100`). Those are **a 24-hour accumulation over a whole region**,
     and are therefore *not* numerically comparable to an Open-Meteo point forecast for one
     coordinate. `comparison.py` encodes that distinction; this module only extracts the ranges
     faithfully and never turns them into a single number.
  3. **The source URL is always carried**, so the UI can link to the official document rather
     than asking anyone to trust a paraphrase.
  4. **Failure is a normal outcome.** INAMHI may be unreachable, or the PDF layout may change so
     the text is unparseable. Both return `ok=False` with a reason, and the UI shows the official
     link instead of stale numbers.

WHY PDF TEXT EXTRACTION AND NOT AN HTML PARSE
  The bulletin is a PDF with a text layer (`pdftotext` reads it cleanly). There is no HTML
  representation of the same fields. Extracting from the PDF text is therefore the least
  inventive available approach.

DEPENDENCY NOTE
  `pdftotext` (poppler-utils) is invoked as a subprocess and **is already present on this host**,
  so no Python dependency was added. If it is missing the adapter reports that plainly rather
  than silently returning nothing.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Callable

# Official sources. Recorded here so the UI links to the same URLs the adapter reads.
PORTAL_PRONOSTICO = "https://servicios.inamhi.gob.ec/pronostico/"
PORTAL_BOLETINES = "https://servicios.inamhi.gob.ec/boletines/"
PORTAL_ALERTAS = "https://servicios.inamhi.gob.ec/alertas/"
MODELOS_NUMERICOS = "https://www.inamhi.gob.ec/modelos-numericos-para-prediccion/"

# The live advisory PDF linked from /boletines/. Verified reachable and current on 2026-10-26.
ADVERTENCIA_PDF = "https://www.inamhi.gob.ec/pronostico/advertencia.pdf"

PDF_TIMEOUT_S = 20.0
MAX_PDF_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True)
class RainfallBand:
    """One published threat band for a region: `Nivel <label>` spans `low_mm`..`high_mm`."""

    level: str          # e.g. "Medio", "Alto", "Muy Alto"
    low_mm: float | None
    high_mm: float | None


@dataclass(frozen=True)
class RegionBands:
    """The published 24h rainfall bands for one region."""

    region: str         # e.g. "Litoral"
    bands: tuple[RainfallBand, ...]


@dataclass(frozen=True)
class Bulletin:
    """An official INAMHI bulletin, as published.

    `None` everywhere means "the document did not yield this field", which the UI renders as
    unavailable. It never means zero and never means "safe".
    """

    ok: bool
    source_url: str
    source_name: str = "INAMHI — Dirección de Pronósticos y Alertas Hidrometeorológicas"
    bulletin_number: str | None = None
    status: str | None = None            # e.g. "ADVERTENCIA", "ALERTA"
    issued_at: datetime | None = None
    issued_text: str | None = None       # verbatim, since the PDF's wording is the source
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    validity_text: str | None = None
    threat_level: str | None = None      # e.g. "MEDIO – MUY ALTO"
    phenomenon: str | None = None
    affected_regions: tuple[str, ...] = ()
    regions: tuple[RegionBands, ...] = ()
    recommendations: tuple[str, ...] = ()
    fetched_at: datetime | None = None
    pdf_last_modified: str | None = None
    error: str | None = None
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_quantitative(self) -> bool:
        """True only when the bulletin published numeric mm bands we can reason about."""
        return any(b.low_mm is not None or b.high_mm is not None for r in self.regions for b in r.bands)

    def bands_for(self, region: str) -> RegionBands | None:
        for r in self.regions:
            if r.region.lower() == region.lower():
                return r
        return None


HttpGetBytes = Callable[[str, float], tuple[int, bytes, str | None]]


def urllib_get_bytes(url: str, timeout_s: float = PDF_TIMEOUT_S) -> tuple[int, bytes, str | None]:
    """Fetch raw bytes. Returns (status, body, last_modified). Never raises for HTTP failure."""
    import urllib.error
    import urllib.request

    req = urllib.request.Request(
        url, headers={"User-Agent": "Guaradar/1.0 (flood-resilience prototype; contact: local)"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:  # noqa: S310
            body = resp.read(MAX_PDF_BYTES + 1)
            if len(body) > MAX_PDF_BYTES:
                return 413, b"", None
            return resp.status, body, resp.headers.get("Last-Modified")
    except urllib.error.HTTPError as exc:
        return exc.code, b"", None
    except (urllib.error.URLError, TimeoutError, OSError):
        return 0, b"", None


# --- text extraction -------------------------------------------------------


def pdf_to_text(pdf_bytes: bytes, timeout_s: float = PDF_TIMEOUT_S) -> tuple[str, str | None]:
    """Return (text, error). Uses pdftotext, which is present on this host.

    Returns an error string rather than raising, because "the bulletin could not be read" is a
    state the UI must be able to show honestly.
    """
    exe = shutil.which("pdftotext")
    if not exe:
        return "", (
            "pdftotext is not installed on this host, so the official PDF cannot be read. "
            "The bulletin link is still provided; no values are shown."
        )
    try:
        proc = subprocess.run(
            [exe, "-layout", "-", "-"],
            input=pdf_bytes,
            capture_output=True,
            timeout=timeout_s,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return "", f"PDF text extraction failed: {type(exc).__name__}"
    if proc.returncode != 0:
        return "", f"pdftotext exited {proc.returncode}"
    text = proc.stdout.decode("utf-8", errors="replace")
    if not text.strip():
        return "", "the PDF has no extractable text layer (possibly a scanned image)"
    return text, None


# --- field extraction ------------------------------------------------------

_MONTHS_ES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}

_RE_BULLETIN = re.compile(r"Bolet[ií]n\s+Meteorol[oó]gico\s+Nro\.?\s*(\d+)", re.I)
_RE_STATUS = re.compile(r"Estatus:\s*([A-ZÁÉÍÓÚÑ ]+)", re.I)
_RE_ISSUED = re.compile(
    r"Fecha y hora de emisi[oó]n:\s*([a-zá-ú]+),?\s*(\d{1,2})\s+de\s+([a-zá-ú]+)\s+de\s+(\d{4}),?\s*(\d{1,2}):(\d{2})",
    re.I,
)
_RE_VALIDITY = re.compile(r"Vigencia:\s*(.+)", re.I)
_RE_THREAT = re.compile(r"NIVEL AMENAZA:\s*([^\n]+)", re.I)
_RE_PHENOMENON = re.compile(r"FEN[OÓ]MENO:\s*([^\n]+)", re.I)
# "10 – 18" with en dash, hyphen or tilde. Captures the two bounds.
_RE_RANGE = re.compile(r"(\d{1,3}(?:[.,]\d+)?)\s*(?:[–\-−]|a)\s*(\d{1,3}(?:[.,]\d+)?)")


def _parse_issued(text: str) -> tuple[datetime | None, str | None]:
    m = _RE_ISSUED.search(text)
    if not m:
        return None, None
    weekday, day, month_name, year, hour, minute = m.groups()
    month = _MONTHS_ES.get(month_name.lower())
    if month is None:
        return None, m.group(0)
    try:
        # INAMHI issues in Ecuador time (UTC-5, no DST). Storing it as UTC keeps every
        # timestamp in this project on one clock; the UI renders it back in Guayaquil time.
        from datetime import timedelta

        local = datetime(int(year), month, int(day), int(hour), int(minute))
        return local.replace(tzinfo=timezone(timedelta(hours=-5))).astimezone(timezone.utc), m.group(0)
    except ValueError:
        return None, m.group(0)


def _parse_validity(text: str) -> tuple[datetime | None, datetime | None, str | None]:
    """Parse `Vigencia: desde 16H00 del 25 hasta las 23H00 del 28 de octubre de 2026`.

    The bulletin states times as `HHhmm` and days as integers, sometimes without a year on the
    first bound. Both bounds are optional; an unparseable window is reported verbatim instead of
    being guessed.
    """
    m = _RE_VALIDITY.search(text)
    if not m:
        return None, None, None
    raw = " ".join(m.group(1).split())
    # Harvest every (HHhMM, day) pair plus any trailing month/year.
    pairs = re.findall(r"(\d{1,2})\s*[Hh]\s*(\d{2})[^\d]{0,20}?(\d{1,2})", raw)
    year_m = re.search(r"de\s+(\d{4})", raw)
    month_m = re.search(r"de\s+([a-zá-ú]+)", raw)
    year = int(year_m.group(1)) if year_m else None
    month = _MONTHS_ES.get(month_m.group(1).lower()) if month_m else None

    from datetime import timedelta

    found: list[datetime] = []
    for hour_s, minute_s, day_s in pairs[:2]:
        if year is None or month is None:
            continue
        try:
            local = datetime(year, month, int(day_s), int(hour_s), int(minute_s))
        except ValueError:
            continue
        found.append(local.replace(tzinfo=timezone(timedelta(hours=-5))).astimezone(timezone.utc))
    if len(found) == 2:
        return found[0], found[1], raw
    return None, None, raw


def _parse_region_bands(text: str) -> tuple[RegionBands, ...]:
    """Extract the `Precipitación acumulada diaria (mm/24h)` table.

    The PDF lays it out as a row per region with three level columns. We read each region line and
    take the ranges in order; a row with fewer ranges than levels simply yields fewer bands.
    """
    out: list[RegionBands] = []
    # Find the table region: between the header and the next section.
    start = text.find("Precipitación acumulada diaria")
    if start == -1:
        start = text.find("Precipitaci\u00f3n acumulada diaria")
    if start == -1:
        return ()
    window = text[start: start + 1400]
    levels = ("Medio", "Alto", "Muy Alto")
    for line in window.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        low = stripped.lower()
        region = None
        for candidate in ("Litoral", "Interandina", "Amazonía", "Amazonia", "Insular"):
            if low.startswith(candidate.lower()):
                region = candidate.replace("Amazonia", "Amazonía")
                break
        if region is None:
            continue
        ranges = _RE_RANGE.findall(stripped)
        bands: list[RainfallBand] = []
        for i, (lo, hi) in enumerate(ranges[:3]):
            def f(v: str) -> float | None:
                try:
                    return float(v.replace(",", "."))
                except ValueError:
                    return None

            bands.append(
                RainfallBand(
                    level=levels[i] if i < len(levels) else f"level{i + 1}",
                    low_mm=f(lo),
                    high_mm=f(hi),
                )
            )
        if bands:
            out.append(RegionBands(region=region, bands=tuple(bands)))
    return tuple(out)


def _parse_affected(text: str) -> tuple[str, ...]:
    """Pull the region names named in `ZONAS AFECTADAS` (one bullet per region)."""
    idx = text.find("ZONAS AFECTADAS")
    if idx == -1:
        return ()
    window = text[idx: idx + 1200]
    names = []
    for label in ("Litoral", "Interandina", "Amazónica", "Amazonica", "Insular"):
        if label.lower() in window.lower():
            names.append(label.replace("Amazonica", "Amazónica"))
    return tuple(names)


def _parse_recommendations(text: str) -> tuple[str, ...]:
    idx = text.find("¿QUÉ PUEDE PASAR?")
    if idx == -1:
        return ()
    window = text[idx: idx + 1600]
    recs: list[str] = []
    for line in window.splitlines():
        s = line.strip()
        if s.startswith("•") or s.startswith("-"):
            body = s.lstrip("•- ").strip()
            if len(body) > 12:
                recs.append(body)
    return tuple(recs[:8])


def parse_bulletin_text(
    text: str,
    *,
    source_url: str,
    fetched_at: datetime,
    last_modified: str | None = None,
) -> Bulletin:
    """Turn extracted PDF text into a Bulletin. Every field independently optional."""
    warnings: list[str] = []

    num_m = _RE_BULLETIN.search(text)
    bulletin_number = num_m.group(1) if num_m else None
    if bulletin_number is None:
        warnings.append("bulletin number not found in the document")

    status_m = _RE_STATUS.search(text)
    status = status_m.group(1).strip() if status_m else None

    issued_at, issued_text = _parse_issued(text)
    if issued_at is None:
        warnings.append(
            "issue time could not be parsed; the document's own wording is shown instead"
        )

    valid_from, valid_until, validity_text = _parse_validity(text)
    if valid_from is None or valid_until is None:
        warnings.append(
            "validity window could not be parsed precisely; the stated text is shown as published"
        )

    threat_m = _RE_THREAT.search(text)
    threat_level = threat_m.group(1).strip() if threat_m else None
    if threat_level is None:
        warnings.append("threat level not published in a readable form")

    phen_m = _RE_PHENOMENON.search(text)
    phenomenon = phen_m.group(1).strip() if phen_m else None

    regions = _parse_region_bands(text)
    if not regions:
        warnings.append(
            "no numeric rainfall bands found; this bulletin is qualitative only. "
            "No rainfall values are invented to fill the gap."
        )

    return Bulletin(
        ok=True,
        source_url=source_url,
        bulletin_number=bulletin_number,
        status=status,
        issued_at=issued_at,
        issued_text=issued_text,
        valid_from=valid_from,
        valid_until=valid_until,
        validity_text=validity_text,
        threat_level=threat_level,
        phenomenon=phenomenon,
        affected_regions=_parse_affected(text),
        regions=regions,
        recommendations=_parse_recommendations(text),
        fetched_at=fetched_at,
        pdf_last_modified=last_modified,
        warnings=tuple(warnings),
    )


def fetch_bulletin(
    *,
    now: datetime,
    url: str = ADVERTENCIA_PDF,
    http_get: HttpGetBytes = urllib_get_bytes,
) -> Bulletin:
    """Fetch and parse the official advisory. Never raises for network or parse failure."""
    status, body, last_modified = http_get(url, PDF_TIMEOUT_S)

    if status == 0:
        return Bulletin(
            ok=False, source_url=url, fetched_at=now,
            error="INAMHI is unreachable or timed out; no bulletin values are shown",
        )
    if status == 413:
        return Bulletin(
            ok=False, source_url=url, fetched_at=now,
            error="the bulletin PDF exceeded the size limit; refused rather than truncated",
        )
    if status >= 400:
        return Bulletin(
            ok=False, source_url=url, fetched_at=now,
            error=f"INAMHI returned HTTP {status}; no bulletin values are shown",
        )
    if not body.startswith(b"%PDF"):
        return Bulletin(
            ok=False, source_url=url, fetched_at=now,
            error="the response was not a PDF, so it was not parsed",
        )

    text, err = pdf_to_text(body)
    if err is not None:
        return Bulletin(ok=False, source_url=url, fetched_at=now, error=err)

    try:
        return parse_bulletin_text(
            text, source_url=url, fetched_at=now, last_modified=last_modified
        )
    except Exception as exc:  # defensive: a layout change must not 500 the API
        return Bulletin(
            ok=False, source_url=url, fetched_at=now,
            error=f"the bulletin layout could not be interpreted ({type(exc).__name__}); "
            "the official link is shown instead",
        )
