# Valuation and signal-generator review

Date: 2026-09-17  
Scope: repository inspection plus primary/official sources. Findings were published in [GitHub issue #12](https://github.com/HarryWarre/crypto_options_desk_mcp_standalone/issues/12).

## Bottom line

The current scan does not actually measure historical strategy win rate. The canonical path computes a risk-neutral/lognormal **model estimate** of expiry P&L and explicitly labels it `model_estimate`, while opportunities remain `not_validated` / `insufficient_evidence`. See [`payoff_metrics.py`](../../src/options_lib/payoff_metrics.py#L33-L69) and [`opportunity_scanner.py`](../../src/options_lib/opportunity_scanner.py#L168-L182).

The main reason the displayed metrics feel unreasonable is semantic:

- Standard profit-loss ratio is `average win / abs(average loss)`. QuantConnect’s official glossary defines that ratio and expectancy as expected return per trade, with win/loss rates and average wins/losses. It also defines win rate after transaction fees. [QuantConnect glossary](https://www.quantconnect.com/docs/v2/writing-algorithms/key-concepts/glossary)
- The repository’s `risk_reward` is instead `expected positive P&L contribution / abs(expected negative P&L contribution)`. See [`payoff_metrics.py`](../../src/options_lib/payoff_metrics.py#L64-L69). A value of `1.0` means model EV is approximately zero under that distribution—not a conventional 1:1 average payoff ratio.
- With no zero-P&L ties, `E = pG - (1-p)L`, `R = G/L`, and therefore `p_break_even = 1/(1+R)`. Thus 33% wins with 1:1 payoff gives `E = -0.34L` and needs a 50% win rate to break even. At 33% wins, the payoff ratio must exceed about 2.03:1 before costs to break even. These figures are algebraic derivations of the cited definitions.

## Findings in the repository

### 1. Model probability is being read as “win rate”

The canonical payoff calculation defines a win as expiry P&L strictly greater than zero, using a risk-neutral distribution, executable-side quote assumptions, and opening fees/slippage. It does not use realized trades. See [`payoff_metrics.py`](../../src/options_lib/payoff_metrics.py#L33-L69) and [`payoff_metrics.py`](../../src/options_lib/payoff_metrics.py#L186-L212).

Risk-neutral valuation is appropriate for pricing/market-implied quantities, but it is not automatically a real-world outcome forecast. MathWorks’ technical documentation describes risk-neutral option simulation as the average of **discounted** terminal payoffs: [Simulating Equity Prices](https://www.mathworks.com/help/finance/example-simulating-equity-prices.html). BIS research distinguishes option-implied risk-neutral distributions from physical/realized distributions: [How useful are implied distributions?](https://www.bis.org/publ/bisp06e.pdf). CME likewise describes delta as only an approximate, market-implied probability of finishing in the money—not the probability that a multi-leg strategy finishes with positive net P&L: [Using Options Prices to Assess Oil Market Opportunities](https://www.cmegroup.com/articles/whitepapers/using-options-prices-to-assess-oil-market-opportunities.html).

Implication: rename/display the field as `model_win_probability`, include distribution/IV/rate/timestamp/cost assumptions, and reserve `historical_win_rate` and `validated_expectancy` for chronological realized-trade validation.

### 2. The EV units may be inconsistent with fair-value edge

[`fair_value.py`](../../src/options_lib/pricing/fair_value.py#L247-L324) discounts Black-Scholes/Black-76 fair value to the present. [`payoff_metrics.py`](../../src/options_lib/payoff_metrics.py#L417-L503) integrates expiry P&L under the lognormal distribution without an explicit `exp(-rT)` factor. At zero rates this is invisible; otherwise `expected_value` may be expiry-dollar EV while `edge_after_costs` is current-dollar fair-value edge.

Implication: either discount terminal P&L consistently, or expose both `expected_expiry_pnl` and `expected_present_value_pnl`; add a parity test for their relationship. Do not rank candidates using quantities with different time units.

### 3. Legacy signals are heuristics, not expectancy signals

The legacy covered-call path triggers from IV-RV thresholds and additional regime, term-structure, skew, and delta gates, but does not calculate strategy payoff, break-even win rate, average win/loss, cost-adjusted EV, or held-out performance. See [`covered_call.py`](../../src/options_lib/strategy/covered_call.py#L300-L424) and [`orchestrator.py`](../../src/mcp_trading/orchestrator.py#L505-L608).

There is a concrete lookback defect: `get_covered_call_signal` fetches 30 days of 4-hour candles but does not pass `rv_window`, leaving the analyzer default at 30 bars (about 5 days). `get_iv_rv_spread` explicitly scales the requested window by six. The two user-facing paths can therefore calculate different RV for the same apparent horizon. See [`orchestrator.py`](../../src/mcp_trading/orchestrator.py#L564-L608) and [`covered_call.py`](../../src/options_lib/strategy/covered_call.py#L105-L205).

The legacy analyzer also uses distance-based arbitrary probabilities for straddles/strangles, approximates spread probability with the long-leg delta, and uses mark prices without fees/slippage. See [`analyzer.py`](../../src/options_lib/strategy/analyzer.py#L187-L255), [`analyzer.py`](../../src/options_lib/strategy/analyzer.py#L321-L412), [`analyzer.py`](../../src/options_lib/strategy/analyzer.py#L509-L586), and [`classifier.py`](../../src/options_lib/strategy/classifier.py#L388-L517).

For the strangle specifically, the official Options Industry Council describes losses in the middle and profits beyond either break-even. That conflicts with the legacy analyzer’s stored between-break-even “profit range.” [OIC long strangle](https://www.optionseducation.org/strategies/all-strategies/long-strangle-long-combination)

Implication: route legacy MCP tools through one payoff/cost schema, or label their output explicitly as heuristic/unvalidated and prevent `go` from being interpreted as positive-EV approval.

### 4. Costs and liquidity are optimistic by default

The API defaults to a 5% risk-free rate and zero fees/slippage unless overridden. See [`api.py`](../../src/options_app/api.py#L103-L104) and [`api.py`](../../src/options_app/api.py#L151-L197). These are assumptions, not evidence that the live account or instrument has those economics.

Bybit’s official options fee page uses the applicable maker/taker rate plus an option-price cap and documents delivery fees for exercised options; this is not equivalent to a flat generic fee per contract. [Bybit options fees](https://www.bybit.com/en/help-center/article?id=000001544&language=en_US)

Bybit’s options ticker schema provides separate bid/ask prices, bid/ask sizes, IVs, mark price, index price, open interest, and volume. [Bybit V5 tickers](https://bybit-exchange.github.io/docs/v5/market/tickers) Its slippage documentation states that execution depends on order size and order-book depth. [Bybit market-order slippage tolerance](https://www.bybit.com/en/help-center/article/Market-Order-with-Slippage-Tolerance)

Implication: use an account/instrument-specific fee profile, delivery treatment, side-specific bid/ask and size, quote timestamp, and adverse-fill sensitivity. A single `slippage_bps` value should be treated as a stress scenario, not a fill guarantee.

### 5. Validation must control selection bias

The repository has a chronological train/holdout validator with fee/slippage and cost sensitivity. The snapshot backtest replays scanner candidates and calls that validator, but live scan results remain model estimates and require a configured historical archive before they become realized evidence. See [`ev_validation.py`](../../src/options_lib/ev_validation.py#L100-L148), [`backtest_engine.py`](../../src/options_lib/backtest_engine.py#L192-L294), and [valuation remediation QA](../valuation-remediation-qa.md#ev-evidence--not-ready-for-a-positive-ev-claim).

When many strategies, thresholds, strikes, or lookbacks are tried on the same history, the selected result is exposed to backtest overfitting. Bailey, Borwein, López de Prado, and Zhu’s primary paper proposes a combinatorial-symmetry approach for estimating the probability of backtest overfitting: [The Probability of Backtest Overfitting](https://papers.ssrn.com/sol3/Papers.cfm?abstract_id=2326253)

Implication: require untouched holdout data, record the number of variants tried, and report sample size, cost sensitivity, and uncertainty before displaying “validated positive EV.”

## Issue-ready acceptance criteria

- [ ] Separate `model_win_probability` from `historical_win_rate`; separate standard `profit_loss_ratio` from the current weighted contribution ratio.
- [ ] Add `average_win`, `average_loss`, `break_even_win_rate`, and present-value `expected_value` to the canonical strategy output.
- [ ] Add regression tests for 33%/1:1 (`-0.34R`, 50% break-even), approximately 33%/2.03:1 break-even before costs, ties, and cost changes.
- [ ] Fix or explicitly document the expiry-dollar versus present-dollar EV calculation.
- [ ] Make the RV lookback explicit end-to-end and test the current 30-day/30-bar mismatch.
- [ ] Replace legacy arbitrary probabilities with full strategy payoff integration using net premium and all legs; never use one leg’s delta as a multi-leg profit probability.
- [ ] Apply exchange-specific fees/delivery costs and bid/ask/size-aware fill assumptions; run adverse cost scenarios.
- [ ] Keep signals `NO_TRADE`/unvalidated when no candidate survives model, cost, liquidity, and out-of-sample evidence gates.

Recommended order: normalize metric semantics → correct discounting → unify probability/cost inputs → retire or wrap legacy signals → run chronological holdout validation.
