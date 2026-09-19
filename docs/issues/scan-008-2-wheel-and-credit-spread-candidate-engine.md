# SCAN-008.2: Mở Rộng Chiến Lược The Wheel & Chuẩn Hóa Credit Spreads Trong Scanner

**Mã Sub-Issue:** SCAN-008.2  
**Master Issue:** [SCAN-008](file:///Users/hoangviet/Flowsurface/crypto_options_desk_mcp/docs/issues/scan-008-bot-aligned-strategy-scanner.md)  
**Trạng thái:** Completed  
**Target:** `main`  
**File cần sửa:**
- `src/options_lib/opportunity_scanner.py`
- `tests/test_opportunity_scanner.py`

---

## 1. Mô Tả Chi Tiết (Detailed Description)

### 1.1. The Wheel Strategy Scanner (BOT-006)
Chiến lược The Wheel là cỗ máy sinh dòng tiền ổn định nhất trong 5 bot (1,845 trades, PnL +$153,902.35, Win Rate 99.8%). Hiện tại, `opportunity_scanner.py` hoàn toàn không có định nghĩa chiến lược `wheel`.
- Wheel vận hành theo 2 pha độc lập:
  - **Pha 1 (Cash-Secured Put - CSP):** Bán Put OTM mục tiêu Delta $-0.20$ đến $-0.30$, DTE $7 - 30$ ngày. Cần tính toán chỉ số APY quy đổi:
    $$\text{APY} = \frac{\text{Bid Price}}{\text{Strike}} \times \frac{365}{\text{DTE}} \times 100\%$$
    Chỉ chọn hợp đồng có $\text{APY} \ge 15\%$ và xác suất không bị gán (Probability of OTM) cao.
  - **Pha 2 (Covered Call - CC):** Dành cho tài khoản đã sở hữu Spot (hoặc bị gán từ CSP). Bán Call OTM có Strike $\ge$ Giá vốn mua (Cost Basis), Delta $0.20 - 0.30$, DTE $7 - 21$ ngày.

### 1.2. Directional Credit Spreads (BOT-007)
Trong `opportunity_scanner.py`, các chiến lược `bull_put_vertical` và `bear_call_vertical` hiện đang được tạo ra một cách cơ bản từ các cặp strike. Để đồng bộ với BOT-007:
- Bắt buộc kiểm tra tỷ lệ Credit-to-Width:
  $$\text{Credit Ratio} = \frac{\text{Net Credit}}{\text{Strike Width}} \ge 15\% \text{ đến } 20\%$$
- Khóa Delta chân bán (Short Leg Delta) trong khoảng $0.20 - 0.28$ để tối ưu hóa Win Rate (~98.8% trong backtest thực tế).
- Chân mua bảo hiểm (Long Protective Wing) phải có Delta nhỏ ($0.05 - 0.10$) để giảm thiểu chi phí hedging.

---

## 2. Thay Đổi Cần Thực Hiện (Implementation Changes)

1. **Bổ sung `wheel_csp` và `wheel_cc` vào `Strategy` Literal trong `opportunity_scanner.py`:**
   - Thêm vào danh mục `_SUPPORTED_STRATEGIES`.
   - Hàm `_wheel_csp_candidates()`:
     - Lọc các hợp đồng Put OTM có DTE từ 7 đến 30 ngày.
     - Lọc Delta trong dải $[-0.35, -0.15]$ (tâm điểm quanh $-0.25$).
     - Tính toán Margin yêu cầu ($\approx \text{Strike} \times \text{Qty}$) và APY lợi nhuận.
   - Hàm `_wheel_cc_candidates(cost_basis)`:
     - Lọc các hợp đồng Call có Strike $\ge \text{cost\_basis}$.
     - Lọc Delta trong dải $[0.15, 0.35]$.

2. **Cập nhật hàm ghép cặp `_vertical_leg_sets()` cho Credit Spreads:**
   - Thêm điều kiện kiểm tra tỷ lệ Credit / Width ngay trong quá trình screening.
   - Bổ sung trường `credit_ratio` vào payoff metrics của cơ hội.

3. **Tham số cấu hình mới trong `ScanRequest`:**
   - `wheel_cost_basis: float | None = None`: Giá vốn dùng khi quét Covered Call của The Wheel.
   - `wheel_min_apy: float = 0.15`: Lợi suất APY tối thiểu yêu cầu (15%/năm).

---

## 3. Tiêu Chí Nghiệm Thu (Acceptance Criteria)

- [x] Yêu cầu quét `strategies=("wheel_csp",)` trả về danh sách các Put hợp lệ kèm chỉ số APY quy đổi rõ ràng.
- [x] Yêu cầu quét `strategies=("wheel_cc",)` với `wheel_cost_basis=90000` không sinh ra bất kỳ Call nào có Strike $< 90,000$.
- [x] Vertical Credit Spreads có tỷ lệ Net Credit / Width $< 15\%$ sẽ bị loại bỏ hoặc đánh dấu không đủ điều kiện bot.
- [x] Viết đầy đủ unit tests kiểm thử logic sinh ứng viên The Wheel và Credit Spread.
