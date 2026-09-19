# BOT-011: Deribit Testnet Integration & Multi-Tier Strategy Accounts (Swing, Intraday, HFT)

**Status:** in-progress  
**Branch:** `feat/bot-011-deribit-testnet-paper-trading`  
**Target:** `main`  
**Blueprint Reference:** [bot-001-virtual-paper-trading-engine.md](file:///Users/hoangviet/Flowsurface/crypto_options_desk_mcp/docs/issues/bot-001-virtual-paper-trading-engine.md), [paper_broker](file:///Users/hoangviet/Flowsurface/crypto_options_desk_mcp/src/options_lib/paper_broker)

---

## 1. Problem & Context
Hệ thống demo trading của Bybit đối với thị trường Options gặp nhiều hạn chế kỹ thuật:
1. **Sổ lệnh Testnet rỗng:** Thiếu vắng Market Maker bot duy trì quote 2 chiều, dẫn đến lệnh Limit không khớp hoặc bị trượt giá phi thực tế.
2. **Lỗi hệ thống ký quỹ UTA:** Unified Trading Account trên testnet thường xuyên out-of-sync, báo lỗi margin call ảo hoặc không hỗ trợ chính xác Portfolio Margin (PMM) cho multi-leg options.

**Giải pháp:** Tích hợp trực tiếp môi trường **Deribit Testnet (`test.deribit.com`)** làm Broker Demo / Paper Trading chính thức cho toàn bộ Desk Options.
Deribit là sàn chuyên options thanh khoản lớn nhất thế giới, testnet duy trì market maker bot 24/7, khớp lệnh hai chiều chân thực, hỗ trợ đầy đủ Greeks/IV, Portfolio Margin chuẩn và Faucet testnet tức thì.

---

## 2. Multi-Tier Strategy Account Architecture

Nhằm phân tách rủi ro ký quỹ và tối ưu độ trễ cho các mô hình giao dịch khác nhau, hệ thống chia cấu trúc tài khoản thành 3 phân tầng (Tiered Sub-accounts) dưới 1 Master Account Deribit Testnet:

```text
               ┌──────────────────────────────────────┐
               │    Deribit Master Testnet Account     │
               └──────────────────┬───────────────────┘
                                  │
         ┌────────────────────────┼────────────────────────┐
         ▼                        ▼                        ▼
┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐
│  Tier 1: Swing   │    │ Tier 2: Intraday │    │   Tier 3: HFT    │
│  (Thực hiện trước│    │ (Scalping / Gamma│    │ (Microstructure /│
│   ưu tiên số 1)  │    │  0-2 DTE)        │    │  Market Making)  │
├──────────────────┤    ├──────────────────┤    ├──────────────────┤
│• Iron Condor     │    │• 0DTE Straddle   │    │• Orderbook MM    │
│• Calendar Spread │    │• Gamma Scalping  │    │• Spread Arbitrage│
│• The Wheel       │    │• Vol Breakout    │    │• Sub-ms JSON-RPC │
│• 7-30 DTE        │    │• WebSocket feed  │    │• Direct WS pipes │
└──────────────────┘    └──────────────────┘    └──────────────────┘
```

### Chi tiết phân tầng:
1. **Swing Account (Triển khai đầu tiên):**
   - **Chiến lược:** Iron Condor, Calendar Spread, Iron Butterfly, Vertical Credit Spread, The Wheel.
   - **Đặc tính:** Thời gian nắm giữ từ 3 - 30 ngày, tần suất thấp, tối ưu hóa độ thu phí Theta và sử dụng ký quỹ Portfolio Margin an toàn.
   - **Tài sản:** BTC, ETH, SOL (USDC-settled & Coin-margined).
2. **Intraday Account (Giai đoạn tiếp theo):**
   - **Chiến lược:** 0-2 DTE Scalping, Long Volatility Breakout, Intraday Straddle/Strangle.
   - **Đặc tính:** Vị thế đóng trong ngày, theo dõi sát bước nhảy Gamma và biến động ngầm định (IV).
3. **HFT Account (Giai đoạn nâng cao):**
   - **Chiến lược:** Tự động tạo lập thanh khoản (Avellaneda-Stoikov MM), chênh lệch giá sổ lệnh (Latency Arbitrage).
   - **Đặc tính:** Kết nối WebSocket JSON-RPC tốc độ cao, quản lý rate-limit và cancel-on-disconnect.

---

## 3. Sub-tasks / Child Issues

- [x] **BOT-011A: Deribit Testnet Account Setup & Sub-account Management**
  - Đăng ký và kích hoạt Master Account trên `test.deribit.com` (`flowsurfaceswing`).
  - Khởi tạo sub-account/chuyên biệt cho `swing` với toàn quyền (`trade:read_write`, `account:read_write`, `wallet:read_write`, `block_trade`, `block_rfq`).
  - Chuẩn bị sẵn cấu trúc mở rộng cho `intraday` và `hft`.
  - Đã lấy API Key / Secret (`swing_desk`) và lưu trữ an toàn vào `.env` (`DERIBIT_TESTNET_CLIENT_ID`, `DERIBIT_TESTNET_CLIENT_SECRET`).

- [x] **BOT-011B: Testnet Faucet Automated Refill**
  - Đã nhận số dư thử nghiệm Testnet tự động: **100 BTC** (~$8.14M) và **100,000 USDC**.
  - Kiểm tra kết nối Private API đọc số dư thành công 100%.

- [x] **BOT-011C: Deribit JSON-RPC / WebSocket & REST Connector**
  - Xây dựng connector module trong `src/options_lib/deribit_client/`:
    - Authentication (`public/auth` client credentials, access token caching).
    - Quản lý lệnh: `buy`, `sell`, `cancel`, `cancel_all`, `get_order_state`, `get_open_orders_by_currency`.
    - Quản lý vị thế & số dư: `get_positions`, `get_account_summary`.
    - Lấy dữ liệu hợp đồng & sổ lệnh: `get_instruments`, `get_order_book`, `get_ticker`.
  - Đã có test suite tự động đạt 5/5 test pass trong `tests/test_deribit_client.py`.

- [x] **BOT-011D: Deribit Paper Broker Adapter (`DeribitBrokerAdapter`)**
  - Xây dựng lớp adapter `DeribitBrokerAdapter` trong `src/options_lib/paper_broker/deribit_adapter.py`.
  - Tự động map `PaperOrder` sang API Deribit (`buy`/`sell`), chuẩn hóa symbol instrument.
  - Đồng bộ vị thế và số dư thực tế từ Deribit vào `PaperAccount`.

- [ ] **BOT-011E: Swing Bot Deployment on Deribit Testnet**
  - Đã chạy kịch bản kiểm thử trực tiếp `scripts/verify_deribit_testnet_trade.py`: Đặt lệnh Limit thành công (Order ID `119694964998`), xác nhận trong Open Orders và hủy lệnh thành công 100%.
  - Kết nối `IronCondorBot` và `CalendarSpreadBot` gửi lệnh trực tiếp lên Deribit Testnet khi bật cờ `use_deribit_testnet`.

