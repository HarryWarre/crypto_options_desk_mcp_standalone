# SWARM-001.4: Verdict Agent & Deribit Testnet Telemetry Sync

**Mã Sub-Issue:** SWARM-001.4  
**Master Issue:** [SWARM-001](swarm-001-multi-agent-trading-swarm-and-visual-desk.md)  
**Trạng thái:** To Do  
**Target:** `main`  
**File cần thêm/sửa:**
- `src/options_lib/verdict/verdict_agent.py` (Mới)
- `src/options_app/bot_manager.py` (Cập nhật)
- `src/options_app/api.py` (Cập nhật)
- `tests/test_verdict_and_deribit_sync.py` (Mới)

---

## 1. Mô Tả Chi Tiết

1. **Verdict Agent (Full Autonomous Swarm):**
   - Đánh giá tổng hợp tín hiệu từ Risk Engine và danh mục hiện hữu.
   - Tự động quyết định: `APPROVE` (đủ điều kiện, gửi lệnh sang Deribit Broker Adapter) hoặc `REJECT` (kèm mã lý do minh bạch, lưu telemetry).
2. **Deribit Testnet Live Bridge:**
   - Kích hoạt `use_deribit_testnet=True`.
   - Thu thập Live Equity (USD, BTC, ETH, USDC), Margin Utilization %, Open Orders, Positions thực tế trên sàn.
   - Lưu trữ lịch sử tài sản vào SQLite (`deribit_equity_history`) để phục vụ vẽ chart theo Ngày (1D), Tuần (1W), Tháng (1M).
   - Đẩy toàn bộ dữ liệu qua API `/api/v1/bot/status` và WebSocket `/api/v1/bot/stream`.
