"""Open-Meteo rainfall ingestion adapter.

Approved design: docs/STAGE-3-ARCHITECTURE.md §11 (rainfall and river ingestion);
Stage 4 §16.2 block 5. Decisions: R-01/R-02 (forecast mandatory, Open-Meteo initial
provider), R-04 (forecast vs observation clearly distinguished), D23/B13 (NO heavy-rain
threshold — none is approved, so none is invented here).

DESIGN CONSTRAINTS THIS MODULE HONOURS
  * No network in tests. The HTTP call is injectable (`http_get`), so fixture tests run
    offline. A live smoke test is optional and reported separately if performed.
  * Forecast is never relabelled as observation. Every record carries `kind` = "forecast".
  * Units are normalised in exactly one place (`_normalise_units`). If the provider ever
    returns inches, the value is converted and the original unit is recorded, rather than
    silently mislabelling the number.
  * Provider failure never invents a reading. The adapter returns a `ForecastResult` with
    `ok=False` and a reason; callers then serve cached data with an honest age, or show
    nothing. It never fabricates millimetres.

WHAT THIS MODULE DOES NOT DO
  * It does not classify "heavy rain". B13 records that no defensible threshold exists.
  * It does not decide whether data is fresh enough to display; it reports the ages and
    lets the caller apply its own freshness budget.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Iterable, Literal, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

# The provider's variable names. Kept as constants so a rename is a one-line change.
VAR_PRECIPITATION = "precipitation"
VAR_PROBABILITY = "precipitation_probability"

# Daily aggregates (M14). Names match Open-Meteo's daily API exactly; a typo here would
# silently return a missing series, so each is validated after parsing.
VAR_DAILY_PRECIP_SUM = "precipitation_sum"
VAR_DAILY_PROB_MAX = "precipitation_probability_max"
VAR_DAILY_TMIN = "temperature_2m_min"
VAR_DAILY_TMAX = "temperature_2m_max"
VAR_DAILY_WCODE = "weather_code"
DAILY_VARS = (
    VAR_DAILY_PRECIP_SUM,
    VAR_DAILY_PROB_MAX,
    VAR_DAILY_TMIN,
    VAR_DAILY_TMAX,
    VAR_DAILY_WCODE,
)
# Open-Meteo allows 16 days; seven is what the UI shows and what was asked for.
MAX_DAILY_DAYS = 16

ACCEPTED_UNITS_PRECIP = {"mm": 1.0, "inch": 25.4, "inches": 25.4}

DEFAULT_TIMEOUT_S = 8.0
MAX_PLAUSIBLE_MM_PER_HOUR = 300.0      # sanity bound only; not a warning threshold
MAX_FORECAST_HOURS = 384               # Open-Meteo's documented ceiling is 16 days

Kind = Literal["forecast", "observation"]


class ForecastError(Exception):
    """Raised only for programmer error, never for provider failure."""


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HourlyRain:
    """One hourly value, with everything needed to display it honestly.

    `kind` is "forecast" for every record this adapter produces. An observation would need
    a different adapter and a different provenance label (R-04).
    """

    at: datetime                     # provider timestamp, normalised to UTC
    precipitation_mm: float | None   # None = provider omitted this hour
    probability_pct: float | None
    kind: Kind = "forecast"


@dataclass(frozen=True)
class DailyRain:
    """One calendar day of forecast, as the provider reports it.

    `date` is a plain `date`, not a datetime: a daily aggregate covers a whole day, and
    turning it into an instant would invent a precision the provider never claimed.

    Every value is Optional. `None` means **the provider did not supply it**, which is not
    the same as zero rain or zero probability, and the UI must render it as unavailable.
    """

    date: date
    precipitation_sum_mm: float | None
    probability_max_pct: float | None
    temperature_min_c: float | None
    temperature_max_c: float | None
    weather_code: int | None
    kind: Kind = "forecast"


@dataclass(frozen=True)
class ForecastResult:
    """The adapter's whole answer, including failures and provenance.

    A caller must check `ok` before using `hours`. On failure `hours` is empty — there is
    no partial-invention path.
    """

    ok: bool
    hours: tuple[HourlyRain, ...]
    source: str
    provider_units_original: str | None
    model_run_at: datetime | None
    fetched_at: datetime | None
    latitude: float | None
    longitude: float | None
    error: str | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)
    # Daily series. Empty when the provider was not asked for daily data, or on failure.
    days: tuple[DailyRain, ...] = field(default_factory=tuple)

    @property
    def total_mm(self) -> float:
        return round(sum(h.precipitation_mm or 0.0 for h in self.hours), 2)

    @property
    def max_hourly_mm(self) -> float | None:
        vals = [h.precipitation_mm for h in self.hours if h.precipitation_mm is not None]
        return round(max(vals), 2) if vals else None

    def age_seconds(self, now: datetime) -> float | None:
        """How old the FETCH is. Distinct from how old the model run is."""
        if self.fetched_at is None:
            return None
        return (now - self.fetched_at).total_seconds()


# ---------------------------------------------------------------------------
# Injectable HTTP
# ---------------------------------------------------------------------------

HttpGet = Callable[[str, float], tuple[int, str]]


def urllib_get(url: str, timeout_s: float = DEFAULT_TIMEOUT_S) -> tuple[int, str]:
    """Default HTTP GET. Returns (status_code, body_text).

    Network errors are converted to a status of 0 rather than raised, so the adapter has a
    single error path and tests never need to mock exceptions.
    """
    try:
        with urlopen(url, timeout=timeout_s) as resp:      # noqa: S310 - fixed provider host
            return int(getattr(resp, "status", 200)), resp.read().decode("utf-8", "replace")
    except HTTPError as exc:
        return int(exc.code), ""
    except (URLError, TimeoutError, OSError):
        return 0, ""


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _parse_iso(value: str) -> datetime:
    """Parse an Open-Meteo timestamp. Values are naive local to the requested timezone.

    We request `timezone=UTC` so a naive value is unambiguous; any offset present is
    honoured. A naive value is treated as UTC and this is stated, not assumed silently.
    """
    v = value.strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(v)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _normalise_units(unit: str | None, values: Sequence[float | None]) -> tuple[list[float | None], str, tuple[str, ...]]:
    """Convert precipitation to millimetres in exactly one place.

    Returns (converted_values, original_unit, notes). An unknown unit is an error, not a
    guess: displaying a mislabelled quantity is worse than displaying nothing.
    """
    notes: list[str] = []
    if unit is None:
        notes.append("provider did not state a precipitation unit; assuming mm is NOT safe")
        raise ForecastError("precipitation unit missing")
    u = unit.strip().lower()
    if u not in ACCEPTED_UNITS_PRECIP:
        raise ForecastError(f"unsupported precipitation unit {unit!r}")
    factor = ACCEPTED_UNITS_PRECIP[u]
    if u != "mm":
        notes.append(f"unit converted from {unit!r} to mm (factor {factor})")
    out = [None if v is None else round(float(v) * factor, 3) for v in values]
    return out, unit, tuple(notes)


def _validate_hour_values(
    values: Sequence[float | None], label: str
) -> tuple[list[float | None], tuple[str, ...]]:
    """Reject implausible magnitudes; keep None as None (a gap is a gap)."""
    notes: list[str] = []
    out: list[float | None] = []
    dropped = 0
    for v in values:
        if v is None:
            out.append(None)
            continue
        fv = float(v)
        if fv != fv or fv < 0:
            out.append(None)
            dropped += 1
            continue
        if fv > MAX_PLAUSIBLE_MM_PER_HOUR:
            out.append(None)
            dropped += 1
            continue
        out.append(fv)
    if dropped:
        notes.append(f"dropped {dropped} implausible {label} value(s) as missing")
    return out, tuple(notes)


def parse_open_meteo(
    payload: Any,
    *,
    fetched_at: datetime,
    latitude: float,
    longitude: float,
) -> ForecastResult:
    """Turn an Open-Meteo JSON payload into a ForecastResult.

    Raises ForecastError only for structurally unusable payloads (wrong shape, missing
    hourly block, unknown units). Missing individual values are kept as None.
    """
    notes: list[str] = []
    if not isinstance(payload, dict):
        raise ForecastError("payload is not a JSON object")
    if "error" in payload and payload.get("error"):
        raise ForecastError(f"provider reported an error: {payload.get('reason')!r}")
    hourly = payload.get("hourly")
    if not isinstance(hourly, dict):
        raise ForecastError("payload has no 'hourly' object")

    times = hourly.get("time")
    if not isinstance(times, list) or not times:
        raise ForecastError("hourly.time missing or empty")

    units = payload.get("hourly_units") or {}
    if not isinstance(units, dict):
        units = {}

    precip_raw = hourly.get(VAR_PRECIPITATION)
    prob_raw = hourly.get(VAR_PROBABILITY)
    if precip_raw is None and prob_raw is None:
        raise ForecastError("payload contains neither precipitation nor probability")

    if precip_raw is not None and not isinstance(precip_raw, list):
        raise ForecastError("hourly.precipitation is not a list")
    if prob_raw is not None and not isinstance(prob_raw, list):
        raise ForecastError("hourly.precipitation_probability is not a list")

    orig_unit = units.get(VAR_PRECIPITATION)
    if precip_raw is not None:
        precip_vals, orig_unit, unit_notes = _normalise_units(orig_unit, precip_raw)
        notes.extend(unit_notes)
    else:
        precip_vals = [None] * len(times)
        orig_unit = None
        notes.append("provider returned no precipitation values; probability only")

    precip_vals, val_notes = _validate_hour_values(precip_vals, "precipitation")
    notes.extend(val_notes)

    prob_vals: list[float | None]
    if prob_raw is not None:
        raw_probs, prob_notes = _validate_probabilities(prob_raw)
        prob_vals = raw_probs
        notes.extend(prob_notes)
    else:
        prob_vals = [None] * len(times)
        notes.append("provider returned no probability values")

    if len(precip_vals) != len(times):
        raise ForecastError(
            f"length mismatch: {len(times)} timestamps vs {len(precip_vals)} precipitation values"
        )
    if len(prob_vals) != len(times):
        raise ForecastError(
            f"length mismatch: {len(times)} timestamps vs {len(prob_vals)} probability values"
        )

    hours: list[HourlyRain] = []
    for i, t in enumerate(times):
        try:
            at = _parse_iso(str(t))
        except (ValueError, TypeError) as exc:
            raise ForecastError(f"unparseable timestamp {t!r}") from exc
        hours.append(
            HourlyRain(
                at=at,
                precipitation_mm=precip_vals[i],
                probability_pct=prob_vals[i],
                # Every value from a forecast endpoint is a forecast. Never an observation.
                kind="forecast",
            )
        )

    # Open-Meteo does not return a model run time in the default response. We record the
    # fetch time and say so explicitly rather than implying we know the model vintage.
    notes.append(
        "provider response includes no model run time; only the fetch time is known"
    )

    days = _parse_daily(payload, notes)

    return ForecastResult(
        ok=True,
        hours=tuple(hours),
        days=days,
        source="open-meteo",
        provider_units_original=orig_unit,
        model_run_at=None,
        fetched_at=fetched_at,
        latitude=latitude,
        longitude=longitude,
        error=None,
        notes=tuple(notes),
    )



def _parse_daily(
    payload: dict, notes: list[str]
) -> tuple[DailyRain, ...]:
    """Parse the daily block. Missing series yield None, never a fabricated zero.

    Deliberate behaviours, each guarding a specific way this could mislead:

    * A **missing daily block entirely** is not an error — an hourly-only response is still a
      valid forecast. It yields an empty tuple and a note, so the UI can hide the 7-day view
      rather than show blanks or invented numbers.
    * A **missing individual value** (provider returns `null`) becomes None. Rendering that as
      0 mm would turn "the model has no answer" into "it will not rain", which is precisely the
      false reassurance this project forbids.
    * A **length mismatch** between the date series and a value series is reported and the
      shorter length is used, with a note. Silently zipping would misalign dates against the
      wrong days — a subtle, serious error in a forecast.
    * Units are checked. A non-mm precipitation unit aborts rather than being assumed.
    """
    daily = payload.get("daily")
    if not isinstance(daily, dict):
        notes.append("provider returned no daily block; the 7-day view is unavailable")
        return ()

    dates = daily.get("time")
    if not isinstance(dates, list) or not dates:
        notes.append("daily.time missing or empty; the 7-day view is unavailable")
        return ()

    units = payload.get("daily_units") or {}
    if not isinstance(units, dict):
        units = {}

    precip_unit = units.get(VAR_DAILY_PRECIP_SUM)
    if precip_unit is not None and precip_unit.lower() not in ("mm", "millimetres", "millimeters"):
        raise ForecastError(
            f"unsupported daily precipitation unit {precip_unit!r}; refusing to assume mm"
        )

    def series(key: str, expected_len: int) -> list[Any]:
        raw = daily.get(key)
        if not isinstance(raw, list):
            notes.append(f"daily.{key} absent from the response")
            return [None] * expected_len
        if len(raw) != expected_len:
            notes.append(
                f"daily.{key} has {len(raw)} values for {expected_len} dates; "
                "values are aligned positionally and the missing tail is left unavailable"
            )
            # Pad rather than truncate. Truncating would silently drop days; returning the short
            # list raised IndexError below. Padding keeps each value on the day it belongs to and
            # makes the missing tail explicitly None.
            raw = list(raw[:expected_len]) + [None] * (expected_len - len(raw))
        return raw

    n = len(dates)
    precip = series(VAR_DAILY_PRECIP_SUM, n)
    prob = series(VAR_DAILY_PROB_MAX, n)
    tmin = series(VAR_DAILY_TMIN, n)
    tmax = series(VAR_DAILY_TMAX, n)
    wcode = series(VAR_DAILY_WCODE, n)

    def num(v: Any) -> float | None:
        if v is None or isinstance(v, bool):
            return None
        try:
            f = float(v)
        except (TypeError, ValueError):
            return None
        # NaN / infinity are not "no data" — they are corrupt, and must not be rendered.
        if f != f or f in (float("inf"), float("-inf")):
            return None
        return f

    out: list[DailyRain] = []
    for i in range(n):
        try:
            d = date.fromisoformat(str(dates[i]))
        except (TypeError, ValueError):
            notes.append(f"unparseable daily date {dates[i]!r} skipped")
            continue

        p = num(precip[i])
        if p is not None and p < 0:
            # Negative rainfall is physically impossible; treat as absent rather than clamp to 0,
            # because clamping would hide a provider fault.
            notes.append(f"negative daily precipitation {p} on {d} treated as unavailable")
            p = None

        prob_i = num(prob[i])
        if prob_i is not None and not 0 <= prob_i <= 100:
            notes.append(f"daily probability {prob_i} on {d} outside 0..100 treated as unavailable")
            prob_i = None

        out.append(
            DailyRain(
                date=d,
                precipitation_sum_mm=round(p, 2) if p is not None else None,
                probability_max_pct=round(prob_i, 0) if prob_i is not None else None,
                temperature_min_c=num(tmin[i]),
                temperature_max_c=num(tmax[i]),
                weather_code=int(wcode[i]) if isinstance(wcode[i], (int, float)) else None,
            )
        )

    return tuple(out)



def _validate_probabilities(values: Sequence[Any]) -> tuple[list[float | None], tuple[str, ...]]:
    out: list[float | None] = []
    dropped = 0
    for v in values:
        if v is None:
            out.append(None)
            continue
        try:
            fv = float(v)
        except (TypeError, ValueError):
            out.append(None)
            dropped += 1
            continue
        if fv != fv or fv < 0 or fv > 100:
            out.append(None)
            dropped += 1
            continue
        out.append(round(fv, 1))
    notes = (f"dropped {dropped} out-of-range probability value(s)",) if dropped else ()
    return out, notes


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


def build_forecast_url(
    base_url: str,
    latitude: float,
    longitude: float,
    *,
    forecast_hours: int = 48,
    forecast_days: int = 7,
) -> str:
    """Construct the request URL.

    `timezone=UTC` is requested so timestamps are unambiguous, and probability is always
    asked for. No `past_days` — this adapter must never blur observation into forecast.
    """
    if not -90 <= latitude <= 90:
        raise ValueError("latitude out of range")
    if not -180 <= longitude <= 180:
        raise ValueError("longitude out of range")
    if not 1 <= forecast_hours <= MAX_FORECAST_HOURS:
        raise ValueError(f"forecast_hours must be within 1..{MAX_FORECAST_HOURS}")
    if not 1 <= forecast_days <= MAX_DAILY_DAYS:
        raise ValueError(f"forecast_days must be within 1..{MAX_DAILY_DAYS}")
    # `forecast_days` and `forecast_hours` are both accepted by Open-Meteo; requesting days
    # covers the 7-day view while the hourly series serves the next-24h chart.
    params = {
        "latitude": f"{latitude:.6f}",
        "longitude": f"{longitude:.6f}",
        "hourly": f"{VAR_PRECIPITATION},{VAR_PROBABILITY}",
        "daily": ",".join(DAILY_VARS),
        "forecast_hours": str(forecast_hours),
        "forecast_days": str(forecast_days),
        "timezone": "UTC",
    }
    return f"{base_url.rstrip('/')}/forecast?{urlencode(params)}"


def fetch_forecast(
    *,
    base_url: str,
    latitude: float,
    longitude: float,
    now: datetime,
    http_get: HttpGet = urllib_get,
    forecast_hours: int = 48,
    forecast_days: int = 7,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> ForecastResult:
    """Fetch and parse a rainfall forecast. Never raises for provider failure.

    On any failure the result has ok=False, empty hours, and an honest error string. The
    caller decides whether to show cached data or nothing; this adapter never invents mm.
    """
    try:
        url = build_forecast_url(
            base_url, latitude, longitude,
            forecast_hours=forecast_hours, forecast_days=forecast_days,
        )
    except ValueError as exc:
        return _failure(str(exc), latitude, longitude, now, "invalid request parameters")

    status, body = http_get(url, timeout_s)

    if status == 0:
        return _failure(
            "network unavailable or timed out", latitude, longitude, now,
            "provider unreachable",
        )
    if status == 429:
        return _failure(
            "provider rate-limited the request (HTTP 429)", latitude, longitude, now,
            "rate limited",
        )
    if status >= 400:
        return _failure(
            f"provider returned HTTP {status}", latitude, longitude, now, "provider error"
        )
    if not body.strip():
        return _failure(
            "provider returned an empty body", latitude, longitude, now, "malformed response"
        )

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        return _failure(
            f"response was not valid JSON ({exc.msg})", latitude, longitude, now,
            "malformed response",
        )

    try:
        return parse_open_meteo(
            payload, fetched_at=now, latitude=latitude, longitude=longitude
        )
    except ForecastError as exc:
        return _failure(str(exc), latitude, longitude, now, "unusable payload")


def _failure(
    error: str, latitude: float, longitude: float, now: datetime, note: str
) -> ForecastResult:
    return ForecastResult(
        ok=False,
        hours=(),
        source="open-meteo",
        provider_units_original=None,
        model_run_at=None,
        fetched_at=now,
        latitude=latitude,
        longitude=longitude,
        error=error,
        notes=(note, "no values were invented; caller must show cached data or nothing"),
    )


# ---------------------------------------------------------------------------
# Presentation helper — the only place mm may be described to a user
# ---------------------------------------------------------------------------


def describe(result: ForecastResult, now: datetime) -> str:
    """A one-line, honest summary. Contains NO heavy-rain classification (B13).

    Deliberately says "forecast" and shows absolute millimetres plus the fetch age. It does
    not say "heavy rain", because no approved threshold exists.
    """
    if not result.ok:
        return f"Rainfall forecast unavailable ({result.error}). No estimate is shown."

    age = result.age_seconds(now)
    age_txt = "just now" if age is None else f"{int(max(age, 0) // 60)} min ago"
    peak = result.max_hourly_mm
    peak_txt = "no hourly value" if peak is None else f"peak {peak:g} mm in one hour"
    return (
        f"Forecast (not an observation): {result.total_mm:g} mm total over "
        f"{len(result.hours)} hours, {peak_txt}. Retrieved {age_txt}."
    )
