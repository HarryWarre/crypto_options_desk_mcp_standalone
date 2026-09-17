import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from options_lib.strategy_head_provenance import (
    PROVENANCE_KEY,
    SIGNAL_DISCLAIMER,
    DecisionAction,
    DecisionSource,
    SignalProvenance,
    StrategyRanking,
    attach_provenance,
    get_signal_provenance,
)

AS_OF = datetime(2026, 9, 17, 9, 30, tzinfo=UTC)


def test_manual_provenance_is_typed_and_json_safe() -> None:
    provenance = SignalProvenance.manual(
        selected_strategies=("LONG_CALL", "long_put"),
        as_of=AS_OF,
        reason_codes=("manual_selection", "user_preference"),
    )

    payload = provenance.to_dict()

    assert provenance.source is DecisionSource.MANUAL
    assert provenance.action is DecisionAction.SELECT_STRATEGIES
    assert provenance.selected_strategy_families == ("long_call", "long_put")
    assert provenance.ranked_strategies == ()
    assert payload["as_of"] == "2026-09-17T09:30:00Z"
    assert payload["execution_status"] == "not_executed"
    assert payload["profit_guarantee"] is False
    assert payload["disclaimer"] == SIGNAL_DISCLAIMER
    json.dumps(payload, allow_nan=False)


def test_lightgbm_provenance_keeps_model_evidence_and_round_trips() -> None:
    provenance = SignalProvenance.lightgbm(
        selected_strategies=("bull_call_vertical",),
        as_of=AS_OF,
        model_version="strategy-head-2026-09-17",
        ranked_strategies=(
            StrategyRanking("bull_call_vertical", 1, 0.82),
            StrategyRanking("long_call", 2, 0.63),
        ),
        reason_codes=("head_selected_strategy", "above_threshold"),
    )

    restored = SignalProvenance.from_json(provenance.to_json())

    assert restored == provenance
    assert restored.source.value == "lightgbm"
    assert restored.model_version == "strategy-head-2026-09-17"
    assert restored.ranked_strategies[0].to_dict() == {
        "strategy_family": "bull_call_vertical",
        "rank": 1,
        "ranking_score": 0.82,
    }


def test_fallback_provenance_is_explicit_and_has_no_model_claim() -> None:
    provenance = SignalProvenance.fallback(
        selected_strategies="long_call",
        as_of=AS_OF,
        reason_codes="model_unavailable",
    )

    assert provenance.source is DecisionSource.FALLBACK
    assert provenance.action is DecisionAction.SELECT_STRATEGIES
    assert provenance.selected_strategy_families == ("long_call",)
    assert provenance.reason_codes == ("model_unavailable",)
    assert provenance.model_version is None


def test_no_trade_has_no_selected_strategy_and_can_keep_model_context() -> None:
    provenance = SignalProvenance.no_trade(
        as_of=AS_OF,
        source=DecisionSource.LIGHTGBM,
        model_version="strategy-head-2026-09-17",
        ranked_strategies=(StrategyRanking("long_call", 4, 0.21),),
        reason_codes=("below_threshold", "no_trade"),
    )

    assert provenance.is_no_trade
    assert provenance.selected_strategy_families == ()
    assert provenance.to_dict()["action"] == "no_trade"
    assert provenance.ranked_strategies[0].ranking_score == pytest.approx(0.21)
    assert provenance.ranked_strategies[0].rank == 4


def test_legacy_signal_without_provenance_returns_none() -> None:
    assert get_signal_provenance({"symbol": "BTC-17SEP26-60000-C"}) is None
    assert get_signal_provenance(None) is None


def test_attach_provenance_copies_signal_and_can_be_read_back() -> None:
    legacy_signal = {"symbol": "BTC-17SEP26-60000-C", "edge": 0.12}
    provenance = SignalProvenance.manual(selected_strategies="long_call", as_of=AS_OF)

    enriched = attach_provenance(legacy_signal, provenance)

    assert legacy_signal == {"symbol": "BTC-17SEP26-60000-C", "edge": 0.12}
    assert enriched[PROVENANCE_KEY] == provenance.to_dict()
    assert get_signal_provenance(enriched) == provenance


def test_from_head_decision_maps_contract_fields_without_importing_contract() -> None:
    decision = SimpleNamespace(
        source="lightgbm",
        action="select_strategies",
        selected_strategy_families=("long_call",),
        market_context=SimpleNamespace(observed_at=AS_OF),
        reason_codes=("lightgbm_selection",),
        ranked_strategies=(
            SimpleNamespace(strategy_family="long_call", rank=1, ranking_score=0.82),
        ),
        model_metadata=SimpleNamespace(model_version="strategy-head-2026-09-17"),
    )

    provenance = SignalProvenance.from_head_decision(decision)

    assert provenance.source is DecisionSource.LIGHTGBM
    assert provenance.action is DecisionAction.SELECT_STRATEGIES
    assert provenance.as_of == AS_OF
    assert provenance.model_version == "strategy-head-2026-09-17"
    assert provenance.ranked_strategies == (StrategyRanking("long_call", 1, 0.82),)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    (
        (
            {
                "source": "manual",
                "action": "select_strategies",
                "selected_strategy_families": (),
                "as_of": AS_OF,
                "reason_codes": ("manual_selection",),
            },
            "selected_strategy_families",
        ),
        (
            {
                "source": "lightgbm",
                "action": "no_trade",
                "selected_strategy_families": ("long_call",),
                "as_of": AS_OF,
                "reason_codes": ("below_threshold",),
            },
            "NO_TRADE",
        ),
    ),
)
def test_provenance_rejects_inconsistent_or_non_finite_metadata(
    kwargs: dict[str, object], message: str
) -> None:
    with pytest.raises((TypeError, ValueError), match=message):
        SignalProvenance(**kwargs)


def test_ranking_rejects_non_finite_model_score() -> None:
    with pytest.raises(ValueError, match="ranking_score"):
        StrategyRanking("long_call", 1, float("nan"))
