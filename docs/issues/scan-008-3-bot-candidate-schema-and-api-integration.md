# SCAN-008.3: Chuẩn Hóa Schema Ứng Viên Bot, Tích Hợp REST API & Giao Diện Web Quick-Launch

**Mã Sub-Issue:** SCAN-008.3  
**Master Issue:** [SCAN-008](file:///Users/hoangviet/Flowsurface/crypto_options_desk_mcp/docs/issues/scan-008-bot-aligned-strategy-scanner.md)  
**Trạng thái:** To Do  
**Target:** `main`  
**File cần sửa:**
- `src/options_lib/opportunity_scanner.py`
- `src/options_app/api.py`
- `src/options_app/static/app.js`
- `src/options_app/static/index.html`
- `tests/test_options_app_api.py`

---

## 1. Mô Tả Chi Tiết (Detailed Description)

Sau khi Scanner đã tích hợp các bộ lọc Regime (SCAN-008.1) và cấu trúc chiến lược mở rộng (SCAN-008.2), bước cuối cùng là kết nối giữa **Phát hiện cơ hội (Discovery)** và **Thực thi giao dịch tự động (Execution)**.

Hiện tại:
- Kết quả quét trả về đối tượng `Opportunity` nhưng không có thông tin gắn kết với Bot Engine.
- Người dùng trên Web UI hoặc nhà phát triển gọi qua API không thể biết liệu cơ hội này có thể nạp thẳng vào `WheelBot`, `VerticalSpreadBot`, `IronButterflyBot`, `CalendarSpreadBot`, `LongVolBot`, hay `IronCondorBot` hay không.
- Chưa có nút bấm "Gửi lệnh sang Bot / Paper Trading" hoặc chuyển trực tiếp thành order lên sàn Deribit Testnet.

---

## 2. Thay Đổi Cần Thực Hiện (Implementation Changes)

1. **Bổ sung metadata Bot vào `Opportunity`:**
   ```python
   @dataclass(frozen=True)
   class BotCandidateMetadata:
       target_bot: str  # "wheel" | "vertical_spread" | "iron_butterfly" | "calendar" | "long_vol" | "iron_condor"
       is_bot_ready: bool
       bot_readiness_score: float  # 0.0 -> 1.0
       entry_payload: dict[str, Any]  # Payload cấu trúc tương thích với Candidate của bot tương ứng
       disqualification_reasons: tuple[str, ...] = ()
   ```
   Gắn `bot_metadata: BotCandidateMetadata | None = None` vào `Opportunity`.

2. **Endpoint Mới & Presets trong `src/options_app/api.py`:**
   - Thêm query parameter `bot_preset`:
     - `/api/scan?bot_preset=wheel`
     - `/api/scan?bot_preset=vertical_credit`
     - `/api/scan?bot_preset=iron_butterfly`
     - `/api/scan?bot_preset=calendar`
     - `/api/scan?bot_preset=long_vol`
     - `/api/scan?bot_preset=iron_condor`
   - Endpoint thực thi nhanh: `POST /api/bot/execute-scanner-candidate`
     - Nhận `entry_payload` từ cơ hội quét được.
     - Khởi tạo adapter Deribit Testnet (`DeribitBrokerAdapter`) hoặc Paper Account để đặt lệnh tự động ngay lập tức.

3. **Cập nhật Giao Diện Web (`src/options_app/static/`):**
   - Thêm dropdown bộ lọc: **Strategy Bot Preset** (All, The Wheel, Vertical Credit, Iron Butterfly, Calendar Spread, Long Volatility, Iron Condor).
   - Trên mỗi thẻ cơ hội (Opportunity Card):
     - Hiển thị badge: `[Bot Ready]` (màu xanh lá) nếu đạt đủ tiêu chuẩn.
     - Nút hành động: `⚡ Trade on Testnet` (gọi endpoint `/api/bot/execute-scanner-candidate`).

---

## 3. Tiêu Chí Nghiệm Thu (Acceptance Criteria)

- [ ] Gọi `/api/scan?bot_preset=calendar` tự động cấu hình các tham số DTE, RV ceiling, SMA20 filter chuẩn theo BOT-009.
- [ ] Mọi cơ hội trả về đều chứa `bot_metadata` với đầy đủ `entry_payload`.
- [ ] Endpoint `POST /api/bot/execute-scanner-candidate` nhận payload và thực thi thành công qua `DeribitBrokerAdapter` (hoặc mock client trong môi trường test).
- [ ] Test E2E và API test trong `tests/test_options_app_api.py` pass 100%.
- [ ] UI hiển thị trực quan nhãn Bot Ready và nút bấm hành động.
