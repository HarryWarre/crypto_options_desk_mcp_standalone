# DESK-002 — Live Desk UI Bot Widgets & Control Panel

**Status:** in-progress  
**Branch:** `feat/desk-bot-ui-widgets`  
**Target:** `main`

## 1. Problem & Context
While the backend now has `BotManager` and `WS /api/v1/bot/stream`, users currently have no visual representation of the automated options bot on the web interface (`#live-desk`). 
Users need:
1. A real-time control bar to start/stop the bot, trigger a cycle manually, or emergency close positions.
2. An overview of the virtual account balance (Equity, Cash, Margin Utilization % with safety color coding).
3. A live display of the active Iron Condor's 4 legs with individual Greeks, entry prices, and mark prices.
4. A Take-Profit progress tracker showing how close the position is to the 50% TP threshold.
5. Instant updates via WebSocket without requiring page reload.

## 2. Component Design

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│ 🤖 AUTOMATED OPTIONS BOT (IRON CONDOR)           [RUNNING ●] [BTC-USDT]      │
│ [Bật/Tắt Bot]   [Quét ngay (Cycle)]   [Đóng hết (Close All)]   [Reset Ví]  │
├──────────────┬──────────────┬──────────────┬──────────────┬─────────────────┤
│ EQUITY       │ CASH BALANCE │ UNREALIZED   │ MARGIN USE   │ COMPOUNDED PNL  │
│ $10,216.54   │ $10,216.54   │ +$18.50      │ 4.2% [SAFE]  │ +$216.54        │
├──────────────┴──────────────┴──────────────┴──────────────┴─────────────────┤
│ ACTIVE IRON CONDOR: ic_btc_6283f8f4 (DTE: 8.5d)                             │
│ 🎯 Take Profit (50%): $46.14  |  Current: $18.50 (40.1%)  [=========>     ] │
│                                                                             │
│ Leg Role        Symbol                  Strike   Delta   Entry   Mark   PnL │
│ Long Put Wing   BTC-25SEP26-74000-P     74,000   -0.03   70.35   50.0  -$11 │
│ Short Put       BTC-25SEP26-77500-P     77,500   -0.15  303.48  230.0  +$40 │
│ Short Call      BTC-25SEP26-85000-C     85,000   +0.15  278.60  210.0  +$38 │
│ Long Call Wing  BTC-25SEP26-90000-C     90,000   +0.03   55.27   42.0   -$7 │
└─────────────────────────────────────────────────────────────────────────────┘
```

## 3. Acceptance Criteria
- [ ] Responsive bot panel added to `#live-desk-view` in `index.html`.
- [ ] CSS styling adhering to terminal theme with dark backgrounds, high-contrast badges, and clean typography in `styles.css`.
- [ ] WebSocket streaming client wired in `live-desk.js` connecting to `/api/v1/bot/stream`.
- [ ] Buttons for Start/Stop, Run Cycle, Close All, and Reset Account make API calls to `/api/v1/bot/control` and update UI immediately.
- [ ] Works seamlessly at mobile viewport width (390px) without overflow.
