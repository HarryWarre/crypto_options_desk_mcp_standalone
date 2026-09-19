# SWARM-001.2: Specialized Trader Swarm & Multi-Strategy Candidate Pool

**Mã Sub-Issue:** SWARM-001.2  
**Master Issue:** [SWARM-001](swarm-001-multi-agent-trading-swarm-and-visual-desk.md)  
**Trạng thái:** To Do  
**Target:** `main`  
**File cần thêm/sửa:**
- `src/options_lib/swarm/trader_pool.py` (Mới)
- `src/options_lib/swarm/__init__.py` (Mới)
- `tests/test_trader_pool.py` (Mới)

---

## 1. Mô Tả Chi Tiết

Nâng cấp điều phối từ đơn bot sang Swarm gồm 6 Trader Agents đại diện cho 6 trường phái chiến lược:
1. `IronCondorTrader`: Bán biên độ hai đầu khi High IV & Range-bound.
2. `WheelTrader`: Bán CSP Delta 0.2-0.3 khi Sideway/Bullish & IVR cao.
3. `VerticalSpreadTrader`: Đánh xu hướng directional credit spread khi Bullish/Bearish.
4. `IronButterflyTrader`: Đánh găm chốt ATM khi IV - RV cao và thị trường không biến động mạnh.
5. `CalendarSpreadTrader`: Khai thác chênh lệch kỳ hạn khi RV thấp (<=55%) và Spot tích lũy gần SMA20.
6. `LongVolTrader`: Mua biến động khi IV rẻ hơn RV (IV Discount).

Mỗi chu kỳ, căn cứ vào `MarketRegimeReport` từ Research Agent, các Trader phù hợp sẽ quét và phát sinh `CandidateSignal` gửi về bể tín hiệu chung (Candidate Pool).
