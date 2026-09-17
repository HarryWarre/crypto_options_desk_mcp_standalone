# Order, Position/PnL và Risk/Exit Decision — Research

**Status:** research-only; chưa triển khai code production
**Ngày:** 2026-09-17
**Phạm vi:** Bybit V5, ưu tiên options/perpetuals/inverse contracts vì phù hợp workspace hiện tại; SEC/FINRA/NIST chỉ được dùng làm nguyên tắc tham chiếu cho risk-control, supervision và audit. Đây không phải tư vấn pháp lý hay khuyến nghị đầu tư.

## 1. Kết luận điều hành

Khoảng trống hiện tại không chỉ là thiếu màn hình theo dõi. Sau khi user đặt lệnh thủ công, hệ thống cần một lớp stateful với broker/exchange là nguồn sự thật cuối cùng:

```text
Valuation / Signal
        ↓ (read-only intent / signal snapshot)
Order Execution
        ↓ (manual order, broker ack, fills)
Position Tracker
        ↓ (size, entry, PnL, Greeks, margin, exits)
Risk Monitor
        ↓ (hard limits + data/operational health)
Exit Decision Engine
        ↓ (CLOSE_FULL / CLOSE_PARTIAL / HOLD / REPAIR_PROTECTION / UNKNOWN)
Order Closing
        ↓ (reduce-only close + broker confirmation)
Reconciliation + Audit Log
```

Ba nguyên tắc quan trọng:

1. **Broker/exchange state thắng local state.** HTTP acknowledgement chỉ chứng minh request được chấp nhận; Bybit ghi rõ cancel request là asynchronous và cần WebSocket để xác nhận status cuối cùng. [Bybit — Cancel Order](https://bybit-exchange.github.io/docs/v5/order/cancel-order)
2. **Fills tạo ra position; order intent không tạo ra position.** Execution stream cung cấp `execId`, `execPrice`, `execQty`, `leavesQty`, fee, PnL của từng execution và `closedSize`; một order có thể có nhiều execution trong cùng message. [Bybit — Execution stream](https://bybit-exchange.github.io/docs/v5/websocket/private/execution)
3. **HOLD chỉ là kết quả có điều kiện, không phải mặc định.** Nếu thiếu dữ liệu, mất đồng bộ, protective exit không được xác nhận, position gần liquidation hoặc broker state không rõ, engine phải trả về trạng thái an toàn như `UNKNOWN`/`REPAIR_PROTECTION`, không tự diễn giải là “tiếp tục hold”. Đây là đề xuất thiết kế suy ra từ các yêu cầu về pre-trade controls, post-trade reports và auditability trong [SEC Rule 15c3-5](https://www.sec.gov/files/faq-15c-5-risk-management-controls-bd.htm) và các trạng thái/risk fields mà Bybit công bố trong [Get Position Info](https://bybit-exchange.github.io/docs/v5/position).

## 2. Phân biệt fact từ nguồn và đề xuất nội bộ

| Nhóm | Ý nghĩa trong tài liệu này |
| --- | --- |
| **API fact** | Hành vi, field, lifecycle hoặc giới hạn được mô tả trong tài liệu chính thức của Bybit/SEC/FINRA/NIST. |
| **Inference** | Kết luận kiến trúc trực tiếp suy ra từ một hoặc nhiều API fact, ví dụ cần event stream + periodic reconciliation. |
| **Internal policy proposal** | Ngưỡng, reason code, ưu tiên hành động và điều kiện HOLD/CLOSE cần product owner định nghĩa; không phải quy tắc giao dịch phổ quát. |

Các ngưỡng như `max_position_notional`, `max_loss_pct`, `stale_after_ms`, `min_liquidation_buffer`, `max_holding_time` và ngưỡng Greeks phải là cấu hình versioned theo account, category, strategy và symbol; không nên hard-code từ research này.

## 3. Order lifecycle và reconciliation

### 3.1. Lifecycle tối thiểu cần biểu diễn

Bybit định nghĩa các order status mở gồm `New`, `PartiallyFilled`, `Untriggered`; status đóng gồm `Rejected`, `PartiallyFilledCanceled`, `Filled`, `Cancelled`, `Triggered` và `Deactivated` tùy loại order/category. [Bybit — Enums: orderStatus](https://bybit-exchange.github.io/docs/v5/enum)

API place order trả về `orderId` và `orderLinkId`, nhưng việc có ID không đồng nghĩa order đã filled. Order stream mới phản ánh các thay đổi như `orderStatus`, `cumExecQty`, `cumExecValue`, `avgPrice`, `leavesQty`, `closedPnl`, `reduceOnly`, `closeOnTrigger`, TP/SL và timestamps. [Bybit — Place Order](https://bybit-exchange.github.io/docs/v5/order/create-order), [Bybit — Private Order stream](https://bybit-exchange.github.io/docs/v5/websocket/private/order)

Execution stream phải là nguồn fill-level để tính position: mỗi execution có `execId`, `orderId`, `orderLinkId`, `execPrice`, `execQty`, `execValue`, `execFee`, `execPnl`, `closedSize`, `execTime` và `seq`; `seq + symbol` nên được dùng khi cần định danh duy nhất theo hướng dẫn của Bybit. [Bybit — Execution stream](https://bybit-exchange.github.io/docs/v5/websocket/private/execution)

Order stream có race condition cần xử lý: Bybit cảnh báo có thể nhận hai message `Filled` khi cancel được chấp nhận gần đồng thời với execution; message thứ nhất phản ánh execution, message thứ hai phản ánh cancel bị reject vì order đã execute. Vì vậy không được coi event “cancel accepted/requested” là terminal cancellation. [Bybit — Private Order stream](https://bybit-exchange.github.io/docs/v5/websocket/private/order)

### 3.2. Event-driven không đủ để phục hồi state

Private WebSocket yêu cầu authentication, heartbeat và reconnect khi disconnect; Bybit khuyến nghị gửi ping mỗi 20 giây và reconnect sớm nếu mất kết nối. [Bybit — WebSocket Connect](https://bybit-exchange.github.io/docs/v5/ws/connect)

Vì vậy, **inference kiến trúc** là dùng hai lớp:

- **Fast path:** consume private `order`, `execution`, `position`, và options `greeks` streams để cập nhật nhanh.
- **Recovery path:** sau startup, reconnect, heartbeat gap, sequence anomaly, API error, timeout hoặc nghi ngờ mất event, gọi REST snapshots và history để dựng lại state.

Bybit nói `/v5/order/realtime` chủ yếu dùng cho unfilled/partially filled orders và chỉ giữ tối đa 500 closed records gần nhất; sau server release/restart, closed orders cần lấy từ order history. Vì thế reconciliation không được giới hạn trong “open orders hiện tại”. [Bybit — Get Open & Closed Orders](https://bybit-exchange.github.io/docs/v5/order/open-order), [Bybit — Get Order History](https://bybit-exchange.github.io/docs/v5/order/order-list)

### 3.3. Mô hình local state đề xuất

Đây là **internal policy proposal** dựa trên các field/order events nói trên:

```text
LOCAL_INTENT      → user đã ghi nhận signal/order dự kiến
SUBMITTED         → đã gửi request, chưa có broker outcome cuối
ACKED             → broker trả ID/request accepted; chưa phải fill
OPEN              → broker New/Untriggered
PARTIALLY_FILLED  → cumExecQty > 0 và còn leavesQty
FILLED            → broker Filled / leavesQty = 0
CANCEL_PENDING    → cancel request accepted, chờ terminal event
CANCELLED         → broker terminal cancel
REJECTED          → broker reject
UNKNOWN           → không thể chứng minh state từ broker
RECONCILE_ERROR   → broker/local fields mâu thuẫn hoặc snapshot không đầy đủ
```

Một order record nên giữ tối thiểu: `account_id`, `category`, `symbol`, `position_idx`, `order_id`, `order_link_id`, `parent_order_link_id`, requested side/type/qty/price, `cum_exec_qty`, `leaves_qty`, average fill, fee currency/amount, broker status, `created_time`, `updated_time`, last event ID/sequence, source, received time và raw payload hash. Việc giữ type/when/source/outcome/identity phù hợp với hướng dẫn audit record content của [NIST SP 800-53 Rev. 5](https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-53r5.pdf), đặc biệt các control family Audit and Accountability (`AU-2`, `AU-3`, `AU-8`, `AU-11`, `AU-12`).

### 3.4. Reconciliation algorithm đề xuất

Reconciler chạy khi startup, định kỳ và sau các trigger bất thường. Đây là **inference**, không phải endpoint requirement riêng của Bybit:

1. Lấy broker open orders theo category/symbol/account; lấy order history theo cursor cho khoảng thời gian có thể chứa event bị mất; lấy current positions; với options lấy closed option positions khi cần.
2. Dedupe event bằng `execId` cho fills; với order update dùng `(orderId, updatedTime, payload/version)` hoặc một fingerprint tương đương. Không cộng lại execution khi replay WebSocket hoặc REST.
3. Join local với broker ưu tiên `orderId`, sau đó `orderLinkId`; nếu hai ID conflict thì theo Bybit, `orderId` được ưu tiên khi cancel. [Bybit — Cancel Order](https://bybit-exchange.github.io/docs/v5/order/cancel-order)
4. So sánh immutable intent và mutable execution state: side/category/symbol/position index/qty/price/type, status, cumulative fill, leaves, average fill, fees, TP/SL và timestamps.
5. Áp dụng monotonic terminal transition: terminal broker state không bị một event cũ ghi đè; chỉ cho phép sửa bằng reconciliation có audit trail.
6. Gắn kết quả: `MATCHED`, `LOCAL_ONLY`, `BROKER_ONLY`, `DIVERGED`, `STALE_SOURCE`, `UNKNOWN`. `BROKER_ONLY` không tự động được coi là user-owned intent; nên adopt thành `UNASSIGNED/FOREIGN` và khóa mở position mới cho tới khi user xác nhận.
7. Nếu position broker khác với projection local, position broker là operational truth; rebuild local position từ fills/snapshot rồi ghi discrepancy để điều tra.

Các tình huống phải phát cảnh báo và không cho engine trả `HOLD` bình thường: local order chưa thấy broker sau timeout; broker order/position không có local mapping; `cumExecQty`, `leavesQty`, status hoặc avg price lệch; sequence gap; WebSocket stale; hoặc snapshot REST bị lỗi/không đủ.

## 4. Position, PnL và exposure

### 4.1. Position snapshot

`/v5/position/list` trả real-time position data gồm `positionIdx`, side, size, avg price, position value, mark price, break-even price, leverage, initial/maintenance margin, liquidation price, TP/SL/trailing stop, unrealised PnL, current/cumulative realised PnL, position status và `isReduceOnly`. Bybit cũng cảnh báo position interface có thể tăng latency hoặc tạm chậm trong biến động cực mạnh. [Bybit — Get Position Info](https://bybit-exchange.github.io/docs/v5/position)

Private position stream đẩy update khi position thay đổi; message có `seq`, nhưng Bybit cũng ghi rõ việc create/amend/cancel order có thể tạo position message dù position thực tế không đổi. Consumer vì vậy phải so sánh field trước khi phát signal, không coi mỗi message là position change có ý nghĩa. [Bybit — Private Position stream](https://bybit-exchange.github.io/docs/v5/websocket/private/position)

### 4.2. PnL cho perps/inverse và options không giống nhau

Đối với linear/inverse, Bybit cung cấp current `unrealisedPnl`, `curRealisedPnl`, `cumRealisedPnl`, và endpoint closed PnL có `closedSize`, average entry/exit, `closedPnl`, open/close fee và fill count. [Bybit — Get Position Info](https://bybit-exchange.github.io/docs/v5/position), [Bybit — Get Closed PnL](https://bybit-exchange.github.io/docs/v5/position/close-pnl)

Đối với options, Bybit ghi trong position endpoint rằng `cumRealisedPnl` là empty/meaningless; closed option positions phải lấy từ endpoint riêng, trả `avgEntryPrice`, `avgExitPrice`, `totalOpenFee`, `totalCloseFee`, `deliveryFee`, `deliveryPrice`, `openTime`, `closeTime` và `totalPnl`, hiện chỉ hỗ trợ dữ liệu sáu tháng gần nhất. [Bybit — Get Position Info](https://bybit-exchange.github.io/docs/v5/position), [Bybit — Get Closed Options Positions](https://bybit-exchange.github.io/docs/v5/position/close-position)

Do đó position tracker không nên tự đặt tên một field tổng quát là `realized_pnl` rồi gán mọi category vào đó. **Internal policy proposal:** dùng typed PnL components:

```text
unrealized_pnl         ← broker mark-based live estimate
realized_pnl_current   ← category-specific current-holding field
closed_pnl             ← closed trade/position record
open_fees
close_fees
delivery_or_settlement
funding_or_other_cashflow (nếu category hỗ trợ)
net_pnl                ← explicit formula + source fields, không đoán khi thiếu
```

Mark price, last price, bid/ask và underlying price là các snapshot khác nhau. Ticker API của Bybit phân biệt chúng và options ticker còn có mark IV, underlying price, open interest, delta, gamma, vega, theta. [Bybit — Get Tickers](https://bybit-exchange.github.io/docs/v5/market/tickers)

### 4.3. Greeks và risk exposure

Options position tracker cần lưu Greeks theo từng leg khi có thể, đồng thời lấy portfolio totals từ private `greeks` stream (`totalDelta`, `totalGamma`, `totalVega`, `totalTheta`). [Bybit — Private Greek stream](https://bybit-exchange.github.io/docs/v5/websocket/private/greek)

**Internal policy proposal:** risk monitor nên tính ít nhất gross notional, net notional, net delta, gamma/vega/theta, margin used, distance to liquidation, concentration theo underlying/expiry/strategy, và exposure sau khi tính các pending fills. Không được dùng `unrealised_pnl` đơn độc để kết luận nên hold; PnL phải đi cùng liquidity, risk limit, protection coverage, time-to-expiry và thesis state.

## 5. Protective exits và order closing

### 5.1. Protective exits là state phải reconcile

Bybit `Set Trading Stop` hỗ trợ take profit, stop loss và trailing stop; request tạo conditional orders internally, hệ thống hủy các order này khi position đóng và điều chỉnh quantity theo position size. API hỗ trợ full-position và partial-position TP/SL; full mode chỉ hỗ trợ market order khi trigger, còn partial mode có thể dùng market/limit theo field tương ứng. [Bybit — Set Trading Stop](https://bybit-exchange.github.io/docs/v5/position/trading-stop)

Mỗi position cần có protection coverage rõ ràng: `expected_protection_qty`, `confirmed_tp`, `confirmed_sl`, trigger source (`LastPrice`, `MarkPrice`, `IndexPrice`), order IDs/parent relation, last broker confirmation và coverage ratio. Bybit hỗ trợ `parentOrderLinkId` cho attached TP/SL trong order stream, nhưng có nuance: sửa một phía có thể làm mất paired binding; set TP/SL mới cho position vốn chưa có attached order khiến `parentOrderLinkId` không có ý nghĩa. [Bybit — Private Order stream](https://bybit-exchange.github.io/docs/v5/websocket/private/order)

**Internal policy proposal:** sau khi position được tạo hoặc tăng size, nếu protection chưa được broker xác nhận trong SLA cấu hình thì trạng thái không phải `HOLD`; phải là `REPAIR_PROTECTION` hoặc `PROTECTION_MISSING`, đồng thời không cho tăng position. Không tự coi một local stop intent là stop đã hoạt động.

### 5.2. Đóng position an toàn

Bybit mô tả `reduceOnly=true` là order chỉ được phép giảm position; field này hợp lệ cho linear, inverse và option. `closeOnTrigger` là cơ chế closing order có thể chỉ giảm position và được mô tả cho linear/inverse. FAQ của Bybit nói `reduceOnly` là field thực sự quan trọng khi đóng position. [Bybit — Place Order](https://bybit-exchange.github.io/docs/v5/order/create-order), [Bybit — Bybit FAQ](https://bybit-exchange.github.io/docs/faq)

Vì vậy closing workflow đề xuất là:

1. Lock position key để tránh hai close actions cùng lúc.
2. Re-read broker position và active protection orders.
3. Tính close quantity từ broker `size`, không từ local estimate; giữ `positionIdx` đúng với one-way/hedge mode.
4. Gửi closing order với `reduceOnly=true`; dùng `closeOnTrigger` chỉ khi category/strategy yêu cầu và API hỗ trợ.
5. Chờ order/execution/position confirmation; không coi HTTP success là close complete.
6. Reconcile lại position size, fills, fees và closed PnL. Chỉ chuyển `CLOSED` khi broker position size bằng zero hoặc closed-position record/terminal evidence xác nhận đầy đủ.
7. Nếu partial fill, tạo lại protection cho remainder trước khi quyết định bước tiếp theo; nếu cancel/close race, dùng terminal broker event làm truth.

## 6. Risk controls và điều kiện CLOSE/HOLD

### 6.1. Nguyên tắc control tham chiếu

SEC Rule 15c3-5 yêu cầu controls được thiết kế để giới hạn exposure, chặn order vượt pre-set credit/capital thresholds hoặc có vẻ erroneous; SEC FAQ nêu rõ controls cần xử lý cả order manual và order tự động, và phải reject pre-trade thay vì để order vào venue rồi “chase and cancel”. [SEC — Rule 15c3-5 Final Rule](https://www.sec.gov/rules-regulations/2011/06/risk-management-controls-brokers-or-dealers-market-access), [SEC — Rule 15c3-5 FAQ](https://www.sec.gov/files/faq-15c-5-risk-management-controls-bd.htm)

SEC FAQ cũng nêu các ví dụ về price/size parameters, duplicate orders, pre-order regulatory checks, authorized access, immediate post-trade execution reports và regular review. Các yêu cầu này áp dụng trực tiếp cho broker-dealer market access, không tự động biến thành nghĩa vụ pháp lý cho crypto workspace; ở đây chúng là **design reference** cho hệ thống risk-control. [SEC — Rule 15c3-5 FAQ](https://www.sec.gov/files/faq-15c-5-risk-management-controls-bd.htm)

FINRA mô tả algorithmic-trading supervision theo hướng holistic risk assessment, test/deployment controls và phản ứng với risk evolution; FINRA cũng khuyến nghị monitoring đầy đủ marketable order flow, bao gồm activated stop orders và order flow trong tài sản thanh khoản thấp. Đây là tham chiếu supervisory, không phải trading rule cho Bybit. [FINRA — Algorithmic Trading](https://www.finra.org/rules-guidance/key-topics/algorithmic-trading), [FINRA — Customer Order Handling](https://www.finra.org/rules-guidance/guidance/reports/2026-finra-annual-regulatory-oversight-report/best-execution)

NIST SP 800-53 là catalog control có các nhóm Audit and Accountability, Continuous Monitoring, System and Information Integrity; NIST nêu rằng controls là flexible/customizable và cần được áp dụng trong quy trình quản trị rủi ro của tổ chức. Vì vậy audit/reconciliation log nên được coi là một control của trading system, không chỉ là tiện ích debug. [NIST — SP 800-53 Rev. 5 landing page](https://csrc.nist.gov/pubs/sp/800/53/r5/upd1/final), [NIST — Audit and Accountability control list](https://csrc.nist.gov/projects/risk-management/about-rmf/assess-step/assessment-cases-download-page)

### 6.2. Hard risk gates — ưu tiên cao hơn AI

Đây là **internal policy proposal**; các nguồn bên cạnh là cơ sở control/reference, không phải ngưỡng bắt buộc:

- **Data integrity gate:** broker snapshot/stream stale, sequence gap, API error, clock skew, unknown mapping hoặc source disagreement ⇒ `UNKNOWN`/`REPAIR`, không `HOLD` và không mở thêm risk. [Bybit — WebSocket Connect](https://bybit-exchange.github.io/docs/v5/ws/connect), [Bybit — Get Open & Closed Orders](https://bybit-exchange.github.io/docs/v5/order/open-order)
- **Position status gate:** `positionStatus` khác `Normal`, `isReduceOnly=true`, margin/risk-tier changed, hoặc liquidation buffer dưới ngưỡng ⇒ giảm/đóng theo policy và chặn tăng position. Bybit công bố các field này và gợi ý các biện pháp khi position bị đánh dấu reduce-only. [Bybit — Get Position Info](https://bybit-exchange.github.io/docs/v5/position)
- **Protection gate:** position không có stop loss/TP theo policy hoặc coverage nhỏ hơn size ⇒ `REPAIR_PROTECTION`; nếu không thể repair trong SLA thì `CLOSE_FULL`/`CLOSE_PARTIAL` tùy policy.
- **Exposure gate:** vượt max order notional, max position notional, max portfolio delta/vega, max leverage/risk tier, max concentration, max daily loss hoặc max drawdown ⇒ không được tăng risk; nếu hard limit đã breached thì close/reduce theo playbook. Bybit công bố risk limit, maintenance margin và max leverage theo instrument/risk-limit endpoints. [Bybit — Get Instruments Info](https://bybit-exchange.github.io/docs/v5/market/instrument), [Bybit — Get Risk Limit](https://bybit-exchange.github.io/docs/v5/market/risk-limit)
- **Execution gate:** duplicate/erroneous size/price, invalid tick/qty, insufficient liquidity hoặc expected slippage vượt policy ⇒ block/repair order. SEC dùng price/size/duplicate-order checks làm ví dụ về pre-trade erroneous-order controls. [SEC — Rule 15c3-5 FAQ](https://www.sec.gov/files/faq-15c-5-risk-management-controls-bd.htm)
- **Expiry/settlement gate:** với options, time-to-expiry, delivery/settlement risk, theta/vega/liquidity và closed-position/PnL data availability phải được đánh giá trước khi cho HOLD. Ticker và closed option endpoints cung cấp delivery/expiry-related fields cần thiết nhưng không tự quyết định policy. [Bybit — Get Tickers](https://bybit-exchange.github.io/docs/v5/market/tickers), [Bybit — Get Closed Options Positions](https://bybit-exchange.github.io/docs/v5/position/close-position)

### 6.3. Exit Decision Engine contract đề xuất

Engine nên trả một decision có `action`, `reason_codes[]`, `severity`, `as_of`, `data_freshness`, `position_snapshot_id`, `risk_snapshot_id`, `protection_snapshot_id`, policy version và `requires_human_confirmation`. **Internal policy proposal:** action enum nên gồm:

| Action | Khi nào dùng |
| --- | --- |
| `CLOSE_FULL` | Hard stop/risk breach, protection không thể repair, broker position status nguy hiểm, thesis invalid rõ ràng, expiry/settlement không còn chấp nhận được, hoặc user đã yêu cầu đóng. |
| `CLOSE_PARTIAL` | Cần đưa exposure về limit, giảm delta/vega/concentration, chốt một phần theo target, hoặc partial exit giảm risk mà vẫn giữ thesis. |
| `HOLD` | Chỉ khi mọi hard gate pass, broker/local đã matched, data fresh, protection coverage hợp lệ, position bình thường, exposure trong limit và thesis vẫn còn hiệu lực. |
| `REPAIR_PROTECTION` | Position còn mở nhưng TP/SL/trailing stop thiếu, sai quantity, sai trigger source hoặc chưa được broker confirm. |
| `OBSERVE` | Dữ liệu chưa đủ để hành động nhưng chưa chứng minh hard breach; cần polling/reconciliation nhanh hơn và cảnh báo người dùng. |
| `UNKNOWN_BLOCKED` | Không thể xác định broker truth, mapping hoặc PnL/exposure; cấm mở thêm risk và yêu cầu human/operator recovery. |

Không nên đóng chỉ vì PnL đang dương, và cũng không nên hold chỉ vì PnL đang âm. **Inference:** PnL là một input; quyết định phải kết hợp PnL với broker position status, protection, exposure, liquidity, time/expiry và thesis snapshot. Các input này đều có field/stream tương ứng trong [Bybit Position](https://bybit-exchange.github.io/docs/v5/position), [Bybit Execution](https://bybit-exchange.github.io/docs/v5/websocket/private/execution), [Bybit Trading Stop](https://bybit-exchange.github.io/docs/v5/position/trading-stop) và [Bybit Tickers](https://bybit-exchange.github.io/docs/v5/market/tickers).

### 6.4. Rule-following AI

AI chỉ nên là lớp giải thích/ranking trên một deterministic risk policy:

- Nhận một immutable snapshot đã normalize; không được bịa field thiếu, không tự thay source-of-truth, không tự suy ra fill từ order ACK. Điều này bám vào việc Bybit tách order status, execution và position streams. [Bybit — Place Order](https://bybit-exchange.github.io/docs/v5/order/create-order), [Bybit — Execution stream](https://bybit-exchange.github.io/docs/v5/websocket/private/execution)
- Hard gates chạy trước AI và không cho AI override. Nếu `UNKNOWN`, stale, protection missing, liquidation/risk hard breach hoặc reconciliation divergence thì AI chỉ được giải thích safe action, không được biến thành `HOLD`.
- Output bắt buộc có action, reason codes, input timestamps, source IDs, policy version, model/prompt version, uncertainty và `requires_human_confirmation`. Đây là **internal policy proposal**, phù hợp với yêu cầu audit content về event/time/source/outcome/identity của [NIST SP 800-53](https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-53r5.pdf).
- Vì workflow hiện tại đặt lệnh thủ công, giai đoạn đầu nên để AI **read-only**: hiển thị `CLOSE/HOLD/REPAIR/UNKNOWN` và lý do; user xác nhận mới tạo closing intent. Không tự gọi order-closing API trong research phase.
- Nếu user đã xác nhận close, closing adapter vẫn phải enforce `reduceOnly`, quantity từ broker, position index, idempotency key, terminal confirmation và reconciliation; AI không bypass các kiểm tra này. [Bybit — Place Order](https://bybit-exchange.github.io/docs/v5/order/create-order), [Bybit — Cancel Order](https://bybit-exchange.github.io/docs/v5/order/cancel-order)

## 7. Proposed issue slices và acceptance criteria

Đây là backlog đề xuất để chuyển research thành implementation sau này; **research này không triển khai các issue dưới đây**.

### ORD-001 — Canonical order/position domain contract

- Có typed IDs cho account/category/symbol/position index/order ID/order link ID/parent order link ID.
- Phân biệt request accepted, open, partial fill, filled, cancel pending, cancelled, rejected và unknown theo broker status. [Bybit — Enums](https://bybit-exchange.github.io/docs/v5/enum)
- Giữ immutable raw event/payload hash và normalized projection; mỗi transition có timestamp/source/reason.
- Không cho code gọi “closed” chỉ vì REST create/cancel trả success. [Bybit — Cancel Order](https://bybit-exchange.github.io/docs/v5/order/cancel-order)

### ORD-002 — Private event ingestion và idempotency

- Consume order, execution, position và options greeks topics; có authentication, ping/heartbeat, reconnect và health status. [Bybit — WebSocket Connect](https://bybit-exchange.github.io/docs/v5/ws/connect)
- Dedupe `execId`; bảo toàn fill ordering bằng `seq + symbol` khi cần; test multi-fill và cancel-vs-fill race. [Bybit — Execution stream](https://bybit-exchange.github.io/docs/v5/websocket/private/execution), [Bybit — Private Order stream](https://bybit-exchange.github.io/docs/v5/websocket/private/order)
- Có metric event lag, last event time, reconnect count, sequence anomaly và dropped-message suspicion.

### ORD-003 — REST reconciliation và restart recovery

- Startup/reconnect/periodic reconciler lấy open orders, order history, positions và category-specific closed PnL/positions. [Bybit — Open & Closed Orders](https://bybit-exchange.github.io/docs/v5/order/open-order), [Bybit — Order History](https://bybit-exchange.github.io/docs/v5/order/order-list), [Bybit — Position](https://bybit-exchange.github.io/docs/v5/position)
- Test `MATCHED`, `LOCAL_ONLY`, `BROKER_ONLY`, `DIVERGED`, stale và partial snapshot.
- Closed order history không bị giới hạn nhầm vào recent-500 endpoint sau server restart. [Bybit — Open & Closed Orders](https://bybit-exchange.github.io/docs/v5/order/open-order)
- Reconciler có audit record cho mọi auto-adopt, local correction và human resolution.

### POS-001 — Position/PnL tracker

- Position state lấy size/side/avg price/mark price/fees/PnL/margin/liquidation/risk status/TP/SL và Greeks phù hợp category. [Bybit — Position](https://bybit-exchange.github.io/docs/v5/position)
- Linear/inverse và options dùng đúng endpoint closed PnL khác nhau; options không coi `cumRealisedPnl` là số hợp lệ. [Bybit — Closed PnL](https://bybit-exchange.github.io/docs/v5/position/close-pnl), [Bybit — Closed Options Positions](https://bybit-exchange.github.io/docs/v5/position/close-position)
- Có snapshot ID/as-of/freshness và hiển thị rõ mark-based unrealized PnL với closed/realized PnL.

### RISK-001 — Protective-exit monitor

- Ghi nhận TP/SL/trailing stop là broker orders/conditional state, không phải local flag.
- Verify coverage theo actual position size; phát `PROTECTION_MISSING`, `PROTECTION_STALE`, `PROTECTION_QTY_MISMATCH` và `PROTECTION_TRIGGER_MISMATCH`. [Bybit — Set Trading Stop](https://bybit-exchange.github.io/docs/v5/position/trading-stop)
- Test full/partial TP/SL, position close tự hủy protection, amend một phía làm mất binding và parent-order mapping. [Bybit — Private Order stream](https://bybit-exchange.github.io/docs/v5/websocket/private/order)

### RISK-002 — Deterministic risk monitor

- Có configurable hard gates cho stale data, reconciliation mismatch, exposure/notional/leverage/risk tier, margin/liquidation buffer, concentration, daily loss/drawdown, liquidity/slippage và expiry.
- Hard gate chạy trước AI, chặn entry/re-entry khi breached và ghi reason code.
- Có pre-trade duplicate/price/size checks và post-trade execution monitoring theo design reference của SEC. [SEC — Rule 15c3-5 FAQ](https://www.sec.gov/files/faq-15c-5-risk-management-controls-bd.htm)

### EXIT-001 — Read-only Exit Decision Engine

- Trả đúng action enum `CLOSE_FULL`, `CLOSE_PARTIAL`, `HOLD`, `REPAIR_PROTECTION`, `OBSERVE`, `UNKNOWN_BLOCKED`.
- `HOLD` chỉ pass khi broker/local matched, data fresh, protection covered, position normal, exposure trong limit và thesis chưa invalid.
- Mọi decision có reason codes, policy/model version, source timestamps, uncertainty và human-confirmation flag.
- Test không được đóng/hold chỉ dựa vào dấu của một PnL field.

### EXIT-002 — Closing adapter (phase sau)

- Chỉ tạo close order từ broker position snapshot; luôn dùng `reduceOnly=true` khi đóng/reduce position. [Bybit — Place Order](https://bybit-exchange.github.io/docs/v5/order/create-order), [Bybit — Bybit FAQ](https://bybit-exchange.github.io/docs/faq)
- HTTP ack không chuyển state sang `CLOSED`; phải chờ execution/order/position terminal confirmation và reconcile lại. [Bybit — Cancel Order](https://bybit-exchange.github.io/docs/v5/order/cancel-order)
- Xử lý partial fill, cancel-vs-fill race, idempotency, hedge-mode `positionIdx`, fees và closed PnL.
- Giai đoạn đầu yêu cầu human confirmation; tự động đóng chỉ bật khi có policy/kill switch/audit đầy đủ.

## 8. Source register

Các nguồn dưới đây đều là nguồn first-party/primary được dùng trực tiếp trong tài liệu:

- [Bybit V5 Place Order](https://bybit-exchange.github.io/docs/v5/order/create-order)
- [Bybit V5 Cancel Order](https://bybit-exchange.github.io/docs/v5/order/cancel-order)
- [Bybit V5 Get Open & Closed Orders](https://bybit-exchange.github.io/docs/v5/order/open-order)
- [Bybit V5 Get Order History](https://bybit-exchange.github.io/docs/v5/order/order-list)
- [Bybit V5 Enums Definitions](https://bybit-exchange.github.io/docs/v5/enum)
- [Bybit V5 Private Order stream](https://bybit-exchange.github.io/docs/v5/websocket/private/order)
- [Bybit V5 Private Execution stream](https://bybit-exchange.github.io/docs/v5/websocket/private/execution)
- [Bybit V5 Private Position stream](https://bybit-exchange.github.io/docs/v5/websocket/private/position)
- [Bybit V5 Private Greek stream](https://bybit-exchange.github.io/docs/v5/websocket/private/greek)
- [Bybit V5 WebSocket Connect](https://bybit-exchange.github.io/docs/v5/ws/connect)
- [Bybit V5 Get Position Info](https://bybit-exchange.github.io/docs/v5/position)
- [Bybit V5 Get Closed PnL](https://bybit-exchange.github.io/docs/v5/position/close-pnl)
- [Bybit V5 Get Closed Options Positions](https://bybit-exchange.github.io/docs/v5/position/close-position)
- [Bybit V5 Set Trading Stop](https://bybit-exchange.github.io/docs/v5/position/trading-stop)
- [Bybit V5 Get Tickers](https://bybit-exchange.github.io/docs/v5/market/tickers)
- [Bybit V5 Get Instruments Info](https://bybit-exchange.github.io/docs/v5/market/instrument)
- [Bybit V5 Get Risk Limit](https://bybit-exchange.github.io/docs/v5/market/risk-limit)
- [SEC Rule 15c3-5 Final Rule overview](https://www.sec.gov/rules-regulations/2011/06/risk-management-controls-brokers-or-dealers-market-access)
- [SEC Rule 15c3-5 FAQ](https://www.sec.gov/files/faq-15c-5-risk-management-controls-bd.htm)
- [FINRA Algorithmic Trading](https://www.finra.org/rules-guidance/key-topics/algorithmic-trading)
- [FINRA Customer Order Handling / Best Execution](https://www.finra.org/rules-guidance/guidance/reports/2026-finra-annual-regulatory-oversight-report/best-execution)
- [NIST SP 800-53 Rev. 5 landing page](https://csrc.nist.gov/pubs/sp/800/53/r5/upd1/final)
- [NIST SP 800-53 Rev. 5 PDF](https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-53r5.pdf)
