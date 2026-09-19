# BOT-010: Long Volatility Straddle & Strangle Bot (Catalyst & Vol Expansion)

**Status:** backlog  
**Branch:** `feat/bot-010-long-volatility-straddle-strangle-engine`  
**Target:** `main`  
**Blueprint Reference:** [iron_condor_bot.py](file:///Users/hoangviet/Flowsurface/crypto_options_desk_mcp/src/options_lib/strategy/iron_condor_bot.py), [iron_condor_backtest.py](file:///Users/hoangviet/Flowsurface/crypto_options_desk_mcp/src/options_lib/strategy/iron_condor_backtest.py)

---

## 1. Problem & Context
Các bot hiện tại (Iron Condor, Vertical Spreads, Iron Butterfly, The Wheel) đều là các chiến lược **Short Volatility (Bán biến động / Thu phí bảo hiểm)**. Khi thị trường xuất hiện các sự kiện đột biến vĩ mô (Macro Catalyst) như công bố CPI, cuộc họp FOMC, phán quyết ETF, hoặc sự kiện Halving, các chiến lược Short Vol dễ bị quá tải rủi ro.

**Long Straddle / Strangle** là đối trọng phòng hộ hoàn hảo:
1. **Long Straddle (Mua ATM Call + Mua ATM Put):** Rủi ro cố định bằng số tiền mua (Net Debit), lợi nhuận tiềm năng không giới hạn ở cả 2 đầu khi giá bứt phá cực mạnh.
2. **Long Strangle (Mua OTM Call + Mua OTM Put):** Chi phí vốn rẻ hơn đáng kể so với Straddle, nhắm đến những cú bùng nổ biên độ lớn (Black Swan / High-Impact Breakout).
3. **Mục tiêu chính:** Bắt trọn sự tăng vọt đồng thời của Biến động ngầm định (Vega Expansion) và Gia tốc bước giá (Gamma Runner).

---

## 2. Target Strategy Specs (Long Straddle & Strangle)

- **Tài sản hỗ trợ:** BTC, ETH, SOL
- **Chế độ giao dịch:** Paper Trading (`PaperBroker`) và Bybit V5 Live
- **Tenor:** 7 – 21 DTE (Đủ thời gian chờ đợi sự kiện bùng nổ mà không bị hao mòn Theta quá nhanh)
- **Cấu hình lựa chọn hợp đồng:**
  - **Long Straddle:** Mua Call và Put tại Strike ATM (Delta $\approx \pm 0.50$, cùng Expiry).
  - **Long Strangle:** Mua Call OTM (Delta $+0.25$ đến $+0.35$) và Mua Put OTM (Delta $-0.25$ đến $-0.35$).
- **Bộ lọc kích hoạt (Catalyst & Cheap Volatility Screener):**
  - **Compressed IV:** IV Rank hoặc IV Percentile $< 20\%$ (Biến động đang bị định giá cực rẻ sau chu kỳ nén dài).
  - **Bollinger Bands Squeeze:** Độ rộng dải Bollinger co cụm về mức đáy 30 ngày.
  - **Lịch sự kiện vĩ mô:** Tích hợp bộ đếm ngược thời gian trước các sự kiện lớn (FOMC, CPI...).
- **Quy tắc Quản trị Vị thế & Chốt lời Bất đối xứng (Asymmetric Lifecycle):**
  - **Partial Profit Taking:** Khi một trong hai chân đạt lợi nhuận $+80\%$ đến $+100\%$, tự động chốt lời $50\%$ khối lượng để thu hồi toàn bộ vốn gốc ban đầu (Free Roll).
  - **Trailing Stop trên phần còn lại:** Kích hoạt Trailing Stop trên chân thắng để gồng hết biên độ sóng tăng/giảm cực mạnh.
  - **Time-Decay Stop Loss:** Nếu sau 3 – 5 ngày mở lệnh mà thị trường vẫn không bứt phá và IV không tăng, chủ động cắt vị thế khi tổng giá trị sụt giảm $20\% – $30\%$ để tránh bị Theta bào mòn đến kiệt quệ.

---

## 3. Sub-tasks / Child Issues

- [ ] **BOT-010A: Compressed Volatility & Catalyst Screener**
  - Quét IV Rank, IV Percentile đa tài sản.
  - Tích hợp logic nhận diện nén biên độ (Volatility Squeeze Indicator) từ dữ liệu nến K-line và options chain.

- [ ] **BOT-010B: Straddle / Strangle Strike Selector**
  - Tích hợp template `long_straddle` và `long_strangle` từ `builder.py`.
  - Tính toán điểm hòa vốn kép (Upper / Lower Breakevens) và yêu cầu biến động tối thiểu để sinh lời.

- [ ] **BOT-010C: Net Debit Execution & Slippage Guard**
  - Đặt lệnh mua cả 2 chân qua Limit Order có kiểm soát trượt giá gắt gao.
  - Đảm bảo trượt giá thực thi không làm tăng chi phí vốn ròng quá 3%.

- [ ] **BOT-010D: Asymmetric Profit-Taking & Trailing Stop Engine**
  - Xây dựng module theo dõi riêng biệt từng chân (Leg-level tracking).
  - Thực thi tự động logic chốt lời bảo toàn vốn và trailing gồng lãi chân chiến thắng.
  - Kích hoạt quy tắc Time-Stop thoát trước khi bước vào 3 ngày cuối trước đáo hạn.

- [ ] **BOT-010E: Event-Driven Historical Parquet Backtester**
  - Xây dựng `LongVolBacktestEngine` trong `src/options_lib/strategy/long_vol_backtest.py`.
  - Replay qua các sự kiện biến động lớn trong lịch sử crypto (các cú sập giá, halving, ETF approvals).
  - Thống kê tỷ lệ Reward/Risk trung bình và kỳ vọng lợi nhuận trên mỗi trade.

- [ ] **BOT-010F: Unit Tests & Portfolio Risk Hedging Metric**
  - Tạo `tests/test_long_vol_bot.py` và `tests/test_long_vol_backtest.py`.
  - Kiểm tra tác động của bot Long Vol như một công cụ bảo hiểm danh mục cho các bot Short Vol khác (Portfolio Hedging).

---

## 4. Acceptance Criteria
1. Module `long_vol_bot.py` hỗ trợ đầy đủ Straddle và Strangle.
2. Bộ lọc chỉ kích hoạt mở vị thế khi IV ở vùng đáy hoặc có tín hiệu nén biến động rõ rệt.
3. Engine backtest chứng minh khả năng phòng vệ danh mục khi thị trường sụt giảm hoặc bứt phá đột ngột.
4. Đạt 100% tỷ lệ pass các test case về khớp lệnh 2 chân debit và chốt lời từng phần.

