# SCAN-008.1: Tích Hợp Các Bộ Lọc Volatility & Regime Edge Theo Bot Vào Scanner

**Mã Sub-Issue:** SCAN-008.1  
**Master Issue:** [SCAN-008](file:///Users/hoangviet/Flowsurface/crypto_options_desk_mcp/docs/issues/scan-008-bot-aligned-strategy-scanner.md)  
**Trạng thái:** To Do  
**Target:** `main`  
**File cần sửa:**
- `src/options_lib/opportunity_scanner.py`
- `src/options_lib/historical_volatility.py`
- `tests/test_opportunity_scanner.py`

---

## 1. Mô Tả Chi Tiết (Detailed Description)

Hiện tại, hàm `scan_opportunities_with_historical_context()` chỉ kiểm tra chênh lệch `IV - RV >= ic_min_iv_rv_spread` riêng cho chiến lược `iron_condor`. Tất cả các chiến lược khác (`calendar_spread`, `long_straddle`, `long_strangle`, `iron_butterfly`, `vertical_spread`) đều bỏ qua bối cảnh biến động thực tế (Realized Volatility - RV) và cấu trúc kỳ hạn (Term Structure).

Kết quả nghiên cứu backtest từ BOT-008, BOT-009, BOT-010 cho thấy:
1. **Long Straddle / Long Strangle (BOT-010):**
   - Mua biến động khi $IV \ge RV$ khiến vị thế chịu lỗ nặng nề do theta decay và IV crush.
   - Chiến lược chỉ có lãi (Profit Factor 1.32, 137 trades) khi áp dụng **IV Discount Filter**: $\text{RV} \ge \text{IV} \times 1.00$. Scanner cần bắt buộc kiểm tra điều kiện này khi `enforce_bot_filters=True`.
2. **Calendar Spread (BOT-009):**
   - Calendar Spread bị lỗ nặng khi thị trường biến động mạnh vì giá cơ sở văng khỏi strike trung tâm.
   - Yếu tố quyết định edge (Win Rate 86.1%, PF 5.22, 613 trades) là:
     - **RV Ceiling**: $\text{RV} \le 55\%$ ($0.55$).
     - **Consolidation Gate**: Khoảng cách giá spot tới SMA20 $\le 2.0\%$.
     - **Term Structure Contango**: Near IV cao hơn hoặc xấp xỉ Far IV, tránh mua Far IV ở vùng đỉnh quá đắt.
3. **Dynamic Iron Butterfly (BOT-008):**
   - Đòi hỏi thị trường sideway găm chốt tại ATM: $IV - RV \ge 5.0\text{ vol pts}$ để đảm bảo thu đủ lượng net credit hấp thụ độ lệch giá.

---

## 2. Thay Đổi Cần Thực Hiện (Implementation Changes)

1. **Mở rộng `ScanRequest`:**
   - `enforce_bot_regime: bool = False`: Bật chế độ lọc nghiêm ngặt theo bot.
   - `straddle_min_rv_iv_ratio: float = 1.0`: Tỷ lệ tối thiểu $RV / IV$ cho long straddle/strangle.
   - `calendar_max_rv: float = 0.55`: Ngưỡng RV tối đa cho phép vào Calendar Spread.
   - `calendar_max_spot_drift_pct: float = 2.0`: Ngưỡng sai lệch giá spot khỏi vùng tích lũy.
   - `butterfly_min_iv_rv_spread: float = 5.0`: Chênh lệch $IV - RV$ tối thiểu cho Iron Butterfly.
   - `credit_spread_min_credit_ratio: float = 0.20`: Tỷ lệ Credit / Wing width tối thiểu (20%).

2. **Cập nhật `scan_opportunities_with_historical_context`:**
   - Lặp qua danh sách cơ hội và áp dụng bộ lọc tương ứng với từng loại chiến lược:
     - Với `long_straddle` / `long_strangle`: So sánh $RV$ của tài sản với $IV$ bình quân của 2 chân. Nếu $RV < IV \times \text{straddle\_min\_rv\_iv\_ratio}$, reject với lý do `"iv_expensive_relative_to_rv"`.
     - Với `calendar_spread`: So sánh $RV$ với $\text{calendar\_max\_rv}$. Nếu $RV > \text{calendar\_max\_rv}$, reject với lý do `"rv_above_calendar_ceiling"`.
     - Với `iron_butterfly`: So sánh $IV - RV$ với $\text{butterfly\_min\_iv\_rv\_spread}$. Nếu không đạt, reject với lý do `"iv_rv_spread_below_butterfly_minimum"`.

3. **Ghi nhận Rejection Types:**
   - Đảm bảo các `reasons` và `messages` trong `RejectedCandidate` rõ ràng, minh bạch để người dùng hiểu tại sao cơ hội bị loại bỏ.

---

## 3. Tiêu Chí Nghiệm Thu (Acceptance Criteria)

- [ ] Unit test: Long straddle bị từ chối nếu $IV = 60\%$ và $RV = 50\%$; được duyệt nếu $IV = 50\%$ và $RV = 60\%$.
- [ ] Unit test: Calendar spread bị từ chối nếu $RV = 65\%$; được duyệt nếu $RV = 45\%$.
- [ ] Unit test: Iron butterfly bị từ chối nếu $IV - RV < 5.0$ vol points.
- [ ] Các chiến lược cũ chạy bình thường nếu `enforce_bot_regime = False` (backward compatibility 100%).
- [ ] Pytest toàn bộ suite pass xanh 100%.
