from datetime import UTC, datetime

import pytest

from options_lib.strategy_head import (
    DecisionAction,
    DecisionSource,
    MarketContext,
    ModelMetadata,
    ReasonCode,
    SelectionMode,
    StrategyHeadDecision,
    StrategyHeadPrediction,
    StrategyRanking,
    resolve_strategy_head_decision,
)

OBSERVED_AT = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)


def _context() -> MarketContext:
    return MarketContext(
        observed_at=OBSERVED_AT,
        assets=("btc", "ETH"),
        features={"spot_return_1h": 0.02, "realized_vol_30d": 0.75},
        snapshot_id="snapshot-001",
        source="bybit",
    )


def _model_metadata() -> ModelMetadata:
    return ModelMetadata(
        model_name="strategy-head",
        model_version="2026-09-17.1",
        feature_set="market-context-v1",
        training_data_version="history-2026-09-16",
        trained_at=OBSERVED_AT,
        artifact_id="artifact-001",
        evaluation_metrics={"ndcg_at_3": 0.42},
    )


def test_market_context_is_typed_and_keeps_features_as_finite_inputs() -> None:
    context = _context()

    assert context.assets == ("BTC", "ETH")
    assert context.features["spot_return_1h"] == pytest.approx(0.02)
    with pytest.raises(TypeError):
        context.features["new_feature"] = 1.0  # type: ignore[index]


def test_manual_mode_selects_requested_strategies_without_model_scores() -> None:
    decision = resolve_strategy_head_decision(
        _context(),
        mode=SelectionMode.MANUAL,
        manual_strategies=("long_call", "long_put", "long_call"),
        automatic_prediction=StrategyHeadPrediction(
            action=DecisionAction.SELECT_STRATEGIES,
            ranked_strategies=(StrategyRanking("iron_condor", 1, 99.0),),
            selected_strategy_families=("iron_condor",),
            model_metadata=_model_metadata(),
        ),
    )

    assert decision.mode is SelectionMode.MANUAL
    assert decision.action is DecisionAction.SELECT_STRATEGIES
    assert decision.source is DecisionSource.MANUAL
    assert decision.selected_strategy_families == ("long_call", "long_put")
    assert [item.strategy_family for item in decision.ranked_strategies] == [
        "long_call",
        "long_put",
    ]
    assert all(item.ranking_score is None for item in decision.ranked_strategies)
    assert decision.reason_codes == (ReasonCode.MANUAL_SELECTION.value,)
    assert decision.model_metadata is None


def test_empty_manual_selection_is_explicit_no_trade() -> None:
    decision = resolve_strategy_head_decision(
        _context(),
        mode="manual",
        manual_strategies=(),
    )

    assert decision.action is DecisionAction.NO_TRADE
    assert decision.source is DecisionSource.MANUAL
    assert decision.selected_strategy_families == ()
    assert decision.reason_codes == (ReasonCode.MANUAL_NO_TRADE.value,)


def test_automatic_mode_accepts_lightgbm_ranking_scores_as_non_probabilities() -> None:
    prediction = StrategyHeadPrediction(
        action=DecisionAction.SELECT_STRATEGIES,
        ranked_strategies=(
            StrategyRanking("long_call", 1, 12.5),
            StrategyRanking("long_put", 2, -4.0),
        ),
        selected_strategy_families=("long_call",),
        reason_codes=("model_ranked",),
        model_metadata=_model_metadata(),
    )

    decision = resolve_strategy_head_decision(
        _context(),
        mode=SelectionMode.AUTOMATIC,
        automatic_prediction=prediction,
    )

    assert decision.source is DecisionSource.LIGHTGBM
    assert decision.action is DecisionAction.SELECT_STRATEGIES
    assert decision.selected_strategy_families == ("long_call",)
    assert decision.ranked_strategies[0].ranking_score == pytest.approx(12.5)
    assert decision.model_metadata == _model_metadata()
    assert decision.reason_codes == (
        "model_ranked",
        ReasonCode.LIGHTGBM_SELECTION.value,
    )


def test_automatic_no_trade_prediction_is_not_replaced_by_fallback() -> None:
    decision = resolve_strategy_head_decision(
        _context(),
        mode="automatic",
        automatic_prediction=StrategyHeadPrediction(
            action=DecisionAction.NO_TRADE,
            ranked_strategies=(StrategyRanking("long_call", 1, 0.1),),
            model_metadata=_model_metadata(),
        ),
        fallback_strategies=("long_put",),
    )

    assert decision.action is DecisionAction.NO_TRADE
    assert decision.source is DecisionSource.LIGHTGBM
    assert decision.reason_codes == (ReasonCode.LIGHTGBM_NO_TRADE.value,)


@pytest.mark.parametrize(
    ("prediction", "expected_reason"),
    [
        (None, ReasonCode.HEAD_UNAVAILABLE.value),
        (
            StrategyHeadPrediction(
                action=DecisionAction.SELECT_STRATEGIES,
                ranked_strategies=(StrategyRanking("long_call", 1, 2.0),),
                selected_strategy_families=("long_call",),
            ),
            ReasonCode.HEAD_UNAVAILABLE.value,
        ),
        (
            StrategyHeadPrediction(
                action=DecisionAction.SELECT_STRATEGIES,
                ranked_strategies=(StrategyRanking("long_call", 1, 2.0),),
                selected_strategy_families=("long_call",),
                model_metadata=ModelMetadata(
                    model_name="other-head",
                    model_version="1",
                    feature_set="market-context-v1",
                    framework="other-framework",
                ),
            ),
            ReasonCode.INVALID_MODEL_METADATA.value,
        ),
    ],
)
def test_automatic_mode_falls_back_when_head_is_unavailable(
    prediction: StrategyHeadPrediction | None,
    expected_reason: str,
) -> None:
    decision = resolve_strategy_head_decision(
        _context(),
        mode=SelectionMode.AUTOMATIC,
        automatic_prediction=prediction,
        fallback_strategies=("long_put",),
    )

    assert decision.source is DecisionSource.FALLBACK
    assert decision.action is DecisionAction.SELECT_STRATEGIES
    assert decision.selected_strategy_families == ("long_put",)
    assert decision.reason_codes[:2] == (
        expected_reason,
        ReasonCode.FALLBACK_USED.value,
    )


def test_automatic_mode_without_fallback_stops_at_no_trade() -> None:
    decision = resolve_strategy_head_decision(
        _context(),
        mode=SelectionMode.AUTOMATIC,
        automatic_prediction=None,
    )

    assert decision.action is DecisionAction.NO_TRADE
    assert decision.source is DecisionSource.FALLBACK
    assert decision.selected_strategy_families == ()
    assert decision.reason_codes == (
        ReasonCode.HEAD_UNAVAILABLE.value,
        ReasonCode.FALLBACK_USED.value,
        ReasonCode.NO_FALLBACK_STRATEGIES.value,
    )


def test_contract_rejects_inconsistent_no_trade_and_ranking_values() -> None:
    with pytest.raises(ValueError, match="NO_TRADE"):
        StrategyHeadPrediction(
            action=DecisionAction.NO_TRADE,
            ranked_strategies=(StrategyRanking("long_call", 1, 0.8),),
            selected_strategy_families=("long_call",),
        )

    with pytest.raises(ValueError, match="consecutive"):
        StrategyHeadPrediction(
            action=DecisionAction.SELECT_STRATEGIES,
            ranked_strategies=(StrategyRanking("long_call", 2, 0.8),),
            selected_strategy_families=("long_call",),
        )

    with pytest.raises(ValueError, match="finite"):
        StrategyRanking("long_call", 1, float("nan"))

    with pytest.raises(ValueError, match="LightGBM"):
        StrategyHeadDecision(
            market_context=_context(),
            mode=SelectionMode.AUTOMATIC,
            action=DecisionAction.SELECT_STRATEGIES,
            source=DecisionSource.LIGHTGBM,
            ranked_strategies=(StrategyRanking("long_call", 1, 1.0),),
            selected_strategy_families=("long_call",),
            model_metadata=ModelMetadata(
                model_name="other-head",
                model_version="1",
                feature_set="market-context-v1",
                framework="other-framework",
            ),
        )
