# Bybit Private WebSocket cho Position Monitoring

**Status:** research-only; chưa sửa code
**Ngày:** 2026-09-17
**Phạm vi:** Bybit V5 private stream cho position, order và execution; REST bootstrap/reconcile; acceptance implications cho Position Monitoring. Chỉ sử dụng tài liệu chính thức của Bybit.

## 1. Kết luận điều hành

Position Monitoring nên dùng hai lớp:

```text
REST bootstrap/reconcile  ← nguồn khôi phục và kiểm chứng state
            ↑
Private WebSocket          ← fast path cho event gần real-time
            ↓
Database raw events + normalized projections
            ↓
Risk/Exit Decision Engine (read-only trước, cần human confirmation)
```

Các điểm phải coi là contract của implementation:

1. Private WebSocket endpoint là `wss://stream.bybit.com/v5/private` cho mainnet và `wss://stream-testnet.bybit.com/v5/private` cho testnet. Private topics cần authenticate trước khi subscribe. [Bybit — Connect](https://bybit-exchange.github.io/docs/v5/ws/connect)
2. Ba topic chính là `position`, `order`, `execution`; mỗi topic có all-in-one và categorised variants. Với workspace options, nên ưu tiên `position.option`, `order.option`, `execution.option` để giảm noise. [Bybit — Position](https://bybit-exchange.github.io/docs/v5/websocket/private/position), [Bybit — Order](https://bybit-exchange.github.io/docs/v5/websocket/private/order), [Bybit — Execution](https://bybit-exchange.github.io/docs/v5/websocket/private/execution)
3. Các trang private stream mô tả việc nhận **thay đổi** và trả `data[]`; chúng không định nghĩa một initial snapshot hoặc contract `type=snapshot/delta` như public orderbook/ticker. Đây là cơ sở để suy ra rằng WebSocket private không được dùng làm nguồn bootstrap duy nhất; implementation phải gọi REST. [Bybit — Position](https://bybit-exchange.github.io/docs/v5/websocket/private/position), [Bybit — Order](https://bybit-exchange.github.io/docs/v5/websocket/private/order), [Bybit — Execution](https://bybit-exchange.github.io/docs/v5/websocket/private/execution), [Bybit — Public orderbook snapshot/delta](https://bybit-exchange.github.io/docs/v5/websocket/public/orderbook)
4. Mất kết nối là tình huống bình thường cần xử lý: gửi ping mỗi 20 giây, reconnect sớm và sau reconnect phải authenticate + subscribe lại. [Bybit — Connect](https://bybit-exchange.github.io/docs/v5/ws/connect)
5. HTTP acknowledgement không đủ để kết luận order đã filled/cancelled. Order stream có race giữa cancel và fill; execution stream có thể chứa nhiều executions cho một order. [Bybit — Order](https://bybit-exchange.github.io/docs/v5/websocket/private/order), [Bybit — Execution](https://bybit-exchange.github.io/docs/v5/websocket/private/execution)

Các kết luận về database schema, buffer event trong reconnect, điều kiện `UNKNOWN/RECONCILE_REQUIRED` và thứ tự xử lý là **internal design inference** từ các API fact trên, không phải trading rule do Bybit quy định.

## 2. Private topics và dữ liệu nhận được

| Domain | Topic all-in-one | Topic theo category | Ý nghĩa | Khóa projection đề xuất |
| --- | --- | --- | --- | --- |
| Position | `position` | `position.linear`, `position.inverse`, `position.option` | Thay đổi position gần real-time | `account + category + symbol + positionIdx` |
| Order | `order` | `order.spot`, `order.linear`, `order.inverse`, `order.option` | Thay đổi order gần real-time | `account + category + orderId` |
| Execution | `execution` | `execution.spot`, `execution.linear`, `execution.inverse`, `execution.option` | Các execution/fill gần real-time | `account + category + execId` |

Bybit không cho dùng all-in-one và categorised topic của cùng một domain trong cùng một subscription request. All-in-one của position bao phủ linear/inverse/option; all-in-one của order và execution còn bao phủ spot. [Bybit — Position](https://bybit-exchange.github.io/docs/v5/websocket/private/position), [Bybit — Order](https://bybit-exchange.github.io/docs/v5/websocket/private/order), [Bybit — Execution](https://bybit-exchange.github.io/docs/v5/websocket/private/execution)

### 2.1. Position

Topic position cung cấp các field quan trọng cho tracker và risk monitor: `category`, `symbol`, `side`, `size`, `positionIdx`, `positionValue`, `entryPrice`, `markPrice`, `leverage`, margin, `liqPrice`, `takeProfit`, `stopLoss`, `trailingStop`, `unrealisedPnl`, `curRealisedPnl`, `cumRealisedPnl`, `positionStatus`, `isReduceOnly`, `updatedTime` và `seq`. Với option position còn có `delta`, `gamma`, `vega`, `theta`. `positionIdx` phân biệt one-way/hedge mode. [Bybit — Position](https://bybit-exchange.github.io/docs/v5/websocket/private/position)

Hai nuance bắt buộc:

- `side` có thể là chuỗi rỗng khi position rỗng; không được coi mọi message là position đang mở. [Bybit — Position](https://bybit-exchange.github.io/docs/v5/websocket/private/position)
- Bybit nói mỗi lần create/amend/cancel order đều có thể tạo một position message, kể cả khi position thực tế không đổi. Consumer phải so sánh state/`updatedTime`/`seq` trước khi phát lại notification hoặc chạy exit decision. [Bybit — Position](https://bybit-exchange.github.io/docs/v5/websocket/private/position)

`seq` là cross sequence để liên kết fill và position update; Bybit cảnh báo các symbol khác nhau có thể có cùng `seq`, vì vậy key so sánh phải là `seq + symbol`, không phải chỉ `seq`. [Bybit — Position](https://bybit-exchange.github.io/docs/v5/websocket/private/position)

### 2.2. Order

Topic order cung cấp state/order transition gồm `category`, `orderId`, `orderLinkId`, `parentOrderLinkId`, `symbol`, `price`, `qty`, `side`, `positionIdx`, `orderStatus`, `cancelType`, `rejectReason`, `avgPrice`, `leavesQty`, `leavesValue`, `cumExecQty`, `cumExecValue`, fee, `closedPnl`, TP/SL/trigger fields và timestamps. `parentOrderLinkId` cần được giữ để nối các order TP/SL khi broker cung cấp nó. [Bybit — Order](https://bybit-exchange.github.io/docs/v5/websocket/private/order)

Bybit cảnh báo race cụ thể: có thể nhận hai message `orderStatus=Filled` khi cancel request được accept đồng thời với việc order được execute. Một message phản ánh execution thành công; message còn lại phản ánh cancel bị reject vì order đã execute. Vì vậy không được chuyển sang `CANCELLED` chỉ từ một acknowledgement/cancel event mà chưa kiểm tra terminal broker state và executions. [Bybit — Order](https://bybit-exchange.github.io/docs/v5/websocket/private/order)

### 2.3. Execution

Topic execution là fill-level stream, có `orderId`, `orderLinkId`, `execId`, `execPrice`, `execQty`, `execValue`, `execFee`, `execPnl`, `closedSize`, `execTime`, fee currency, option IV/mark/index/underlying price và `seq`. Một message có thể chứa nhiều execution cho cùng một order. [Bybit — Execution](https://bybit-exchange.github.io/docs/v5/websocket/private/execution)

`execId` là khóa idempotency chính cho execution. `seq` dùng để liên kết với position update; khi cần kiểm tra uniqueness cross-symbol thì dùng `seq + symbol` theo hướng dẫn của Bybit. Execution phải được lưu như immutable append-only fact, không được coi là current order state. [Bybit — Execution](https://bybit-exchange.github.io/docs/v5/websocket/private/execution)

## 3. Authentication, subscribe, heartbeat và reconnect

### 3.1. Authentication

Private connection phải authenticate khi thiết lập kết nối và trước khi subscribe private topics. Message có dạng:

```json
{
  "op": "auth",
  "args": ["api_key", 1662350400000, "signature"]
}
```

Trong ví dụ HMAC của Bybit, `expires` phải lớn hơn current timestamp và signature được tạo từ chuỗi `GET/realtime{expires}` bằng API secret. Authentication thành công trả `success: true`, `op: "auth"` và `conn_id`. [Bybit — Connect](https://bybit-exchange.github.io/docs/v5/ws/connect)

**Acceptance implication:** API secret chỉ được dùng ở server-side connector. Đây là security inference trực tiếp từ việc signature cần API secret; browser không được nhận secret hoặc tự ký private WebSocket request.

### 3.2. Subscribe/unsubscribe

Sau auth, subscribe bằng:

```json
{
  "op": "subscribe",
  "args": ["position.option", "order.option", "execution.option"]
}
```

Có thể unsubscribe động bằng `op=unsubscribe` và cùng tên topic trong `args`. Bybit trả subscription response với `success`, `op`, `conn_id` và tùy trường hợp `req_id`. Consumer phải coi subscription chỉ thành công khi đã xác nhận response, không chỉ khi WebSocket ở trạng thái OPEN. [Bybit — Connect](https://bybit-exchange.github.io/docs/v5/ws/connect)

Nếu một subscription request bị reject một phần, implementation nên ghi rõ topic nào failed, không đánh dấu cả connector là healthy. Khi triển khai lần đầu, có thể gửi từng domain một request để lỗi position/order/execution được cô lập dễ hơn.

### 3.3. Heartbeat và thời gian sống

Bybit khuyến nghị gửi packet ping mỗi 20 giây:

```json
{"req_id":"heartbeat-1","op":"ping"}
```

Private pong có `op: "pong"`, timestamp trong `args` và `conn_id`. Nếu không có ping-pong và không có stream data, connection có thể bị cắt sau 10 phút. Có thể đặt `max_active_time` từ 30 giây đến 600 giây trên private stream; đây không thay thế heartbeat định kỳ. [Bybit — Connect](https://bybit-exchange.github.io/docs/v5/ws/connect)

**Acceptance implication:** health monitor cần ít nhất `last_pong_at`, `last_event_at`, `last_subscribe_ack_at`, `reconnect_count`, `connection_state` và `stale_reason`. `last_event_at` không được dùng một mình vì không có position/order event vẫn có thể là trạng thái hợp lệ.

### 3.4. Reconnect và giới hạn

Bybit yêu cầu client reconnect sớm khi disconnect và không nên liên tục connect/disconnect. Giới hạn được công bố là không vượt quá 500 connections trong 5 phút trên mỗi WebSocket domain. [Bybit — Connect](https://bybit-exchange.github.io/docs/v5/ws/connect)

**Acceptance implication:** reconnect phải có exponential backoff với jitter, giới hạn retry, và sau mỗi connection mới phải chạy lại auth + subscribe. Không tạo một WebSocket mới cho từng symbol hoặc từng position; dùng một private connection theo account/environment nếu phù hợp.

## 4. Snapshot-vs-delta semantics

### 4.1. Điều Bybit thực sự công bố

Các private docs cho position/order/execution có chung hình dạng `id`, `topic`, `creationTime`, `data[]`, và mô tả là stream để nhận “changes” hoặc executions real-time. Những trang này không công bố field `type` là `snapshot` hoặc `delta`, cũng không mô tả một initial private snapshot gửi ngay sau subscribe. [Bybit — Position](https://bybit-exchange.github.io/docs/v5/websocket/private/position), [Bybit — Order](https://bybit-exchange.github.io/docs/v5/websocket/private/order), [Bybit — Execution](https://bybit-exchange.github.io/docs/v5/websocket/private/execution)

Ngược lại, Bybit mô tả rõ snapshot/delta cho public orderbook: subscribe nhận snapshot, sau đó nhận delta; snapshot mới phải reset local book. Đây là contract riêng của public orderbook và không nên suy rộng sang private position/order/execution. [Bybit — Public orderbook](https://bybit-exchange.github.io/docs/v5/websocket/public/orderbook)

### 4.2. Projection contract đề xuất

Phần dưới là **internal design inference**, được chọn vì private docs không cung cấp snapshot/delta contract đầy đủ:

- **Position:** upsert theo `account + category + symbol + positionIdx`; lưu raw payload trước khi normalize. So sánh các field quan trọng và `seq`/`updatedTime` để bỏ qua event không tạo ra thay đổi có ý nghĩa. `size=0` hoặc side rỗng phải biểu diễn position không còn mở, không xóa audit event.
- **Order:** upsert current projection theo `account + category + orderId`; giữ toàn bộ raw updates để xử lý race. Không patch tùy tiện như public orderbook; field absent/không applicable phải được phân biệt với “giá trị cũ chưa đổi” cho tới khi có contract test của category đó.
- **Execution:** append-only theo `execId`; không merge execution vào một bản ghi cũ và không cộng fill lần hai khi event được replay sau reconnect.
- **Decision input:** chỉ đánh dấu broker state là `fresh` sau khi connector authenticated/subscribed và dữ liệu đã được bootstrap/reconcile. WebSocket event đơn lẻ không phải snapshot account hoàn chỉnh.

### 4.3. Thứ tự và duplicate

`creationTime` là thời điểm Bybit tạo message, không phải bằng chứng rằng các message đến client theo thứ tự toàn cục. `seq` có thể liên kết execution và position update nhưng không unique toàn hệ thống vì symbol khác nhau có thể dùng cùng sequence. [Bybit — Position](https://bybit-exchange.github.io/docs/v5/websocket/private/position), [Bybit — Execution](https://bybit-exchange.github.io/docs/v5/websocket/private/execution)

Do đó:

1. Dedupe execution bằng `execId`.
2. Dedupe hoặc monotonic-check position theo symbol + position index + `seq`/`updatedTime`.
3. Order transition phải cho phép duplicate `Filled` và giải quyết theo execution/REST terminal state.
4. Không đánh dấu `HOLD` khi sequence/state đang mâu thuẫn hoặc connector có gap chưa reconcile.

## 5. REST bootstrap và reconciliation

### 5.1. Position snapshot

`GET /v5/position/list` yêu cầu `category` là `linear`, `inverse` hoặc `option`. Có thể lọc bằng `symbol`, `settleCoin`; `baseCoin` áp dụng cho option. Có cursor phân trang. Với inverse, Bybit ghi rõ không query nhiều symbol trong một request; trong biến động cực mạnh endpoint có thể latency hoặc delay. [Bybit — Get Position Info](https://bybit-exchange.github.io/docs/v5/position)

Đây là bootstrap source cho current position: size, side, average entry, mark price, liquidation price, margin, TP/SL, unrealised/realised PnL, position status, reduce-only state và Greeks category-appropriate. REST snapshot vẫn cần timestamp/freshness và không nên coi là tức thời tuyệt đối trong biến động lớn. [Bybit — Get Position Info](https://bybit-exchange.github.io/docs/v5/position)

### 5.2. Open orders và recent closed orders

`GET /v5/order/realtime` chủ yếu dùng cho order chưa fill hoặc partial fill; `openOnly=0` là active orders. Endpoint cũng hỗ trợ tối đa 500 closed records gần nhất tùy category, nhưng Bybit cảnh báo sau server release/restart các closed Unified orders phải lấy từ order history. [Bybit — Get Open & Closed Orders](https://bybit-exchange.github.io/docs/v5/order/open-order)

**Acceptance implication:** không được xem `/v5/order/realtime?openOnly=1` là order ledger đầy đủ. Nó là một phần current view và cần history để phục hồi.

### 5.3. Order history

`GET /v5/order/history` dùng để query order history, có cursor và limit tối đa 50. Bybit ghi rõ dữ liệu có thể delay vì create/cancel là asynchronous. Quy tắc retention được phân vùng: closed status trong 7 ngày, cancelled/rejected/deactivated trong 24 giờ, và beyond 7 ngày chỉ còn các order có fills. [Bybit — Get Order History](https://bybit-exchange.github.io/docs/v5/order/order-list)

**Acceptance implication:** reconciliation sau reconnect phải có overlap window và không chỉ dựa vào một lần query history mặc định. Cần lưu `last_reconcile_at` và cursor đã xử lý để tránh mất event ở biên thời gian.

### 5.4. Execution history

`GET /v5/execution/list` trả execution records theo `execTime` giảm dần, có cursor và limit tối đa 100. Nếu không truyền time range, mặc định query 7 ngày; khoảng `startTime`/`endTime` tối đa là 7 ngày. Bybit cũng nhắc một order có thể có nhiều execution và các record có cùng `execTime` có vấn đề sorting; nên dùng `execId + OrderId + leavesQty` để sort/tie-break. [Bybit — Get Trade History](https://bybit-exchange.github.io/docs/v5/order/execution)

### 5.5. Rate limit

Bybit công bố limit 50 requests/second cho `/v5/position/list`, `/v5/order/realtime`, `/v5/order/history` và `/v5/execution/list` trong bảng rate limit V5. Đây là trần API, không phải tần suất polling nên dùng mặc định. Implementation vẫn cần backoff, jitter và tránh gọi REST mỗi UI repaint. [Bybit — Rate Limit Rules](https://bybit-exchange.github.io/docs/v5/rate-limit)

### 5.6. Reconciliation algorithm đề xuất

Đây là **internal design inference**:

1. **Startup:** mở private WebSocket, auth, subscribe và bắt đầu buffer event; đồng thời gọi REST position, open orders, order history và execution history với overlap window.
2. **Baseline:** tạo normalized projection từ REST snapshot; không coi WebSocket message trước baseline là duplicate nếu chưa kiểm tra key/sequence.
3. **Replay buffer:** áp dụng event đã buffer theo domain; dedupe execution bằng `execId`, order bằng `orderId` + version/fingerprint, position bằng key + monotonic sequence/time.
4. **Steady state:** xử lý WebSocket fast path; ghi raw event trước projection để không mất audit khi normalizer lỗi.
5. **Reconnect:** reconnect + auth + subscribe ngay, buffer event mới, chạy lại REST với overlap từ thời điểm trước disconnect, sau đó replay/merge.
6. **Periodic reconcile:** định kỳ so sánh broker projection với database; tần suất cấu hình theo category/account, không dùng heartbeat như một REST polling trigger.
7. **Anomaly:** nếu REST lỗi, stream stale, subscription chưa ack, sequence/state conflict, broker-only order hoặc position/local mismatch thì trạng thái dữ liệu là `RECONCILE_REQUIRED`/`UNKNOWN`, không được biến thành `HOLD` bình thường.

### 5.7. So sánh ngắn gọn WebSocket và REST

| Tiêu chí | Private WebSocket | REST |
| --- | --- | --- |
| Mục đích | Fast path cho thay đổi gần real-time | Bootstrap, kiểm chứng, recovery |
| Initial snapshot | Không được private docs cam kết | Có current position/open order/history responses |
| Order fill | Có event, có thể nhiều execution/message | History để replay, có pagination/retention |
| Disconnect recovery | Không tự phục hồi state | Query lại bằng overlap window |
| Duplicate/race | Có thể có duplicate/race | Có delay/asynchronous/retention caveat |
| Freshness | Cần health + last event/pong | Cần request timestamp + latency + source status |
| Database | Raw append-only events + projection | Snapshot/reconcile evidence |

## 6. Database và audit implications

Chưa triển khai database trong research này. Acceptance cho implementation nên yêu cầu tối thiểu các logical records sau:

### 6.1. Raw private events

Lưu `account_id`, environment, `topic`, category, symbol nếu có, message `id`, `creationTime`, received time, `seq` nếu có, event key, raw JSON, payload hash và processing status. Có unique constraint phù hợp để retry không tạo duplicate.

### 6.2. Current projections

- `positions`: current normalized position theo `category + symbol + positionIdx`, kèm `as_of`, `source`, `seq`, `updated_time`, data freshness và raw event reference.
- `orders`: current normalized order theo `category + orderId`, kèm status, cum/leaves quantity, fill average, TP/SL mapping, terminal evidence và raw event reference.
- `executions`: immutable fills theo `category + execId`, kèm order ID, exec price/qty/value/fee/PnL/time/seq.

### 6.3. Reconciliation/audit

Lưu run ID, trigger (`startup`, `reconnect`, `periodic`, `manual`), REST endpoints đã gọi, time window/cursor, counts, anomalies, projection corrections và completion status. Exit decision cần tham chiếu `position_snapshot_id`, `data_health_id` và reconciliation result để người dùng biết quyết định dựa trên dữ liệu nào.

**Security implication:** không lưu API secret vào database, raw log hoặc browser payload. UI chỉ nhận projection và health state đã được server-side connector sanitize. Đây là internal security requirement, không phải field requirement của Bybit.

## 7. Acceptance implications cho Position Monitoring

### P0 — Connector và dữ liệu

- **AUTH-001:** connector dùng đúng mainnet/testnet private URL, gửi auth trước subscribe, xác minh `success=true` và giữ `conn_id`.
- **AUTH-002:** API secret không xuất hiện trong browser, HTTP response, database raw event hoặc log.
- **SUB-001:** connector subscribe đúng topic theo category; không trộn all-in-one và categorised của cùng domain trong một request.
- **SUB-002:** chỉ hiển thị trạng thái `LIVE` sau auth và từng subscription cần thiết đã được ack.
- **WS-001:** ping định kỳ 20 giây; ghi nhận pong; phát `STALE` khi không còn health evidence trong SLA.
- **WS-002:** disconnect phải reconnect với backoff/jitter, auth lại và subscribe lại; không tạo connection loop vượt giới hạn.

### P0 — Semantics và idempotency

- **SEM-001:** không chờ một private snapshot giả định để khởi tạo account state; UI phải dùng REST bootstrap.
- **SEM-002:** position event do create/amend/cancel order nhưng không đổi position không được tạo duplicate decision/notification.
- **SEM-003:** execution message chứa nhiều fills phải lưu đủ từng fill.
- **SEM-004:** cùng `execId` từ replay/retry chỉ tạo một execution record và không cộng PnL/size lần hai.
- **SEM-005:** position `size=0`/side rỗng chuyển projection về flat nhưng vẫn giữ raw event và audit.
- **SEM-006:** order cancel-vs-fill race không được kết luận `CANCELLED` chỉ từ cancel acknowledgement; phải reconcile với execution/order/position terminal evidence.
- **SEM-007:** mọi so sánh sequence cross-symbol dùng `seq + symbol`, không dùng `seq` đơn độc.

### P0 — REST bootstrap/reconcile

- **REC-001:** startup có current positions từ `/v5/position/list`, active orders từ `/v5/order/realtime`, và lịch sử order/execution với pagination.
- **REC-002:** reconnect chạy overlap reconciliation để bù event trong khoảng disconnect; retry không tạo duplicate.
- **REC-003:** sau server restart không phụ thuộc vào recent-500 closed orders; dùng `/v5/order/history` cho recovery.
- **REC-004:** nếu REST snapshot lỗi, partial hoặc mâu thuẫn với stream, trạng thái phải là `RECONCILE_REQUIRED`/`UNKNOWN`, không phải `HOLD`.
- **REC-005:** lưu source timestamp, receive timestamp, latency, cursor/time window và kết quả reconcile.

### P1 — UI và exit decision

- **UI-001:** dropdown/filter category hiển thị option, linear, inverse theo account capability; không bắt người dùng nhập symbol để xem toàn bộ position nếu Bybit hỗ trợ query theo base/settle/category.
- **UI-002:** một dòng position hiển thị rõ `LIVE / STALE / RECONCILE_REQUIRED`, `as_of`, source và last update; empty state khác với disconnected state.
- **EXIT-001:** `HOLD` chỉ hợp lệ khi data fresh, broker/local matched, position status usable và protection/risk checks pass.
- **EXIT-002:** dữ liệu thiếu hoặc stream chưa reconcile chỉ được tạo `REVIEW`/`UNKNOWN`, không được AI suy diễn thành hold.
- **EXIT-003:** decision phải hiển thị reason codes, source time, position/order IDs, policy version và cần human confirmation; research này không authorize automatic close.

## 8. Proposed implementation slices

Đây là backlog đề xuất, chưa triển khai:

1. **WS-INGEST:** server-side private connector, auth, topic subscription, heartbeat, reconnect và health state.
2. **WS-NORMALIZE:** parser cho position/order/execution, raw event store, category-aware keys và idempotency.
3. **REST-BOOTSTRAP:** position/open order/history/execution bootstrap với cursor, time windows và rate-aware backoff.
4. **RECONCILE:** reconnect/periodic reconcile, overlap replay, sequence/race handling và anomaly states.
5. **DB-PROJECTION:** current positions/orders, immutable executions, raw events và audit/reconcile runs.
6. **UI-MONITOR:** dropdown filters, one-click refresh/reconnect, freshness banner và action-first CLOSE/HOLD/REVIEW presentation.
7. **EXIT-GUARD:** deterministic risk gates trước AI; read-only decision và human confirmation.

## 9. Nguồn chính thức

- [WebSocket Connect — endpoints, authentication, heartbeat, subscribe/unsubscribe, reconnect limits](https://bybit-exchange.github.io/docs/v5/ws/connect)
- [Private Position Stream — topics, position fields, `seq`, position update behavior](https://bybit-exchange.github.io/docs/v5/websocket/private/position)
- [Private Order Stream — topics, order fields, cancel/fill race](https://bybit-exchange.github.io/docs/v5/websocket/private/order)
- [Private Execution Stream — topics, fill fields, multi-execution message, `execId`/`seq`](https://bybit-exchange.github.io/docs/v5/websocket/private/execution)
- [Get Position Info — `GET /v5/position/list`](https://bybit-exchange.github.io/docs/v5/position)
- [Get Open & Closed Orders — `GET /v5/order/realtime`](https://bybit-exchange.github.io/docs/v5/order/open-order)
- [Get Order History — `GET /v5/order/history`](https://bybit-exchange.github.io/docs/v5/order/order-list)
- [Get Trade History — `GET /v5/execution/list`](https://bybit-exchange.github.io/docs/v5/order/execution)
- [Rate Limit Rules](https://bybit-exchange.github.io/docs/v5/rate-limit)
- [Public Orderbook — explicit snapshot/delta semantics used for contrast](https://bybit-exchange.github.io/docs/v5/websocket/public/orderbook)

