# BOT-006: The Wheel Strategy Bot (Cash-Secured Put & Covered Call Yield)

**Status:** completed  
**Branch:** `feat/bot-006-wheel-strategy-bot`  
**Target:** `main`  
**Blueprint Reference:** [iron_condor_bot.py](file:///Users/hoangviet/Flowsurface/crypto_options_desk_mcp/src/options_lib/strategy/iron_condor_bot.py), [iron_condor_backtest.py](file:///Users/hoangviet/Flowsurface/crypto_options_desk_mcp/src/options_lib/strategy/iron_condor_backtest.py)

---

## 1. Problem & Context
The Wheel Strategy là một trong những chiến lược quyền chọn thu hoạch dòng tiền (cashflow yield) và tích sản bền vững nhất trong thị trường crypto:
1. **Pha 1 (Bán Put bằng tiền mặt - Cash-Secured Put):** Khi chưa nắm giữ spot, bot bán OTM Put để thu phí bảo hiểm (premium). Nếu quyền chọn đáo hạn vô giá trị (OTM), bot giữ 100% phí bảo hiểm và tiếp tục bán Put mới.
2. **Pha 2 (Gán mua Spot - Assignment):** Nếu giá spot giảm xuống dưới strike của Put tại ngày đáo hạn, bot nhận mua số lượng coin spot tương ứng ở mức giá strike (vốn đã được chiết khấu bởi khoản phí bảo hiểm đã thu).
3. **Pha 3 (Bán Call bảo chứng - Covered Call):** Sau khi sở hữu spot, bot tự động bán OTM Call với strike cao hơn giá vốn (Cost-Basis) để tiếp tục thu phí bảo hiểm định kỳ.
4. **Pha 4 (Bị gán bán Spot - Called Away):** Khi giá spot vượt lên trên strike của Call, bot bán toàn bộ số coin ở giá strike có lãi, thu hồi toàn bộ tiền mặt USDT và quay trở lại Pha 1.

**Thách thức cần giải quyết:**
- Quản lý trạng thái chuyển tiếp (State Machine) giữa Tiền mặt (USDT) và Spot coin bền vững qua các lần khởi động lại bot.
- Đảm bảo quy tắc **Cost-Basis Floor**: Không bao giờ được phép bán Call ở strike thấp hơn giá vốn thực nhập để loại bỏ rủi ro bán lỗ spot.
- Động cơ Backtest chuyên biệt có khả năng đối sánh chính xác hiệu suất The Wheel so với Buy-and-Hold.

---

## 2. Target Strategy Specs (The Wheel)

- **Tài sản hỗ trợ:** BTC, ETH, SOL, DOGE, MNT, XRP
- **Chế độ giao dịch:** Paper Trading qua `PaperBroker` và Live qua Bybit V5 API
- **Chu kỳ kỳ hạn (Tenor):** 5 – 25 DTE (Tối ưu hóa giữa tốc độ thu phí và mức đệm an toàn giá)
- **Pha Cash-Secured Put (CSP):**
  - Delta mục tiêu: $-0.15$ đến $-0.25$ (Xác suất OTM: 75% – 85%)
  - Bộ lọc IV-RV: $\text{IV} - \text{RV} \ge 0.0\text{ vol pts}$
  - Chiết khấu giá tối thiểu: Strike thấp hơn ít nhất 5% – 12% so với giá Spot hiện tại.
- **Pha Covered Call (CC):**
  - Strike condition: $\text{Strike}_{\text{CC}} \ge \text{Net Cost Basis}$
  - Delta mục tiêu: $+0.15$ đến $+0.25$
- **Quy tắc Quản lý vị thế & Chốt lời:**
  - **Take Profit (TP):** Đóng sớm khi thu được $\ge 50\%$ phí bảo hiểm tối đa trên hợp đồng đang mở để quay vòng vốn ngay lập tức.
  - **DTE Expiry Roll:** Nếu DTE $\le 1.0$ ngày và vị thế đang có lãi $\ge 80\%$, tự động tất toán và mở vòng mới cho tuần sau.
  - **Defensive Roll (CSP bị đe dọa):** Nếu Spot thủng strike Put trước DTE 3 ngày, hỗ trợ Roll Down & Out sang kỳ hạn tuần sau để lấy thêm credit.

---

## 3. Sub-tasks / Child Issues

- [x] **BOT-006A: CSP Screener & Dynamic Strike Selector**
  - Tích hợp với `builder.py` template `long_put` / naked put role.
  - Lọc hợp đồng Put theo Delta $(-0.20 \pm 0.05)$, DTE 5–25 ngày và OTM buffer.
  - Tự động sizing dựa trên notional allocation của tài khoản.

- [x] **BOT-006B: Persistent Inventory State Machine**
  - Xây dựng state machine 4 trạng thái:
    - `IDLE_CASH` $\rightarrow$ `OPEN_CSP` $\rightarrow$ `ASSIGNED_SPOT` $\rightarrow$ `OPEN_COVERED_CALL`.
  - Lưu trạng thái vào `portfolio_data/wheel_state.json` và SQLite DB (`PaperStorage`).
  - Ghi nhận lịch sử nạp/rút/gán tài sản (Assignment ledger).

- [x] **BOT-006C: Covered Call Auto-Writer với Cost-Basis Floor**
  - Tính toán chính xác `realized_net_cost_basis`.
  - Tự động chọn hợp đồng Call thỏa mãn $\text{Strike} \ge \text{Cost Basis}$ với Delta từ $0.15 - 0.25$.
  - Bảo đảm không bán Call dưới giá vốn nhập hàng.

- [x] **BOT-006D: Wheel Lifecycle Engine (50% TP & Roll Logic)**
  - Vòng lặp giám sát giá mark theo thời gian thực (`evaluate_active_position`).
  - Tự động đóng vị thế chốt lời khi đạt 50% TP.
  - Xử lý đáo hạn và chuyển đổi trạng thái khi bị thực hiện quyền (Assignment / Called Away).

- [x] **BOT-006E: Wheel Historical Parquet Backtest Engine**
  - Xây dựng `WheelBacktestEngine` trong `src/options_lib/strategy/wheel_backtest.py`.
  - Mô phỏng toàn bộ vòng quay qua 75 ngày dữ liệu Parquet trên 6 tài sản (BTC, ETH, SOL, DOGE, MNT, XRP).
  - Kết quả đạt **1,845 trades**, Win Rate **99.8%**, Net PnL **+$153,902.35**, Profit Factor **12,756.75**.

- [x] **BOT-006F: Unit Tests & Verification Suite**
  - Tạo `tests/test_wheel_bot.py` và `tests/test_wheel_backtest.py`.
  - Đạt 100% test pass (5/5 unit tests mới pass mượt mà).

---

## 4. Acceptance Criteria
1. Module `src/options_lib/strategy/wheel_bot.py` và `src/options_lib/strategy/wheel_backtest.py` được triển khai theo đúng cấu trúc chuẩn của `iron_condor_bot.py`.
2. Script backtest chạy thành công trên dữ liệu parquet `data/multi_asset_parquet/` và xuất kết quả `data/wheel_multi_asset_portfolio_results.json`.
3. Số lượng lệnh backtest đạt yêu cầu: 1,845 lệnh (vượt mốc 100 lệnh).
4. Toàn bộ unit test mới đạt tỷ lệ pass 100%.

