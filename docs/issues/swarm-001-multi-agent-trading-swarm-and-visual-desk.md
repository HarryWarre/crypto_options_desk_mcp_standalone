# SWARM-001: Master Issue — Multi-Agent Options Trading Swarm & ATSMatrix Visual Desk

**Mã Issue:** SWARM-001  
**Tiêu đề:** Xây dựng Hệ thống Giao dịch Phái sinh Đa Đại nhân (5-Stage Multi-Agent Swarm) & Giao diện Canvas Trực quan ATSMatrix  
**Trạng thái:** In Progress  
**Target:** `main`  
**Liên kết tham chiếu:**
- [BOT-000 Master Roadmap](bot-000-multi-strategy-options-roadmap.md)
- [DESK-001 Live Desk Bot Manager](desk-001-bot-manager-and-stream.md)
- [BOT-011 Deribit Testnet Adapter](bot-011-deribit-testnet-paper-trading-integration.md)
- [ATSMatrix Visualizer Reference](https://github.com/anyel1to/atsmatrix-agent-visualizeR--ANYEL1TO)

---

## 1. Bối Cảnh & Mục Tiêu

Hệ thống Flowsurface hiện tại đã có 6 thuật toán bot options độc lập và adapter Deribit Testnet, tuy nhiên:
1. `BotManager` chỉ chạy duy nhất 1 bot `IronCondorBot` đơn lẻ trên tài khoản ảo SQLite local, chưa đưa thông tin thực tế từ Deribit Testnet lên.
2. Thiếu quy trình phân tầng chuyên nghiệp: Research -> Traders -> Risk -> Verdict -> Execution.
3. Backtest và bot đang fix cứng $Qty = 1.0$, chưa có Risk Engine cân đối tỷ trọng danh mục và margin.
4. Giao diện Live Desk là các bảng số liệu truyền thống, chưa thể hiện được luồng trao đổi đa đại nhân (Multi-Agent Swarm).

**Mục tiêu của SWARM-001:**
- Triển khai toàn bộ quy trình 5 tầng:
  1. **Research Agent (Market Regime)**: Phân tích Bull/Bear, Volatility High/Low, Skew, Term Structure (Hybrid Định lượng + LLM Gemini kèm Fallback an toàn).
  2. **Trader Agents (6 Bot Strategies)**: 6 Trader chuyên biệt chạy song song, tạo ứng viên lệnh theo Regime.
  3. **Risk Management Engine**: Mô hình quản trị rủi ro danh mục phái sinh chuẩn công nghiệp (Dynamic Sizing theo % Equity, Margin Budget, Greeks Exposure Limits).
  4. **Verdict Agent**: Phán quyết tự động (Full Autonomous Swarm Auto-Approve / Reject) dựa trên quy chuẩn rủi ro toàn cục.
  5. **Deribit Testnet Execution & Telemetry**: Đồng bộ số dư thực tế, margin, PnL, và lịch sử tài sản 1D / 1W / 1M.
- Chuyển đổi giao diện Live Desk sang **ATSMatrix Neural Canvas Visualizer**: Đồ họa node tương tác, truyền hạt dữ liệu (pulse packets), telemetry terminal và side drawer chi tiết.

---

## 2. Danh Sách Các Sub-Issues

1. **[SWARM-001.1: Market Regime Research Agent (Hybrid Quantitative & LLM Engine with Fallback)](swarm-001-1-market-regime-research-agent.md)**
   - Xây dựng module nhận định thị trường đa chiều: Định lượng (RV, IV-RV, Term Structure, Trend) kết hợp LLM Reasoning (Gemini) với fallback 100% tự động.
2. **[SWARM-001.2: Specialized Trader Swarm & Multi-Strategy Candidate Pool](swarm-001-2-specialized-trader-swarm-engine.md)**
   - Nâng cấp `BotManager` điều phối 6 Trader Agents đồng thời, kích hoạt chiến lược phù hợp dựa trên Market Regime.
3. **[SWARM-001.3: Industry-Standard Options Risk Engine & Dynamic Position Sizing](swarm-001-3-industry-standard-options-risk-engine.md)**
   - Triển khai mô hình định cỡ vị thế và kiểm soát Margin/Greeks danh mục, thay thế cho fix cứng $Qty = 1$.
4. **[SWARM-001.4: Verdict Agent & Deribit Testnet Telemetry Sync](swarm-001-4-verdict-agent-and-deribit-telemetry.md)**
   - Phán quyết tự động, bridge API Deribit Testnet thật (Equity, Margin, Orders) và lưu timeseries cho chart 1D/1W/1M.
5. **[SWARM-001.5: ATSMatrix Interactive Neural Canvas UI & Telemetry Terminal](swarm-001-5-atsmatrix-neural-canvas-live-desk.md)**
   - Thay thế UI bot cũ bằng Canvas đồ họa tương tác mô phỏng dòng va chạm tín hiệu giữa các Agent, telemetry stream và chart hiệu suất.
