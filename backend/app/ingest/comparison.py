"""Honest comparison between the Open-Meteo point forecast and the INAMHI regional bulletin.

THE PROBLEM THIS MODULE EXISTS TO PREVENT
  It is tempting to put "Open-Meteo says 21.5 mm, INAMHI says 19–41 mm" side by side and declare
  the model "within range" or "cross-verified". That would be misleading, because the two numbers
  are not the same kind of quantity:

  | | Open-Meteo | INAMHI bulletin |
  |---|---|---|
  | Spatial unit | one coordinate | a whole region (Litoral ≈ several provinces) |
  | Temporal unit | an hour, summed into a calendar day (UTC) | a 24-hour accumulation window |
  | Value type | a single model output | a published **band** per threat level, not one value |
  | Meaning | what the model predicts at a point | where INAMHI places the expected severity band |
  | Issue time | fetch time (no model run time given) | a stated issue time and validity window |

  A point value falling inside a region-wide band does **not** corroborate the band, and a point
  value outside it does **not** contradict it: a single pixel of a region can legitimately sit
  outside the region's dominant band.

SO WHAT MAY WE LEGITIMATELY SAY?
  Only this: "the point forecast for Guayaquil falls inside INAMHI's published *Alto* band for the
  Litoral on that day", or "it does not fall inside any published band", followed by an explicit
  statement that the two are **not a like-for-like comparison** and that this is **not** a
  cross-verification.

  The words "verified", "corroborated", "confirmed" and "agrees" are therefore never produced by
  this module. A test asserts that.

WHEN NO COMPARISON IS POSSIBLE AT ALL
  Returning `comparable=False` with a reason is a first-class outcome, not an error. It happens
  when: the bulletin failed to load; the bulletin published no numeric bands; the region is
  unknown; or the two have no overlapping day. Each reason is specific and user-readable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from app.ingest.inamhi import Bulletin, RainfallBand
from app.ingest.openmeteo import DailyRain

# The bulletin's region that contains Guayaquil. Named explicitly rather than guessed.
GUAYAQUIL_REGION = "Litoral"

Comparability = Literal[
    "band_comparison",     # a point value CAN be described relative to a published band
    "no_bulletin",         # INAMHI unavailable or unparseable
    "no_numeric_bands",    # bulletin is qualitative only
    "unknown_region",      # bulletin has no bands for the relevant region
    "no_overlapping_day",  # no shared dates
]


@dataclass(frozen=True)
class DayComparison:
    """One day, side by side, with the caveats attached to it."""

    day: date
    forecast_mm: float | None
    # Which published bands the forecast value falls inside (usually zero or one).
    matching_bands: tuple[RainfallBand, ...]
    # All bands published for the region that day, so the reader sees the whole picture.
    published_bands: tuple[RainfallBand, ...]

    @property
    def forecast_available(self) -> bool:
        return self.forecast_mm is not None


@dataclass(frozen=True)
class ForecastComparison:
    """The whole comparison verdict, including everything that makes it NOT a verification."""

    comparable: bool
    reason: Comparability
    explanation_en: str
    explanation_es: str
    region: str = GUAYAQUIL_REGION
    days: tuple[DayComparison, ...] = ()
    # Non-negotiable disclosures rendered with any comparison.
    disclaimers_en: tuple[str, ...] = ()
    disclaimers_es: tuple[str, ...] = ()
    bulletin_source_url: str | None = None
    bulletin_issued_at: str | None = None
    bulletin_valid_from: str | None = None
    bulletin_valid_until: str | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)


_CAVEATS_EN = (
    "This is NOT a cross-verification. It compares one model's point forecast for Guayaquil "
    "against INAMHI's region-wide published bands; agreement would not validate either source.",
    "INAMHI publishes bands (e.g. 19–41 mm for the Alto level across the whole Litoral), not a "
    "single value for Guayaquil. A point falling inside a band is consistent with it, nothing more.",
    "The time windows differ: the model's totals are calendar days in UTC, while the bulletin's "
    "are its own 24-hour accumulation windows within a stated validity period.",
    "The bulletin is an official warning about expected conditions; the model output is a "
    "numerical forecast. They answer different questions and are not interchangeable.",
)

_CAVEATS_ES = (
    "Esto NO es una verificación cruzada. Compara el pronóstico puntual de un modelo para "
    "Guayaquil con los rangos regionales publicados por el INAMHI; la coincidencia no validaría "
    "a ninguna de las dos fuentes.",
    "El INAMHI publica rangos (p. ej. 19–41 mm para el nivel Alto en todo el Litoral), no un "
    "valor único para Guayaquil. Que un punto caiga dentro de un rango es coherente con él, "
    "nada más.",
    "Las ventanas temporales difieren: los totales del modelo son días calendario en UTC, "
    "mientras que los del boletín son sus propias ventanas de acumulación de 24 h dentro de un "
    "periodo de vigencia declarado.",
    "El boletín es una advertencia oficial sobre las condiciones previstas; la salida del modelo "
    "es un pronóstico numérico. Responden a preguntas distintas y no son intercambiables.",
)


def _contains(band: RainfallBand, value: float) -> bool:
    lo = band.low_mm if band.low_mm is not None else float("-inf")
    hi = band.high_mm if band.high_mm is not None else float("inf")
    return lo <= value <= hi


def compare(
    days: tuple[DailyRain, ...],
    bulletin: Bulletin | None,
    *,
    region: str = GUAYAQUIL_REGION,
) -> ForecastComparison:
    """Build the comparison, or explain precisely why none can be made."""

    def not_comparable(reason: Comparability, en: str, es: str) -> ForecastComparison:
        return ForecastComparison(
            comparable=False,
            reason=reason,
            explanation_en=en,
            explanation_es=es,
            region=region,
            disclaimers_en=_CAVEATS_EN,
            disclaimers_es=_CAVEATS_ES,
            bulletin_source_url=getattr(bulletin, "source_url", None),
            bulletin_issued_at=(
                bulletin.issued_at.isoformat() if bulletin and bulletin.issued_at else None
            ),
            notes=(),
        )

    if bulletin is None or not bulletin.ok:
        return not_comparable(
            "no_bulletin",
            "The official INAMHI bulletin could not be retrieved, so no comparison is shown. "
            "The official link is provided instead of an estimate.",
            "No se pudo obtener el boletín oficial del INAMHI, por lo que no se muestra ninguna "
            "comparación. Se ofrece el enlace oficial en lugar de una estimación.",
        )

    if not bulletin.is_quantitative:
        return not_comparable(
            "no_numeric_bands",
            "The current INAMHI bulletin is qualitative and publishes no numeric rainfall bands, "
            "so there is nothing to compare against. Its text is shown as the official statement.",
            "El boletín actual del INAMHI es cualitativo y no publica rangos numéricos de "
            "precipitación, por lo que no hay nada con qué comparar. Su texto se muestra como la "
            "declaración oficial.",
        )

    region_bands = bulletin.bands_for(region)
    if region_bands is None or not region_bands.bands:
        return not_comparable(
            "unknown_region",
            f"The bulletin publishes no bands for the region {region}, so Guayaquil cannot be "
            f"placed against it.",
            f"El boletín no publica rangos para la región {region}, por lo que no se puede situar "
            f"a Guayaquil frente a él.",
        )

    if not days:
        return not_comparable(
            "no_overlapping_day",
            "No daily forecast data was available, so there is nothing to place against the "
            "bulletin.",
            "No hubo datos de pronóstico diario, por lo que no hay nada que situar frente al "
            "boletín.",
        )

    comparisons: list[DayComparison] = []
    for d in days:
        matching = tuple(
            b for b in region_bands.bands
            if d.precipitation_sum_mm is not None and _contains(b, d.precipitation_sum_mm)
        )
        comparisons.append(
            DayComparison(
                day=d.date,
                forecast_mm=d.precipitation_sum_mm,
                matching_bands=matching,
                published_bands=region_bands.bands,
            )
        )

    return ForecastComparison(
        comparable=True,
        reason="band_comparison",
        explanation_en=(
            "Each row places the model's daily total for Guayaquil against INAMHI's published "
            f"24-hour bands for the {region} region. Being inside a band is consistency, not "
            "agreement, and outside it is not contradiction."
        ),
        explanation_es=(
            "Cada fila sitúa el total diario del modelo para Guayaquil frente a los rangos de "
            f"24 horas publicados por el INAMHI para la región {region}. Estar dentro de un rango "
            "es coherencia, no concordancia; estar fuera no es contradicción."
        ),
        region=region,
        days=tuple(comparisons),
        disclaimers_en=_CAVEATS_EN,
        disclaimers_es=_CAVEATS_ES,
        bulletin_source_url=bulletin.source_url,
        bulletin_issued_at=bulletin.issued_at.isoformat() if bulletin.issued_at else None,
        bulletin_valid_from=bulletin.valid_from.isoformat() if bulletin.valid_from else None,
        bulletin_valid_until=bulletin.valid_until.isoformat() if bulletin.valid_until else None,
        notes=(
            "Both series are forecasts, not observations.",
            "No percentage difference is calculated: a point versus a regional band has no "
            "meaningful arithmetic difference.",
        ),
    )
