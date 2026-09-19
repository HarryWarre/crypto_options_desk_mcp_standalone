# BOT-008: Dynamic Iron Butterfly Strategy Bot (ATM Pinning & High Credit)

**Status:** completed  
**Branch:** `feat/bot-008-iron-butterfly-strategy-engine`  
**Target:** `main`  
**Blueprint Reference:** [iron_condor_bot.py](file:///Users/hoangviet/Flowsurface/crypto_options_desk_mcp/src/options_lib/strategy/iron_condor_bot.py), [iron_condor_backtest.py](file:///Users/hoangviet/Flowsurface/crypto_options_desk_mcp/src/options_lib/strategy/iron_condor_backtest.py)

---

## 1. Problem & Context
So với Iron Condor (bán 2 chân OTM cách xa giá hiện tại), chiến lược **Iron Butterfly**:
- Bán cùng một Strike tại ATM (Sell ATM Call + Sell ATM Put - tức bán ATM Straddle).
- Mua 2 chân bảo vệ ở 2 cánh xa (Buy OTM Put Wing + Buy OTM Call Wing).

**Ưu điểm vượt trội của Iron Butterfly:**
1. **Phí bảo hiểm cực cao (Maximum Premium / Net Credit):** Bán tại ATM đem lại mức credit chiếm tới $40\% – $60\%$ độ rộng của cánh (so với chỉ $10\% – $18\%$ ở Iron Condor).
2. **Tốc độ phân rã thời gian (Theta Decay) dốc nhất tại ATM:** Vị thế đạt trạng thái sinh lời cực nhanh nếu giá chỉ đi ngang trong 2–4 ngày đầu.
3. **Hiệu ứng Max Pain Pinning:** Vào các ngày đáo hạn lớn (thứ Sáu hàng tuần), giá tiền mã hóa thường có xu hướng bị kéo về vùng tập trung Open Interest cao nhất (ATM Pinning).

---

## 2. Target Strategy Specs (Iron Butterfly)

- **Tài sản hỗ trợ:** BTC, ETH, SOL, DOGE, MNT, XRP
- **Chế độ giao dịch:** Paper Trading (`PaperBroker`) và Bybit V5 Live
- **Tenor:** 3 – 16 DTE (Kỳ hạn ngắn để tối đa hóa đỉnh phân rã Theta)
- **Cấu trúc 4 chân:**
  - Short Call: Delta $\approx +0.50$ (Strike gần giá Spot nhất)
  - Short Put: Delta $\approx -0.50$ (Cùng Strike với Short Call)
  - Long Call Wing: Delta $\approx +0.08$
  - Long Put Wing: Delta $\approx -0.08$
- **Quy tắc Lifecycle & Vòng đời:**
  - **Aggressive Take Profit (TP):** Đóng toàn bộ 4 chân khi Unrealized PnL đạt **30% của Net Credit** ban đầu.
  - **Tight Stop Loss (SL):** Cắt lỗ dứt khoát nếu vị thế âm vượt quá **1.0x Net Credit**.
  - **DTE Time-Stop:** Đóng vị thế khi DTE $\le 1.0$ ngày.

---

## 3. Sub-tasks / Child Issues

- [x] **BOT-008A: Low-Volatility, Squeeze & Pinning Screener**
  - Tích hợp phát hiện nén biên độ và tìm Strike ATM tối ưu gần giá Spot nhất.

- [x] **BOT-008B: ATM Strike Centering & Dynamic Wing Width Optimizer**
  - Đồng bộ hóa cùng một Strike ATM cho cả Short Call và Short Put.
  - Tự động chọn 2 cánh bảo vệ Long Call Wing và Long Put Wing.

- [x] **BOT-008C: 4-Leg Synchronized Execution Engine**
  - Mua 2 chân bảo vệ trước để cố định mức ký quỹ tối đa, bán 2 chân ATM straddle sau.

- [x] **BOT-008D: High-Velocity Lifecycle Manager**
  - Thực thi quy tắc 30% early TP và 1.0x SL.

- [x] **BOT-008E: Parquet Backtest Replay Engine**
  - Xây dựng `IronButterflyBacktestEngine` trong `src/options_lib/strategy/iron_butterfly_backtest.py`.
  - Replay qua 75 ngày dữ liệu Parquet trên 6 tài sản (BTC, ETH, SOL, DOGE, MNT, XRP).
  - Kết quả đạt **940 trades**, Win Rate **97.8%**, Net PnL **+$102,439.57**, Profit Factor **46.67**.

- [x] **BOT-008F: Unit Tests & Reporting Dashboard**
  - Tạo `tests/test_iron_butterfly_bot.py` và `tests/test_iron_butterfly_backtest.py`.
  - Pass 100% các unit test (4/4 tests mới pass hoàn toàn).

---

## 4. Acceptance Criteria
1. Module bot `iron_butterfly_bot.py` và backtester `iron_butterfly_backtest.py` hoàn thành chuẩn mực.
2. Số lượng lệnh backtest đạt yêu cầu: 940 lệnh (vượt xa mốc 100 lệnh).
3. Tỷ lệ thắng 97.8% và PnL dương +$102,439.57.
4. Toàn bộ unit test mới đạt tỷ lệ pass 100%.

