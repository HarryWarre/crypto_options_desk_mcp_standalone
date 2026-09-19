# SCAN-008: Master Issue — Cập Nhật Opportunity Scanner Theo Tiêu Chuẩn Các Bot Giao Dịch

**Mã Issue:** SCAN-008  
**Tiêu đề:** Đồng bộ hóa Scanner với Các Bộ Lọc Edge & Tiêu Chí Tuyển Chọn Của 6 Options Trading Bots  
**Trạng thái:** Completed  
**Target:** `main`  
**Nhánh dự kiến:** `main`  
**Liên kết tham chiếu:**
- [BOT-000 Master Roadmap](file:///Users/hoangviet/Flowsurface/crypto_options_desk_mcp/docs/issues/bot-000-multi-strategy-options-roadmap.md)
- [BOT-006: The Wheel](file:///Users/hoangviet/Flowsurface/crypto_options_desk_mcp/docs/issues/bot-006-wheel-strategy-bot.md)
- [BOT-007: Vertical Credit Spreads](file:///Users/hoangviet/Flowsurface/crypto_options_desk_mcp/docs/issues/bot-007-vertical-credit-spreads-engine.md)
- [BOT-008: Dynamic Iron Butterfly](file:///Users/hoangviet/Flowsurface/crypto_options_desk_mcp/docs/issues/bot-008-iron-butterfly-strategy-engine.md)
- [BOT-009: Calendar Spreads](file:///Users/hoangviet/Flowsurface/crypto_options_desk_mcp/docs/issues/bot-009-calendar-spread-strategy-engine.md)
- [BOT-010: Long Volatility Straddle](file:///Users/hoangviet/Flowsurface/crypto_options_desk_mcp/docs/issues/bot-010-long-volatility-straddle-strangle-engine.md)
- [BOT-011: Deribit Testnet Adapter](file:///Users/hoangviet/Flowsurface/crypto_options_desk_mcp/docs/issues/bot-011-deribit-testnet-paper-trading-integration.md)

---

## 1. Bối Cảnh & Vấn Đề (Context & Problem)

Hiện tại, module `src/options_lib/opportunity_scanner.py` phục vụ quét cơ hội thị trường Options dựa trên định giá lý thuyết Black-Scholes và tìm kiếm edge mô hình (`model_edge_after_costs > 0`). Tuy nhiên:

1. **Lệch pha giữa Scanner và Bot Execution Engine:**
   - Quá trình backtest thực tế trên > 4,800 lệnh (BTC, ETH, SOL, DOGE, MNT, XRP) ở 5 bot mới đã chứng minh: **chỉ tính toán Black-Scholes edge là không đủ** để tạo ra lợi nhuận bền vững. Mỗi chiến lược đòi hỏi các bộ lọc chế độ thị trường (Regime Filters) và ngưỡng tuyển chọn cấu trúc nghiêm ngặt (như IV Discount ở Straddle, RV Ceiling ở Calendar, IV-RV spread ở Iron Condor/Butterfly).
   - Scanner hiện tại trả về nhiều cơ hội thỏa mãn công thức BS tĩnh nhưng lại **vi phạm điều kiện vào lệnh của Bot** (ví dụ: Long Straddle khi IV quá đắt so với RV, hoặc Calendar Spread khi RV > 55% dẫn tới nguy cơ bục cánh).

2. **Thiếu hỗ trợ chiến lược The Wheel (BOT-006):**
   - Scanner chỉ có `covered_call` và `protective_put` dạng overlay đơn lẻ, chưa hỗ trợ chế độ quét chuyên biệt cho The Wheel: lọc Cash-Secured Put (Delta 0.20-0.30, APY > 15%) và Covered Call tối ưu theo giá vốn (Cost Basis).

3. **Không xuất được định dạng cấu trúc ứng viên (Bot Candidates):**
   - Scanner trả về `Opportunity` chung chung, không tương thích trực tiếp với các dataclass cấu hình của từng bot (`WheelCandidate`, `VerticalSpreadCandidate`, `IronButterflyCandidate`, `CalendarSpreadCandidate`, `LongVolCandidate`, `IronCondorCandidate`), khiến người dùng hoặc Bot Manager không thể kích hoạt 1-click execution vào Deribit Testnet hay Bybit.

---

## 2. Mục Tiêu (Objectives)

Nâng cấp `src/options_lib/opportunity_scanner.py` và các API liên quan trong `src/options_app/api.py`:
- [x] Tích hợp toàn bộ bộ lọc Regime & Edge đã được kiểm chứng từ 5 bot (BOT-006 đến BOT-010) và Iron Condor.
- [x] Bổ sung preset quét theo phong cách bot (`bot_aligned_mode = True` hoặc preset riêng cho từng bot).
- [x] Trả về thông tin đánh giá sẵn sàng vào lệnh (`bot_eligible: bool`, `bot_rejection_reasons: list[str]`).
- [x] Hỗ trợ chuyển đổi từ `Opportunity` sang payload chuẩn hóa để nạp trực tiếp vào Bot Engine / Deribit Testnet.

---

## 3. Ma Trận Tiêu Chuẩn Tuyển Chọn Của Scanner Theo Từng Bot

| Bot | Chiến Lược Scanner | Bộ Lọc Regime Cốt Lõi (Đã Chứng Minh Edge) | Tiêu Chí Strike & Tenor | Ngưỡng Lợi Nhuận / Rủi Ro |
| :--- | :--- | :--- | :--- | :--- |
| **BOT-001/005** | `iron_condor` | IV - RV Spread >= $3.0\text{ vol pts}$ ($0.03$) | Short Delta: 0.12 - 0.20; Wing Delta: 0.02 - 0.05; DTE 7 - 21d | Net credit >= 20% Wing width |
| **BOT-006** | `wheel` (`csp` & `cc`) | Implied Volatility Rank (IVR) >= 30% | CSP Delta: 0.20 - 0.30; CC Strike >= Cost Basis; DTE 7 - 30d | APY quy đổi >= 15%; Max risk = Strike $\times$ Margin |
| **BOT-007** | `bull_put_vertical` / `bear_call_vertical` | High IV Regime: IV >= RV hoặc IVR >= 40%; ADX xác nhận xu hướng | Short Delta: 0.20 - 0.28; Long Wing Delta: 0.05 - 0.10; DTE 7 - 21d | Net credit >= 15% - 20% Wing width |
| **BOT-008** | `iron_butterfly` | Pinning / Low Realized Vol Regime: IV - RV >= 5 vol pts; ADX < 25 | ATM Short Straddle (Call & Put chung strike ATM, Delta $\approx$ 0.50); OTM Wings: 5-10% spot | Net credit >= 60% - 70% Wing width |
| **BOT-009** | `calendar_spread` | **RV Ceiling**: $\text{RV} \le 55\%$; **SMA20 Consolidation**: Khoảng cách Spot tới SMA20 $\le 2.0\%$ | Near DTE: 7 - 14d (bán); Far DTE: 21 - 45d (mua); Cùng Strike ATM $\pm 3\%$ | Near IV > Far IV (Backwardation) hoặc Term Structure dốc thuận lợi |
| **BOT-010** | `long_straddle` / `long_strangle` | **IV Discount Filter**: $\text{RV} \ge \text{IV} \times 1.00$ (IV đang bán rẻ hơn biến động thực) | ATM Call + ATM Put (Delta 0.45 - 0.55); DTE 14 - 35d | Gamma/Theta ratio cao; Max loss = Net Debit |

---

## 4. Danh Sách Các Sub-Issues (Công Việc Cụ Thể)

Để triển khai mạch lạc và kiểm thử độc lập, issue lớn này được chia thành 3 sub-issues:

### 4.1. [SCAN-008.1 — Volatility & Regime Edge Filters Integration](file:///Users/hoangviet/Flowsurface/crypto_options_desk_mcp/docs/issues/scan-008-1-volatility-regime-edge-filters.md) - [x] Completed
- Mở rộng `scan_opportunities_with_historical_context` không chỉ lọc `iron_condor` mà áp dụng:
  - **IV Discount Filter** cho `long_straddle` / `long_strangle` (`RV >= IV`).
  - **RV Ceiling** (`RV <= 0.55`) và **Spot Drift Filter** cho `calendar_spread`.
  - **High IV Regime** (`IV - RV >= threshold`) cho `iron_butterfly` và vertical credit spreads.
- Gắn các mã từ chối minh bạch (`rejection_reasons`): `iv_discount_missing`, `rv_ceiling_exceeded`, `spot_drift_too_wide`, `credit_ratio_below_minimum`.

### 4.2. [SCAN-008.2 — The Wheel & Directional Credit Spread Scanner Extension](file:///Users/hoangviet/Flowsurface/crypto_options_desk_mcp/docs/issues/scan-008-2-wheel-and-credit-spread-candidate-engine.md) - [x] Completed
- Bổ sung cấu trúc quét chuyên biệt cho The Wheel:
  - Phase 1: Quét Cash-Secured Put (tính toán APY tiềm năng, margin lock, probability of profit).
  - Phase 2: Quét Covered Call theo tham số `cost_basis` người dùng cung cấp.
- Cập nhật bộ lọc Vertical Credit Spread: bắt buộc kiểm tra tỷ lệ Credit/Width và delta biên cánh bảo vệ.

### 4.3. [SCAN-008.3 — Bot Candidate Schema, API Presets & UI Quick-Launch](file:///Users/hoangviet/Flowsurface/crypto_options_desk_mcp/docs/issues/scan-008-3-bot-candidate-schema-and-api-integration.md) - [x] Completed
- Bổ sung trường `bot_compatibility` vào `Opportunity`:
  - `target_bot: str`: Tên bot tương ứng (`wheel`, `vertical_spread`, `iron_butterfly`, `calendar`, `long_vol`, `iron_condor`).
  - `bot_entry_ready: bool`: Đạt 100% tiêu chuẩn vào lệnh của bot.
  - `bot_candidate_payload: dict`: Payload json sẵn sàng chuyển sang `execute_order` trên Deribit Testnet / Bybit.
- Bổ sung API endpoints `/api/scanner/bot-presets` và tham số `bot_mode=true` trong `/api/scan`.
- Cập nhật giao diện Scanner Web: nút "Bot Ready Filter" và nút "Send to Bot / Paper Trade".

---

## 5. Kế Hoạch Xác Minh & Kiểm Thử (Verification Plan)

1. **Unit & Regression Tests:**
   - Viết các test case trong `tests/test_opportunity_scanner.py` xác minh từng bộ lọc regime:
     - Test Straddle bị reject nếu $IV > RV$.
     - Test Calendar Spread bị reject nếu $RV > 55\%$ hoặc Spot lệch SMA20 $> 2\%$.
     - Test Iron Butterfly và Credit Spread yêu cầu tỷ lệ Credit/Width tối thiểu.
     - Test The Wheel tạo ra cơ hội CSP với APY và Delta chuẩn xác.
2. **Backtest Alignment Check:**
   - Chạy scanner trên dữ liệu lịch sử snapshot, đảm bảo các cơ hội được xếp hạng đầu (Rank 1-5) chính là các trade đã mang lại PnL dương trong backtest của từng bot.
3. **End-to-End Testnet Dispatch:**
   - Kiểm tra luồng: Scanner tìm thấy cơ hội -> chọn Send to Bot -> Deribit Testnet Adapter nhận order và thực thi thành công.

---

## 6. Tiêu Chí Nghiệm Thu (Acceptance Criteria)

- [x] Toàn bộ 6 chiến lược bot đều có bộ lọc regime và tham số strike/tenor tương ứng trong `opportunity_scanner.py`.
- [x] Mọi vi phạm tiêu chí bot đều được ghi nhận vào `rejections` với lý do rõ ràng.
- [x] Có helper chuyển đổi từ `Opportunity` sang format candidate của bot tương ứng.
- [x] Tất cả test cases cũ và mới đều pass 100% (`pytest tests/test_*.py`).
- [x] Knowledge graph được cập nhật đồng bộ (`graphify update .`).
