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
