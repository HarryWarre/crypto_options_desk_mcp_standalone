# SWARM-001.3: Industry-Standard Options Risk Engine & Dynamic Position Sizing

**Mã Sub-Issue:** SWARM-001.3  
**Master Issue:** [SWARM-001](swarm-001-multi-agent-trading-swarm-and-visual-desk.md)  
**Trạng thái:** To Do  
**Target:** `main`  
**File cần thêm/sửa:**
- `src/options_lib/risk/portfolio_risk_engine.py` (Mới)
- `src/options_lib/risk/__init__.py` (Mới)
- `tests/test_portfolio_risk_engine.py` (Mới)

---

## 1. Mô Tả Chi Tiết

Thay thế hoàn toàn cơ chế gán cứng $Qty = 1.0$ bằng bộ khung quản trị rủi ro danh mục phái sinh:
1. **Dynamic Position Sizing:** Định cỡ khối lượng dựa trên % rủi ro cho phép trên tổng Equity và Max Loss của cấu trúc, chuẩn hóa theo `min_trade_amount` của từng đồng coin trên Deribit (0.1 BTC, 1.0 ETH, 1.0 SOL).
2. **Portfolio Margin Budget:** Kiểm tra trần ký quỹ Initial Margin và Maintenance Margin (không vượt quá 60% Equity).
3. **Greeks Exposure Constraints:** Giới hạn Net Delta danh mục, Net Vega để chống shock biến động.
4. Xuất kết quả đánh giá cho từng Candidate: Khối lượng được duyệt ($AllocatedQty$), mức rủi ro tối đa ($MaxLoss$), và cảnh báo nếu có.
