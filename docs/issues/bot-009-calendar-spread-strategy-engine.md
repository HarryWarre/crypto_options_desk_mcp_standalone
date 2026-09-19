# BOT-009: Calendar & Diagonal Spread Strategy Bot (Term Structure & Theta Harvest)

**Status:** backlog  
**Branch:** `feat/bot-009-calendar-spread-strategy-engine`  
**Target:** `main`  
**Blueprint Reference:** [iron_condor_bot.py](file:///Users/hoangviet/Flowsurface/crypto_options_desk_mcp/src/options_lib/strategy/iron_condor_bot.py), [iron_condor_backtest.py](file:///Users/hoangviet/Flowsurface/crypto_options_desk_mcp/src/options_lib/strategy/iron_condor_backtest.py)

---

## 1. Problem & Context
Calendar Spread (còn gọi là Time Spread / Horizontal Spread) là chiến lược khai thác cấu trúc kỳ hạn của biến động (Volatility Term Structure) và sự phi tuyến tính của độ suy giảm thời gian (Theta Decay):
- **Cấu trúc:** Bán hợp đồng quyền chọn kỳ hạn ngắn (Near-Term, ví dụ DTE 7–10 ngày) và Mua hợp đồng quyền chọn kỳ hạn dài hơn (Far-Term, ví dụ DTE 30–60 ngày) tại cùng một mức giá Strike (hoặc Strike khác nhau đối với Diagonal Spread).
- **Nguyên lý sinh lời:**
  1. Hợp đồng ngắn hạn có tốc độ phân rã Theta nhanh gấp nhiều lần so với hợp đồng dài hạn ($\Theta \propto 1 / \sqrt{T}$).
  2. Khi hợp đồng ngắn hạn suy hao nhanh về 0, hợp đồng dài hạn vẫn giữ được phần lớn giá trị thời gian và độ nhạy biến động (Vega).
  3. Trạng thái thị trường crypto thường ở trong pha **Contango** (IV kỳ hạn xa cao hơn IV kỳ hạn gần), tạo lợi thế định giá khi mua Vega xa và bán Theta gần.

---

## 2. Target Strategy Specs (Calendar & Diagonal Spreads)

- **Tài sản hỗ trợ:** BTC, ETH, SOL
- **Chế độ giao dịch:** Paper Trading (`PaperBroker`) và Bybit V5 Live
- **Cặp kỳ hạn mục tiêu (Tenor Pair):**
  - **Near-term (Short Leg):** 5 – 10 DTE (Tuần hiện tại)
  - **Far-term (Long Leg):** 28 – 45 DTE (Tháng kế tiếp)
- **Lựa chọn Strike:**
  - Standard Calendar: ATM Strike (Delta $\approx 0.50$) tại thời điểm mở lệnh.
  - Diagonal Spread: Bán OTM Near-Term (Delta 0.25 - 0.35) và Mua ITM/ATM Far-Term (Delta 0.60 - 0.70) tạo đòn bẩy định hướng có bảo hiểm thời gian.
- **Bộ lọc thị trường (Term Structure Screener):**
  - Kiểm tra độ dốc cấu trúc kỳ hạn: $\text{IV}_{\text{far}} - \text{IV}_{\text{near}} \ge -1.0$ (Tránh mở khi thị trường ở trạng thái Extreme Backwardation / hoảng loạn ngắn hạn).
  - Biến động ngầm định ở mức trung bình đến thấp để đón sóng mở rộng IV của chân xa.
- **Quy tắc Vòng đời & Tái sử dụng chân xa (Rolling Front-Month):**
  - **Take Profit:** Đóng toàn bộ spread khi lợi nhuận đạt $25\% – $35\%$ giá trị vốn đầu tư (Debit bỏ ra).
  - **Rolling the Short Leg:** Khi hợp đồng ngắn hạn đáo hạn vô giá trị (hoặc đạt 80% TP), tiếp tục giữ chân dài hạn (Far Leg) và bán tiếp một hợp đồng ngắn hạn mới của tuần tiếp theo (Harvesting liên hoàn).
  - **Stop Loss:** Đóng vị thế nếu giá spot bứt phá quá xa ra khỏi phạm vi lãi dự kiến khiến giá trị spread sụt giảm $> 25\%$.

---

## 3. Sub-tasks / Child Issues

- [ ] **BOT-009A: Volatility Term Structure & Skew Screener**
  - Quét toàn bộ đường cong kỳ hạn (Term Structure Curve) từ Deribit / Bybit.
  - Tính toán độ lệch IV giữa các chu kỳ tuần và chu kỳ tháng.
  - Đưa ra cảnh báo Contango / Backwardation.

- [ ] **BOT-009B: Multi-Tenor Dynamic Contract Matcher**
  - Tích hợp template `calendar_spread` từ `builder.py`.
  - Thuật toán ghép cặp tự động giữa 1 hợp đồng Short kỳ hạn gần và 1 hợp đồng Long kỳ hạn xa trên cùng một Strike.

- [ ] **BOT-009C: Cross-Tenor Execution & Margin Calculator**
  - Tính toán biên độ ký quỹ chênh lệch giữa 2 kỳ hạn trên sàn Bybit (Portfolio Margin / Regular Margin).
  - Đặt lệnh mua chân xa trước để xác lập vị thế Long, sau đó mới bán chân gần.

- [ ] **BOT-009D: Continuous Front-Leg Rollover Engine**
  - Bộ máy điều khiển tự động tái tục (rollover) chân ngắn hạn: Khi chân gần hết hạn, quét tìm Strike mới phù hợp với giá Spot hiện tại và tự động bán hợp đồng tuần tiếp theo.

- [ ] **BOT-009E: Multi-Expiry Parquet Backtest Engine**
  - Xây dựng `CalendarSpreadBacktestEngine` trong `src/options_lib/strategy/calendar_spread_backtest.py`.
  - Khả năng đọc đồng thời nhiều chuỗi thời gian của 2 kỳ hạn khác nhau từ Parquet để định giá chuẩn xác giá trị spread qua từng mốc thời gian.

- [ ] **BOT-009F: Unit Tests & Verification**
  - Tạo `tests/test_calendar_spread_bot.py` và `tests/test_calendar_spread_backtest.py`.
  - Xác minh độ chính xác của cơ chế roll chân ngắn hạn qua nhiều chu kỳ liên tiếp.

---

## 4. Acceptance Criteria
1. Module bot `calendar_spread_bot.py` quản lý mượt mà 2 hợp đồng khác ngày đáo hạn.
2. Cơ chế roll chân ngắn hạn hoạt động trơn tru mà không làm gián đoạn chân dài hạn bảo kê.
3. Backtest chứng minh khả năng thu hoạch dòng tiền định kỳ trong các giai đoạn thị trường tích lũy dài hạn.
4. Đạt 100% tỷ lệ pass các test case kiểm tra chênh lệch kỳ hạn và tính toán margin.

