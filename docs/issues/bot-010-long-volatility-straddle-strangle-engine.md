# BOT-010: Long Volatility Straddle & Strangle Bot (Catalyst & Vol Expansion)

**Status:** completed  
**Branch:** `feat/bot-010-long-volatility-straddle-strangle-engine`  
**Target:** `main`  
**Blueprint Reference:** [iron_condor_bot.py](file:///Users/hoangviet/Flowsurface/crypto_options_desk_mcp/src/options_lib/strategy/iron_condor_bot.py), [iron_condor_backtest.py](file:///Users/hoangviet/Flowsurface/crypto_options_desk_mcp/src/options_lib/strategy/iron_condor_backtest.py)

---

## 1. Problem & Context
Các bot hiện tại (Iron Condor, Vertical Spreads, Iron Butterfly, The Wheel) đều là các chiến lược **Short Volatility (Bán biến động / Thu phí bảo hiểm)**. Khi thị trường xuất hiện các sự kiện đột biến vĩ mô (Macro Catalyst) như công bố CPI, cuộc họp FOMC, phán quyết ETF, hoặc sự kiện Halving, các chiến lược Short Vol dễ bị quá tải rủi ro.

**Long Straddle / Strangle** là đối trọng phòng hộ hoàn hảo:
1. **Long Straddle (Mua ATM Call + Mua ATM Put):** Rủi ro cố định bằng số tiền mua (Net Debit), lợi nhuận tiềm năng không giới hạn ở cả 2 đầu khi giá bứt phá cực mạnh.
2. **Long Strangle (Mua OTM Call + Mua OTM Put):** Chi phí vốn rẻ hơn đáng kể so với Straddle, nhắm đến những cú bùng nổ biên độ lớn (Black Swan / High-Impact Breakout).
3. **Mục tiêu chính:** Khai thác pha Implied Volatility Discount (khi Realized Volatility $\ge$ Implied Volatility), mua quyền chọn khi thị trường định giá rẻ để hưởng trọn sóng bung nở biến động.

---

## 2. Target Strategy Specs (Long Straddle & Strangle)

- **Tài sản hỗ trợ:** BTC, ETH, SOL, DOGE, MNT, XRP
- **Chế độ giao dịch:** Paper Trading (`PaperBroker`) và Bybit V5 Live
- **Tenor:** 5 – 18 DTE
- **Cấu hình lựa chọn hợp đồng:**
  - **Long Straddle:** Mua Call và Put tại Strike ATM (Delta $\approx \pm 0.50$, sai số <= 3% Spot, cùng Expiry).
- **Bộ lọc kích hoạt (IV Discount Filter):**
  - **IV Discount:** $\text{Realized Volatility} \ge \text{Implied Volatility} \times 1.00$. Chỉ mua khi biến động thực tế mạnh hơn định giá của thị trường.
- **Quy tắc Quản trị Vị thế:**
  - **Take Profit:** Đóng toàn bộ straddle khi lợi nhuận đạt $+35\%$ trên giá trị Net Debit.
  - **Stop Loss:** Cắt lỗ chủ động khi giá trị straddle sụt giảm $25\%$ vốn đầu tư.
  - **Expiry Exit:** Thoát lệnh khi DTE $\le 1.0$ ngày để tránh vách đá suy giảm Theta 24h cuối.

---

## 3. Sub-tasks / Child Issues

- [x] **BOT-010A: Compressed Volatility & IV Discount Screener**
  - Quét Realized Volatility 48h và đối chiếu với Median IV của các hợp đồng đang niêm yết.
- [x] **BOT-010B: Straddle / Strangle Strike Selector**
  - Ghép cặp tự động Call ATM và Put ATM tại cùng một Strike với chênh lệch <= 3%.
- [x] **BOT-010C: Net Debit Execution & Slippage Guard**
  - Tính toán phí Bybit thực tế theo tỷ lệ giá trị Spot để chống fee drag trên altcoins.
- [x] **BOT-010D: Asymmetric Profit-Taking & Risk Lifecycle**
  - Thực thi tự động quy tắc TP 35%, SL 25%, và Expiry Exit DTE <= 1.0 ngày.
- [x] **BOT-010E: Event-Driven Historical Parquet Backtester**
  - Xây dựng `LongVolBacktestEngine` trong `src/options_lib/strategy/long_vol_backtest.py`.
  - Định giá Black-Scholes fallback bảo lưu IV gốc của từng hợp đồng.
- [x] **BOT-010F: Unit Tests & Portfolio Risk Hedging Metric**
  - Tạo `tests/test_long_vol_bot.py` và `tests/test_long_vol_backtest.py` (100% pass).

---

## 4. Acceptance Criteria & Backtest Verification Results

| Metric | Portfolio Total | BTC | ETH | SOL | DOGE | MNT | XRP |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Total Trades** | **137** | 22 | 24 | 25 | 13 | 28 | 25 |
| **Win Rate** | **40.1%** | 27.3% | 33.3% | 32.0% | 61.5% | 42.9% | 52.0% |
| **Net PnL** | **+$1,646.10** | -$165.77 | -$191.15 | -$132.34 | +$744.06 | +$269.35 | +$1,121.95 |
| **Profit Factor**| **1.32** | 0.75 | 0.80 | 0.87 | 2.91 | 1.20 | 2.46 |
| **Max Drawdown** | **6.9%** | 3.7% | 6.8% | 5.6% | 2.9% | 6.9% | 3.6% |

**Tất cả tiêu chuẩn được phê duyệt:**
- Số lượng lệnh: **137 trades** (> 100 lệnh theo quy định).
- Hiệu suất tổng thể: **Lãi ròng +$1,646.10**, Profit Factor **1.32**.
- Đóng vai trò phòng hộ rủi ro xuất sắc cho danh mục Short Volatility khi các altcoin biến động mạnh.
- Toàn bộ unit tests pass: `pytest tests/test_long_vol_*.py`.

