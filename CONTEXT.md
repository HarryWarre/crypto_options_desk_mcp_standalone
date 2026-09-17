# Domain context

## Opportunity decision metrics

- **Fair-value edge** is the model fair-value difference from the executable
  entry after stated costs. It is a quote-relative pricing signal, not an
  expected return or win probability.
- **Expected value (EV)** is the average expiry P&L under the explicitly named
  model distribution and execution assumptions. When no historical outcome
  sample is supplied, it is a model estimate and is not validated evidence.
- **Win probability** is the model probability that expiry P&L is strictly
  positive under the same distribution used for EV. It is not a historical
  win rate unless a held-out outcome sample is provided.
- **Reward/risk (RR)** is the expected positive payoff divided by the absolute
  expected negative payoff under the same model distribution. Maximum profit
  and maximum loss remain separate bounded-payoff fields.
- **Payoff curve** is the expiry P&L as a function of underlying price for the
  complete option-builder leg set, including entry costs. It is a piecewise
  option payoff curve, not a forecast path through time.

## Evidence states

Decision metrics must expose whether they are model-estimated, historically
validated, or unavailable because required inputs are missing. A positive
model estimate must not be described as a guarantee or as historical evidence.

## Position monitoring language

**Manual execution**:
An order created and managed by the user outside this application. The
exchange position and fills, not a local signal or an order acknowledgement,
are the source of truth for what was actually opened.
_Avoid_: simulated execution, assumed fill

**Position**:
An open exposure reported by the exchange after one or more fills, identified
by its symbol, category, direction, quantity, entry, mark, and risk fields.
_Avoid_: order, signal

**Exit policy**:
A pre-declared set of loss, profit, time, liquidation-buffer, and thesis rules
against which one position is evaluated. It is input to a decision, not a
prediction of future price.
_Avoid_: guarantee, stop promise

**Exit decision**:
A deterministic, timestamped recommendation to `CLOSE`, `HOLD`, or `REVIEW`
one observed position. It is never an exchange command.
_Avoid_: automated trade, order instruction

**HOLD**:
A conditional result meaning the configured policy has no triggered rule and
the required observations are usable; it does not mean the position is safe or
expected to profit.
_Avoid_: keep forever, safe trade

**REVIEW**:
A fail-safe result used when a policy, source observation, or reconciliation
fact is missing or inconsistent. It must not be silently downgraded to HOLD.
_Avoid_: neutral, no action

**Manual close instruction**:
A human-reviewable description of the opposite side and current broker
quantity to use if a CLOSE decision is accepted. The application does not
submit it in the read-only monitoring phase.
_Avoid_: close order, executed close
