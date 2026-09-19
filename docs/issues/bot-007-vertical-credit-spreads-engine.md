# BOT-007: Directional Vertical Credit Spreads Bot (Bull Put & Bear Call)

**Status:** completed  
**Branch:** `feat/bot-007-vertical-credit-spreads-engine`  
**Target:** `main`  
**Blueprint Reference:** [iron_condor_bot.py](file:///Users/hoangviet/Flowsurface/crypto_options_desk_mcp/src/options_lib/strategy/iron_condor_bot.py), [iron_condor_backtest.py](file:///Users/hoangviet/Flowsurface/crypto_options_desk_mcp/src/options_lib/strategy/iron_condor_backtest.py)

---

## 1. Problem & Context
Trong khi Iron Condor là chiến lược trung tính 4 chân (Delta-Neutral), thị trường tiền mã hóa thường xuyên xuất hiện các đợt sóng xu hướng mạnh mẽ (Trends) hoặc các giai đoạn tích lũy có thiên hướng (Bullish/Bearish bias). 

Vertical Credit Spreads (2 chân xác định rủi ro) cho phép bot thu hoạch phí bảo hiểm theo xu hướng mà không bị rủi ro vỡ nợ một đầu như Iron Condor:
1. **Bull Put Spread (Bán Put trên, Mua Put bảo vệ dưới):** Thu credit ròng trong xu hướng tăng hoặc sideway tăng; lợi nhuận tối đa khi giá đóng trên short put strike.
2. **Bear Call Spread (Bán Call dưới, Mua Call bảo vệ trên):** Thu credit ròng trong xu hướng giảm hoặc sideway giảm; lợi nhuận tối đa khi giá đóng dưới short call strike.

Chiến lược 2 chân giúp:
- Giảm 50% chi phí trượt giá (slippage) và phí giao dịch (trading fees) so với 4 chân của Iron Condor.
- Bắt trọn xu hướng động lượng có kiểm soát mức thua lỗ tối đa cố định ($\text{Max Loss} = \text{Spread Width} - \text{Net Credit}$).

---

## 2. Target Strategy Specs (Vertical Credit Spreads)

- **Tài sản hỗ trợ:** BTC, ETH, SOL, DOGE, MNT, XRP
- **Chế độ giao dịch:** Paper Trading (`PaperBroker`) và Bybit V5 Live
- **Tenor:** 5 – 20 DTE (Hợp đồng tuần để tận dụng gia tốc phân rã Theta)
- **Cấu hình Bull Put Spread:**
  - Điều kiện kích hoạt: Giá nằm trên đường xu hướng trung bình động (EMA lookback).
  - Short Put Delta: $-0.15$ đến $-0.22$
  - Long Put Wing Delta: $-0.03$ đến $-0.08$
- **Cấu hình Bear Call Spread:**
  - Điều kiện kích hoạt: Giá nằm dưới đường xu hướng trung bình động.
  - Short Call Delta: $+0.15$ đến $+0.22$
  - Long Call Wing Delta: $+0.03$ đến $+0.08$
- **Quy tắc Lifecycle:**
  - **Take Profit (TP):** Đóng toàn bộ 2 chân khi thu được $\ge 50\%$ net credit.
  - **Stop Loss (SL):** Cắt lỗ khẩn cấp khi mức lỗ đạt $\ge 1.8\text{x}$ net credit.
  - **Expiry Roll:** Đóng hoặc chuyển kỳ hạn khi DTE $\le 1.0$ ngày.

---

## 3. Sub-tasks / Child Issues

- [x] **BOT-007A: Trend & Volatility Regime Filter**
  - Tích hợp bộ lọc kỹ thuật định hướng: Rolling price momentum xác định xu hướng tăng (Bullish) hoặc giảm (Bearish).
  - Tự động kích hoạt mở Bull Put Spread khi xu hướng tăng và Bear Call Spread khi xu hướng giảm.

- [x] **BOT-007B: Dynamic 2-Leg Strike & Width Selector**
  - Sử dụng cấu hình 2 chân chuẩn xác định rủi ro: Short strike delta ~0.18, Long wing delta ~0.05.
  - Quét chuỗi hợp đồng tuần tối ưu bề rộng spread và tỷ lệ Reward/Risk.

- [x] **BOT-007C: Wing-First Execution Protocol**
  - Mua chân bảo hiểm (Long Wing) trước để khóa biên độ ký quỹ tối đa, sau đó mới bán Short Leg.

- [x] **BOT-007D: Real-time Lifecycle & Defense Manager**
  - Giám sát spread mark price liên tục.
  - Thực thi tự động 50% TP, 1.8x SL và xử lý đáo hạn khi DTE <= 1.

- [x] **BOT-007E: Parquet Backtesting Engine & Multi-Asset Replay**
  - Xây dựng `VerticalSpreadBacktestEngine` trong `src/options_lib/strategy/vertical_spread_backtest.py`.
  - Replay qua 75 ngày dữ liệu Parquet trên 6 tài sản (BTC, ETH, SOL, DOGE, MNT, XRP).
  - Kết quả đạt **1,273 trades**, Win Rate **98.8%**, Net PnL **+$21,089.04**, Profit Factor **65.49**.

- [x] **BOT-007F: Unit Test Suite**
  - Tạo `tests/test_vertical_spread_bot.py` và `tests/test_vertical_spread_backtest.py`.
  - Pass 100% các unit test (5/5 tests mới pass hoàn toàn).

---

## 4. Acceptance Criteria
1. Module bot `vertical_spread_bot.py` và backtester `vertical_spread_backtest.py` hoàn thiện chuẩn mực.
2. Số lượng lệnh backtest đạt yêu cầu: 1,273 lệnh (vượt mốc 100 lệnh).
3. Tỷ lệ thắng 98.8% và PnL dương +$21,089.04.
4. Toàn bộ unit test mới đạt tỷ lệ pass 100%.

