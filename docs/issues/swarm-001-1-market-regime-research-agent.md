# SWARM-001.1: Market Regime Research Agent (Hybrid Quantitative & LLM Engine with Fallback)

**Mã Sub-Issue:** SWARM-001.1  
**Master Issue:** [SWARM-001](swarm-001-multi-agent-trading-swarm-and-visual-desk.md)  
**Trạng thái:** In Progress  
**Target:** `main`  
**File cần thêm/sửa:**
- `src/options_lib/research/market_regime.py` (Mới)
- `src/options_lib/research/__init__.py` (Mới)
- `tests/test_market_regime.py` (Mới)

---

## 1. Mô Tả Chi Tiết

Tầng đầu tiên trong workflow Swarm là **Research Agent**. Nhiệm vụ của Agent này là phân tích toàn diện hiện trạng thị trường phái sinh của từng tài sản (BTC, ETH, SOL, ...) và toàn thị trường để cung cấp định hướng cho các Trader Agents:
1. **Phân tích Định lượng (Quantitative Metrics):**
   - **Volatility Regime:** So sánh Realized Volatility (RV30d/RV7d) với Implied Volatility (ATM IV), xác định IV - RV Spread, Volatility Rank/Percentile (High Vol, Low Vol, IV Crush, Vol Expansion).
   - **Directional Trend:** Giá Spot so với đường trung bình (SMA20, SMA50), độ lệch chuẩn giá, đà xu hướng (Bullish, Bearish, Sideways/Range-bound).
   - **Term Structure:** Slope giữa Near IV và Far IV (Contango, Backwardation, Flat).
   - **Skew / Smile:** Chênh lệch giữa OTM Put IV và OTM Call IV (Put Skew - thị trường phòng hộ giảm, Call Skew - thị trường FOMO tăng, Balanced).
2. **LLM Synthesis (Gemini):**
   - Đưa các chỉ số định lượng vào prompt của LLM Agent để sinh ra nhận định tổng hợp súc tích: tóm tắt bối cảnh, luận điểm chính (Key Thesis), và gợi ý các nhóm chiến lược phù hợp.
3. **Cơ chế Fallback 100% tự động:**
   - Nếu không có API Key, mạng lỗi, hoặc timeout, Agent tự động tổng hợp kết luận dựa trên Rule-based Quantitative Engine mà không làm gián đoạn hệ thống.

---

## 2. Tiêu Chí Nghiệm Thu

- [ ] Lớp `MarketRegimeAgent` xử lý đầu vào từ `NormalizedOptionUniverse`, giá spot, và dữ liệu biến động lịch sử.
- [ ] Tính toán chính xác các enum: `VolRegime`, `TrendRegime`, `TermStructureRegime`, `SkewRegime`.
- [ ] Trả về `MarketRegimeReport` có cấu trúc đầy đủ, kèm danh sách chiến lược được khuyến nghị (`recommended_strategies`) và danh sách chiến lược nên tránh (`avoid_strategies`).
- [ ] Cơ chế gọi LLM qua `httpx` (Gemini API) hoạt động mượt mà khi có key, và tự động fallback về định lượng khi mock error / thiếu key.
- [ ] Toàn bộ unit tests đạt 100% pass xanh.
