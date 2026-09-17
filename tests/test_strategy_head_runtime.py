from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from options_lib.strategy_head_runtime import (
    NO_TRADE,
    SELECT_STRATEGIES,
    RuntimeScanDecision,
    StrategyHeadRuntime,
    apply_strategy_decision,
)

AS_OF = datetime(2026, 9, 17, 10, 0, tzinfo=UTC)


@dataclass(frozen=True)
class FakeMarketContext:
    observed_at: datetime
    features: dict[str, float]


class FakeHead:
    def __init__(self, prediction: object) -> None:
        self.prediction = prediction
        self.calls: list[dict[str, object]] = []

    def predict(self, features: dict[str, object]) -> object:
        self.calls.append(features)
        return self.prediction


class RaisingHead:
    def __init__(self) -> None:
        self.calls = 0

    def predict(self, features: dict[str, object]) -> object:
        self.calls += 1
        raise RuntimeError("model unavailable")


@dataclass(frozen=True)
class FakeScanRequest:
    strategies: tuple[str, ...] = ("long_put",)
    max_results: int = 10


def _context() -> FakeMarketContext:
    return FakeMarketContext(
        observed_at=AS_OF,
        features={"spot_price": 100.0, "volatility": 0.8},
    )


def _runtime(head: object | None = None, **kwargs: object) -> StrategyHeadRuntime:
    return StrategyHeadRuntime(
        head,
        required_features=("spot_price", "volatility"),
        **kwargs,
    )


def _automatic(runtime: StrategyHeadRuntime, **kwargs: object) -> RuntimeScanDecision:
    market_context = kwargs.pop("market_context", _context())
    now = kwargs.pop("now", AS_OF + timedelta(minutes=5))
    return runtime.decide(
        mode="automatic",
        market_context=market_context,
        now=now,
        **kwargs,
    )


def test_automatic_mode_selects_families_without_selecting_contract_or_order() -> None:
    head = FakeHead(
        {
            "selected_strategy_families": ["bull_call_vertical", "long_call"],
            "ranking_score": 0.82,
        }
    )

    decision = _automatic(_runtime(head, min_ranking_score=0.7))

    assert decision.action == SELECT_STRATEGIES
    assert decision.should_scan is True
    assert decision.selected_strategy_families == ("bull_call_vertical", "long_call")
    assert decision.ranking_score == pytest.approx(0.82)
    assert decision.reason_codes == ("lightgbm_selection",)
    assert head.calls == [{"spot_price": 100.0, "volatility": 0.8}]
    assert not hasattr(decision, "symbol")
    assert not hasattr(decision, "order")


def test_manual_mode_bypasses_model_and_uses_explicit_families() -> None:
    head = RaisingHead()

    decision = _runtime(head).decide(
        mode="manual",
        manual_strategies=("long_call", "long_call", "bear_put_vertical"),
    )

    assert decision == RuntimeScanDecision(
        action=SELECT_STRATEGIES,
        selected_strategy_families=("long_call", "bear_put_vertical"),
        reason_codes=("manual_selection",),
    )
    assert head.calls == 0


@pytest.mark.parametrize(
    ("head", "runtime_kwargs", "call_kwargs", "reason"),
    [
        (None, {}, {}, "head_unavailable"),
        (
            FakeHead({"selected_strategy_families": ["not_a_strategy"], "ranking_score": 0.99}),
            {},
            {},
            "invalid_prediction",
        ),
        (
            FakeHead({"selected_strategy_families": ["long_call"], "ranking_score": 0.99}),
            {},
            {"market_context": FakeMarketContext(AS_OF, {"spot_price": 100.0})},
            "features_unavailable",
        ),
        (
            FakeHead({"selected_strategy_families": ["long_call"], "ranking_score": 0.99}),
            {"max_context_age": timedelta(minutes=10)},
            {"now": AS_OF + timedelta(minutes=11)},
            "stale_context",
        ),
        (
            FakeHead({"selected_strategy_families": ["long_call"], "ranking_score": 0.49}),
            {"min_ranking_score": 0.5},
            {},
            "below_threshold",
        ),
    ],
)
def test_automatic_failures_return_no_trade_without_fallback(
    head: object | None,
    runtime_kwargs: dict[str, object],
    call_kwargs: dict[str, object],
    reason: str,
) -> None:
    decision = _automatic(_runtime(head, **runtime_kwargs), **call_kwargs)

    assert decision.action == NO_TRADE
    assert decision.should_scan is False
    assert decision.selected_strategy_families == ()
    assert decision.reason_codes == (reason, "fallback_used", "no_fallback_strategies")


def test_invalid_model_exception_uses_configured_safe_fallback() -> None:
    head = RaisingHead()

    decision = _automatic(_runtime(head, fallback_strategies=("long_put",)))

    assert decision.action == SELECT_STRATEGIES
    assert decision.selected_strategy_families == ("long_put",)
    assert decision.reason_codes == (
        "invalid_model",
        "fallback_used",
        "fallback_selection",
    )
    assert head.calls == 1


def test_no_trade_is_not_applied_to_a_scan_request() -> None:
    request = FakeScanRequest()
    decision = RuntimeScanDecision(action=NO_TRADE, reason_codes=("stale_context",))

    prepared = apply_strategy_decision(request, decision)

    assert prepared is None
    assert request.strategies == ("long_put",)


def test_scan_decision_copies_request_with_selected_strategies() -> None:
    request = FakeScanRequest()
    decision = RuntimeScanDecision(
        action=SELECT_STRATEGIES,
        selected_strategy_families=("iron_condor", "long_strangle"),
        ranking_score=0.91,
        reason_codes=("lightgbm_selection",),
    )

    prepared = apply_strategy_decision(request, decision)

    assert prepared == FakeScanRequest(
        strategies=("iron_condor", "long_strangle"),
        max_results=10,
    )
    assert request.strategies == ("long_put",)


def test_shared_prediction_shape_is_adapted_without_importing_shared_contract() -> None:
    @dataclass(frozen=True)
    class Ranking:
        strategy_family: str
        ranking_score: float

    @dataclass(frozen=True)
    class Metadata:
        framework: str = "lightgbm"

    @dataclass(frozen=True)
    class SharedPredictionShape:
        action: str
        ranked_strategies: tuple[Ranking, ...]
        selected_strategy_families: tuple[str, ...]
        reason_codes: tuple[str, ...]
        model_metadata: Metadata

    head = FakeHead(
        SharedPredictionShape(
            action="select_strategies",
            ranked_strategies=(Ranking("long_call", 12.5), Ranking("long_put", -4.0)),
            selected_strategy_families=("long_call",),
            reason_codes=("model_ranked",),
            model_metadata=Metadata(),
        )
    )

    decision = _automatic(_runtime(head, min_ranking_score=10.0))

    assert decision.action == SELECT_STRATEGIES
    assert decision.selected_strategy_families == ("long_call",)
    assert decision.ranking_score == pytest.approx(12.5)
    assert decision.reason_codes == ("model_ranked", "lightgbm_selection")
