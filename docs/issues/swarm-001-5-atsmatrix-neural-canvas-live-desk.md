# SWARM-001.5: ATSMatrix Interactive Neural Canvas UI & Telemetry Terminal

**Mã Sub-Issue:** SWARM-001.5  
**Master Issue:** [SWARM-001](swarm-001-multi-agent-trading-swarm-and-visual-desk.md)  
**Trạng thái:** Completed (Commit `0b99492`)  
**Target:** `main`  
**File cần thêm/sửa:**
- `src/options_app/static/atsmatrix-canvas.js` (Mới)
- `src/options_app/static/live-desk.js` (Cập nhật)
- `src/options_app/static/index.html` (Cập nhật)
- `src/options_app/static/styles.css` (Cập nhật)

---

## 1. Mô Tả Chi Tiết

Thay thế toàn bộ khu vực Bot UI cũ bằng giao diện đồ họa **ATSMatrix Canvas Visualizer**:
1. **Interactive Neural Canvas:**
   - Vẽ mạng lưới tương tác giữa các Agent: `Research Agent` -> `6 Trader Bots` -> `Risk Manager` -> `Verdict Agent` -> `Deribit Broker`.
   - Các gói hạt năng lượng (Pulse Particles) bắn qua lại giữa các node khi chu kỳ đánh giá chạy và khi lệnh được khớp.
2. **Side-Drawer Node Inspector:**
   - Click vào bất kỳ node nào sẽ mở thanh trượt chi tiết hiển thị: vai trò, tham số, reasoning luận điểm, và trạng thái hiện tại.
3. **Live Telemetry Terminal:**
   - Cửa sổ terminal phong cách Cyberpunk bên dưới ghi nhận log trao đổi giữa các Agent trong Swarm.
4. **Deribit Portfolio Performance Chart:**
   - Biểu đồ tài sản tương tác có bộ lọc mốc thời gian: 1 Ngày (1D), 1 Tuần (1W), 1 Tháng (1M).
