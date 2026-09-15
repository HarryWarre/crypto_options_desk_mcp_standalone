"""Observed and interpolated volatility surfaces for option valuation.

The module is intentionally independent from any exchange adapter.  Callers
convert their normalized market records into :class:`VolatilityObservation`
objects, then use the returned surface as the fair-IV input to a pricing
model.  IV is a decimal (``0.42`` means 42%) and interpolation is performed
on total variance rather than directly on IV.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Literal

SurfacePointStatus = Literal["observed", "interpolated", "extrapolated"]


class VolatilitySurfaceError(ValueError):
    """Base error for an unusable or invalid surface query."""


class InsufficientDataError(VolatilitySurfaceError):
    """Raised when a surface does not contain enough data for a query."""


class ExtrapolationError(VolatilitySurfaceError):
    """Raised when a query is outside the fitted surface range."""


@dataclass(frozen=True)
class VolatilityObservation:
    """One normalized option observation used to build a surface.

    ``iv`` is an annualized decimal volatility.  Either a positive bid/ask
    quote or a positive ``liquidity`` score is required.  ``forward`` can be
    omitted for spot-based instruments and then falls back to ``spot``.
    Expiry accepts an aware/naive datetime, a date, ISO text, or a Bybit-style
    code such as ``25SEP26``.  Naive datetimes are interpreted as UTC.
    """

    asset: str
    expiry: datetime | date | str
    strike: float
    spot: float
    iv: float
    forward: float | None = None
    bid: float | None = None
    ask: float | None = None
    liquidity: float | None = None


@dataclass(frozen=True)
class SurfaceWarning:
    """A quality or model warning attached to a surface."""

    code: str
    message: str
    asset: str
    expiry: datetime | None = None
    strike: float | None = None


@dataclass(frozen=True)
class SurfacePoint:
    """A surface point, either observed or produced by a query."""

    asset: str
    expiry: datetime
    strike: float
    forward: float
    time_to_expiry: float
    log_moneyness: float
    iv: float
    total_variance: float
    status: SurfacePointStatus


@dataclass(frozen=True)
class SurfaceConfig:
    """Quality thresholds for surface construction."""

    minimum_liquidity: float = 1.0
    maximum_iv: float = 5.0
    minimum_points_per_expiry: int = 2

    def __post_init__(self) -> None:
        if self.minimum_liquidity < 0:
            raise ValueError("minimum_liquidity cannot be negative")
        if self.maximum_iv <= 0:
            raise ValueError("maximum_iv must be positive")
        if self.minimum_points_per_expiry < 2:
            raise ValueError("minimum_points_per_expiry must be at least 2")


@dataclass(frozen=True)
class _NormalizedObservation:
    asset: str
    expiry: datetime
    strike: float
    forward: float
    iv: float
    bid: float | None
    ask: float | None
    liquidity: float | None
    time_to_expiry: float
    log_moneyness: float
    total_variance: float


@dataclass(frozen=True)
class ExpirySlice:
    """Chronological observed points for one expiry."""

    expiry: datetime
    time_to_expiry: float
    forward: float
    points: tuple[SurfacePoint, ...]


@dataclass(frozen=True)
class VolatilitySurface:
    """One asset's observed surface and its fair-IV query seam."""

    asset: str
    valuation_time: datetime
    observed_points: tuple[SurfacePoint, ...]
    slices: tuple[ExpirySlice, ...]
    warnings: tuple[SurfaceWarning, ...]
    is_valuation_ready: bool
    minimum_points_per_expiry: int

    @property
    def front_expiry(self) -> datetime | None:
        return self.slices[0].expiry if self.slices else None

    @property
    def back_expiry(self) -> datetime | None:
        return self.slices[-1].expiry if self.slices else None

    def quote(
        self,
        *,
        expiry: datetime | date | str,
        strike: float,
        forward: float | None = None,
        allow_extrapolation: bool = False,
        prefer_observed: bool = True,
    ) -> SurfacePoint:
        """Return fair IV at a requested expiry/strike.

        Interpolation is linear in log-moneyness and total variance.  If the
        request is outside the observed strike or expiry range, the default
        is to raise :class:`ExtrapolationError`; callers must opt into a
        result marked ``extrapolated``.
        """

        if not self.is_valuation_ready:
            raise InsufficientDataError(
                f"{self.asset} surface needs at least two valid points per expiry"
            )

        target_expiry = _coerce_expiry(expiry)
        target_strike = _finite_positive(strike, "strike")
        if target_expiry <= self.valuation_time:
            raise VolatilitySurfaceError("expiry must be after valuation time")

        usable = tuple(
            surface_slice
            for surface_slice in self.slices
            if len(surface_slice.points) >= self.minimum_points_per_expiry
        )
        if not usable:
            raise InsufficientDataError(
                f"{self.asset} surface needs at least two valid points per expiry"
            )

        exact_slice = next(
            (surface_slice for surface_slice in usable if surface_slice.expiry == target_expiry),
            None,
        )
        if exact_slice is not None:
            query_forward = (
                exact_slice.forward
                if forward is None
                else _finite_positive(forward, "forward")
            )
            variance, status = _variance_at_slice(
                exact_slice,
                target_strike,
                query_forward,
                allow_extrapolation,
                prefer_observed=prefer_observed,
            )
            return _make_query_point(
                self.asset,
                target_expiry,
                target_strike,
                query_forward,
                variance,
                exact_slice.time_to_expiry,
                status,
            )

        lower, upper = _bracket_slices(usable, target_expiry)
        target_time = _year_fraction(self.valuation_time, target_expiry)
        if lower is None or upper is None:
            if not allow_extrapolation:
                raise ExtrapolationError(
                    f"expiry {target_expiry.isoformat()} is outside the surface range"
                )
            if len(usable) < 2:
                raise InsufficientDataError(
                    "at least two expiries are required for expiry extrapolation"
                )
            if target_expiry < usable[0].expiry:
                lower, upper = usable[0], usable[1]
            else:
                lower, upper = usable[-2], usable[-1]
            status: SurfacePointStatus = "extrapolated"
        else:
            status = "interpolated"

        if forward is None:
            weight = (target_time - lower.time_to_expiry) / (
                upper.time_to_expiry - lower.time_to_expiry
            )
            query_forward = lower.forward + weight * (upper.forward - lower.forward)
        else:
            query_forward = _finite_positive(forward, "forward")

        lower_variance, lower_status = _variance_at_slice(
            lower,
            target_strike,
            query_forward,
            allow_extrapolation,
            prefer_observed=prefer_observed,
        )
        upper_variance, upper_status = _variance_at_slice(
            upper,
            target_strike,
            query_forward,
            allow_extrapolation,
            prefer_observed=prefer_observed,
        )
        if "extrapolated" in {lower_status, upper_status}:
            status = "extrapolated"
        time_weight = (target_time - lower.time_to_expiry) / (
            upper.time_to_expiry - lower.time_to_expiry
        )
        variance = lower_variance + time_weight * (upper_variance - lower_variance)
        return _make_query_point(
            self.asset,
            target_expiry,
            target_strike,
            query_forward,
            variance,
            target_time,
            status,
        )


@dataclass(frozen=True)
class VolatilitySurfaceResult:
    """Deterministic multi-asset surface build result."""

    surfaces: tuple[VolatilitySurface, ...]
    assets: tuple[str, ...]

    def surface_for(self, asset: str) -> VolatilitySurface:
        normalized_asset = str(asset).strip().upper()
        for surface in self.surfaces:
            if surface.asset == normalized_asset:
                return surface
        raise KeyError(f"No volatility surface for {normalized_asset}")


def build_volatility_surface(
    observations: Iterable[VolatilityObservation | Mapping[str, Any]],
    *,
    valuation_time: datetime,
    config: SurfaceConfig | None = None,
) -> VolatilitySurfaceResult:
    """Build deterministic observed surfaces for all assets in ``observations``.

    Bad observations become explicit warnings and are excluded.  A sparse
    asset still returns a surface object, but ``is_valuation_ready`` is false
    and every quote attempt raises ``InsufficientDataError``.
    """

    surface_config = config or SurfaceConfig()
    as_of = _coerce_expiry(valuation_time)
    normalized_by_asset: dict[str, dict[tuple[datetime, float], _NormalizedObservation]] = defaultdict(dict)
    warnings_by_asset: dict[str, list[SurfaceWarning]] = defaultdict(list)
    assets: set[str] = set()

    for raw in observations:
        asset = _asset_name(raw)
        assets.add(asset)
        normalized, warning = _normalize_observation(raw, as_of, surface_config)
        if warning is not None:
            warnings_by_asset[asset].append(warning)
        if normalized is None:
            continue
        key = (normalized.expiry, normalized.strike)
        previous = normalized_by_asset[asset].get(key)
        if previous is None:
            normalized_by_asset[asset][key] = normalized
            continue
        warnings_by_asset[asset].append(
            SurfaceWarning(
                code="duplicate_point",
                message="Duplicate expiry/strike kept the higher-quality observation",
                asset=asset,
                expiry=normalized.expiry,
                strike=normalized.strike,
            )
        )
        if _observation_rank(normalized) > _observation_rank(previous):
            normalized_by_asset[asset][key] = normalized

    surfaces: list[VolatilitySurface] = []
    for asset in sorted(assets):
        points_by_expiry: dict[datetime, list[_NormalizedObservation]] = defaultdict(list)
        for normalized in normalized_by_asset[asset].values():
            points_by_expiry[normalized.expiry].append(normalized)

        slices: list[ExpirySlice] = []
        for expiry in sorted(points_by_expiry):
            observations_for_expiry = sorted(
                points_by_expiry[expiry], key=lambda item: (item.log_moneyness, item.strike)
            )
            forward = _median(item.forward for item in observations_for_expiry)
            points = tuple(
                SurfacePoint(
                    asset=asset,
                    expiry=item.expiry,
                    strike=item.strike,
                    forward=item.forward,
                    time_to_expiry=item.time_to_expiry,
                    log_moneyness=item.log_moneyness,
                    iv=item.iv,
                    total_variance=item.total_variance,
                    status="observed",
                )
                for item in observations_for_expiry
            )
            slices.append(
                ExpirySlice(
                    expiry=expiry,
                    time_to_expiry=observations_for_expiry[0].time_to_expiry,
                    forward=forward,
                    points=points,
                )
            )
            if len(points) < surface_config.minimum_points_per_expiry:
                warnings_by_asset[asset].append(
                    SurfaceWarning(
                        code="insufficient_data",
                        message=(
                            f"Expiry has {len(points)} valid points; at least "
                            f"{surface_config.minimum_points_per_expiry} are required"
                        ),
                        asset=asset,
                        expiry=expiry,
                    )
                )

        ordered_slices = tuple(slices)
        observed_points = tuple(point for surface_slice in ordered_slices for point in surface_slice.points)
        usable = any(
            len(surface_slice.points) >= surface_config.minimum_points_per_expiry
            for surface_slice in ordered_slices
        )
        ordered_warnings = tuple(
            sorted(
                warnings_by_asset[asset],
                key=lambda warning: (
                    warning.code,
                    warning.expiry or datetime.min.replace(tzinfo=UTC),
                    warning.strike if warning.strike is not None else -math.inf,
                    warning.message,
                ),
            )
        )
        surfaces.append(
            VolatilitySurface(
                asset=asset,
                valuation_time=as_of,
                observed_points=observed_points,
                slices=ordered_slices,
                warnings=ordered_warnings,
                is_valuation_ready=usable,
                minimum_points_per_expiry=surface_config.minimum_points_per_expiry,
            )
        )

    return VolatilitySurfaceResult(tuple(surfaces), tuple(sorted(assets)))


def _normalize_observation(
    raw: VolatilityObservation | Mapping[str, Any],
    valuation_time: datetime,
    config: SurfaceConfig,
) -> tuple[_NormalizedObservation | None, SurfaceWarning | None]:
    asset = _asset_name(raw)
    value = _value_getter(raw)
    try:
        expiry = _coerce_expiry(value("expiry"))
    except (TypeError, ValueError):
        return None, SurfaceWarning("invalid_expiry", "Expiry is not a real date/time", asset)
    try:
        strike = _finite_positive(value("strike"), "strike")
        spot = _finite_positive(value("spot"), "spot")
        raw_forward = value("forward")
        forward = _finite_positive(
            spot if raw_forward is None or raw_forward == "" else raw_forward,
            "forward",
        )
    except ValueError as exc:
        return None, SurfaceWarning("invalid_price", str(exc), asset, expiry)

    try:
        iv = _finite_number(value("iv"), "iv")
    except ValueError as exc:
        return None, SurfaceWarning("invalid_iv", str(exc), asset, expiry, strike)
    if iv <= 0 or iv > config.maximum_iv:
        return None, SurfaceWarning(
            "invalid_iv",
            f"IV must be greater than 0 and no more than {config.maximum_iv}",
            asset,
            expiry,
            strike,
        )
    if expiry <= valuation_time:
        return None, SurfaceWarning(
            "expired_observation", "Observation expiry is not after valuation time", asset, expiry, strike
        )

    bid = _optional_number(value("bid"))
    ask = _optional_number(value("ask"))
    liquidity = _optional_number(value("liquidity"))
    has_quote_fields = value("bid") is not None or value("ask") is not None
    if has_quote_fields:
        if bid is None or ask is None or bid <= 0 or ask <= 0:
            return None, SurfaceWarning(
                "zero_quote", "Bid and ask must both be positive", asset, expiry, strike
            )
        if ask < bid:
            return None, SurfaceWarning(
                "invalid_quote", "Ask cannot be below bid", asset, expiry, strike
            )
    elif liquidity is None or liquidity < config.minimum_liquidity:
        return None, SurfaceWarning(
            "insufficient_liquidity",
            f"A positive quote or liquidity of at least {config.minimum_liquidity} is required",
            asset,
            expiry,
            strike,
        )

    time_to_expiry = _year_fraction(valuation_time, expiry)
    log_moneyness = math.log(strike / forward)
    return (
        _NormalizedObservation(
            asset=asset,
            expiry=expiry,
            strike=strike,
            forward=forward,
            iv=iv,
            bid=bid,
            ask=ask,
            liquidity=liquidity,
            time_to_expiry=time_to_expiry,
            log_moneyness=log_moneyness,
            total_variance=iv**2 * time_to_expiry,
        ),
        None,
    )


def _variance_at_slice(
    surface_slice: ExpirySlice,
    strike: float,
    forward: float,
    allow_extrapolation: bool,
    *,
    prefer_observed: bool = True,
) -> tuple[float, SurfacePointStatus]:
    target_x = math.log(strike / forward)
    points = surface_slice.points
    if len(points) < 2:
        raise InsufficientDataError("at least two valid points per expiry are required")
    exact_index = next(
        (
            index
            for index, point in enumerate(points)
            if math.isclose(target_x, point.log_moneyness, rel_tol=0.0, abs_tol=1e-12)
            and math.isclose(strike, point.strike, rel_tol=1e-12, abs_tol=1e-12)
        ),
        None,
    )
    if exact_index is not None and prefer_observed:
        return points[exact_index].total_variance, "observed"
    if exact_index is not None and not prefer_observed:
        if exact_index == 0 or exact_index == len(points) - 1:
            raise InsufficientDataError(
                "a fitted quote at the observed surface boundary needs a neighboring strike"
            )
        left = points[exact_index - 1]
        right = points[exact_index + 1]
        weight = (target_x - left.log_moneyness) / (
            right.log_moneyness - left.log_moneyness
        )
        variance = left.total_variance + weight * (right.total_variance - left.total_variance)
        return variance, "interpolated"

    if target_x < points[0].log_moneyness:
        if not allow_extrapolation:
            raise ExtrapolationError("strike is below the observed surface range")
        left, right = points[0], points[1]
        status: SurfacePointStatus = "extrapolated"
    elif target_x > points[-1].log_moneyness:
        if not allow_extrapolation:
            raise ExtrapolationError("strike is above the observed surface range")
        left, right = points[-2], points[-1]
        status = "extrapolated"
    else:
        right_index = next(
            index for index, point in enumerate(points) if point.log_moneyness >= target_x
        )
        if right_index == 0:
            return points[0].total_variance, "observed"
        left, right = points[right_index - 1], points[right_index]
        status = "interpolated"

    weight = (target_x - left.log_moneyness) / (right.log_moneyness - left.log_moneyness)
    variance = left.total_variance + weight * (right.total_variance - left.total_variance)
    return variance, status


def _make_query_point(
    asset: str,
    expiry: datetime,
    strike: float,
    forward: float,
    variance: float,
    time_to_expiry: float,
    status: SurfacePointStatus,
) -> SurfacePoint:
    if variance <= 0 or not math.isfinite(variance):
        raise VolatilitySurfaceError("interpolation produced a non-positive total variance")
    return SurfacePoint(
        asset=asset,
        expiry=expiry,
        strike=strike,
        forward=forward,
        time_to_expiry=time_to_expiry,
        log_moneyness=math.log(strike / forward),
        iv=math.sqrt(variance / time_to_expiry),
        total_variance=variance,
        status=status,
    )


def _bracket_slices(
    slices: tuple[ExpirySlice, ...], expiry: datetime
) -> tuple[ExpirySlice | None, ExpirySlice | None]:
    lower = None
    upper = None
    for surface_slice in slices:
        if surface_slice.expiry < expiry:
            lower = surface_slice
        elif surface_slice.expiry > expiry:
            upper = surface_slice
            break
    return lower, upper


def _observation_rank(observation: _NormalizedObservation) -> tuple[float, float, float, float]:
    spread = (
        observation.ask - observation.bid
        if observation.bid is not None and observation.ask is not None
        else math.inf
    )
    return (
        1.0 if observation.bid is not None and observation.ask is not None else 0.0,
        observation.liquidity if observation.liquidity is not None else -1.0,
        -spread,
        -observation.iv,
    )


def _value_getter(raw: VolatilityObservation | Mapping[str, Any]):
    if isinstance(raw, Mapping):
        return raw.get
    return lambda field: getattr(raw, field, None)


def _asset_name(raw: VolatilityObservation | Mapping[str, Any]) -> str:
    value = _value_getter(raw)("asset")
    asset = str(value or "").strip().upper()
    return asset or "UNKNOWN"


def _coerce_expiry(value: Any) -> datetime:
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, date):
        result = datetime.combine(value, datetime.min.time())
    elif isinstance(value, str):
        text = value.strip()
        try:
            result = datetime.fromisoformat(text)
        except ValueError:
            # Bybit option delivery occurs at 08:00 UTC. A date code alone
            # does not contain the delivery timestamp, so make that convention
            # explicit instead of silently using midnight.
            result = datetime.strptime(text.upper(), "%d%b%y").replace(
                hour=8, tzinfo=UTC
            )
    else:
        raise TypeError("expiry must be a date, datetime, ISO string, or Bybit expiry code")
    if result.tzinfo is None:
        result = result.replace(tzinfo=UTC)
    return result.astimezone(UTC)


def _finite_number(value: Any, name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(result):
        raise ValueError(f"{name} must be a finite number")
    return result


def _finite_positive(value: Any, name: str) -> float:
    result = _finite_number(value, name)
    if result <= 0:
        raise ValueError(f"{name} must be positive")
    return result


def _optional_number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _year_fraction(start: datetime, end: datetime) -> float:
    seconds = (end - start).total_seconds()
    if seconds <= 0:
        raise ValueError("expiry must be after valuation time")
    return seconds / (365.0 * 24.0 * 60.0 * 60.0)


def _median(values: Iterable[float]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2
