# Nghiên cứu kho mã nguồn mở cho lớp head chọn chiến lược

Ngày kiểm tra: 2026-09-17

## Kết luận ngắn

Chưa tìm thấy một kho mã nguồn mở có sẵn đúng toàn bộ luồng:

```text
lớp head học máy chọn chiến lược
→ bộ quét quyền chọn tiền điện tử
→ signal để người dùng tự giao dịch
```

Hướng phù hợp nhất là đưa một thư viện học máy nhỏ vào lớp head, giữ nguyên
bộ quét và cách định giá hiện tại.

## Xếp hạng lựa chọn

### 1. LightGBM — lựa chọn nên dùng cho phiên bản đầu

Kho mã nguồn: [lightgbm-org/LightGBM](https://github.com/lightgbm-org/LightGBM)

- Có sẵn cách học để xếp hạng và phân loại lựa chọn.
- Có thể chạy trên dữ liệu dạng bảng, phù hợp với thông tin thị trường và kết
  quả của từng chiến lược.
- Giấy phép MIT.
- Không có sẵn logic quyền chọn, dữ liệu Bybit hoặc bộ tạo signal; phần cần
  thêm chỉ là bộ nối mỏng cho lớp head và quy trình tạo dữ liệu học.

Đây là lựa chọn thực tế nhất nếu hệ thống sẽ huấn luyện định kỳ từ dữ liệu quá
khứ. Lớp head nhận trạng thái thị trường và chấm điểm từng chiến lược, sau đó
trả về một hoặc vài chiến lược tốt nhất, hoặc trả về không giao dịch.

Nguồn: [README và giấy phép chính thức của LightGBM](https://github.com/lightgbm-org/LightGBM/blob/main/README.md).

### 2. MABWiser — phù hợp nếu muốn học theo kết quả mới liên tục

Kho mã nguồn: [fidelity/mabwiser](https://github.com/fidelity/mabwiser)

MABWiser là thư viện Python cho việc chọn một quyết định dựa trên bối cảnh
hiện tại và phần thưởng nhận được sau quyết định. Thư viện có sẵn cách huấn
luyện, dự đoán, mô phỏng và kiểm tra nhiều cách chọn. Giấy phép Apache 2.0.

Áp dụng vào hệ thống này theo suy luận kiến trúc:

- Mỗi chiến lược là một lựa chọn.
- Trạng thái thị trường là bối cảnh.
- Kết quả sau chi phí của signal là phần thưởng.

Kho này không hiểu quyền chọn và không biết Bybit. Ngoài ra, cách học này có
thể cần thử các lựa chọn mới; vì vậy không nên cho nó tự giao dịch thật.

Nguồn: [README chính thức của MABWiser](https://github.com/fidelity/mabwiser) và
[tài liệu chính thức](https://fidelity.github.io/mabwiser/).

### 3. CORP — gần lĩnh vực quyền chọn tiền điện tử nhất

Kho mã nguồn: [signorloops/crypto-options-research-platform](https://github.com/signorloops/crypto-options-research-platform)

Kho này có dữ liệu quyền chọn tiền điện tử, định giá, quản lý rủi ro, tín hiệu,
chiến lược và kiểm tra quá khứ. README cũng nêu các cách dùng XGBoost và PPO
trong nhóm chiến lược. Giấy phép MIT.

Điểm hạn chế là kho tập trung vào Deribit và OKX, chủ yếu cho tạo lập thị
trường và giao dịch chênh lệch. Nó không có sẵn head chọn chiến lược đúng theo
luồng của repo hiện tại và không phải phần cắm vào trực tiếp cho Bybit.

Nên dùng làm tài liệu tham khảo cho cách tổ chức dữ liệu và kiểm tra quá khứ,
không nên đưa cả kho vào sản phẩm hiện tại.

Nguồn: [README chính thức của CORP](https://github.com/signorloops/crypto-options-research-platform).

### 4. NautilusTrader — nền tảng kiểm tra quá khứ và chạy chiến lược

Kho mã nguồn: [nautechsystems/nautilus_trader](https://github.com/nautechsystems/nautilus_trader)

NautilusTrader có hỗ trợ trực tiếp cho quyền chọn, chuỗi quyền chọn, dữ liệu
Bybit và kiểm tra quá khứ; chiến lược có thể viết bằng Python. Kho cũng nêu
khả năng huấn luyện tác nhân học máy. Giấy phép LGPL 3.0.

Đây là nền tảng lớn, không phải head chọn chiến lược. Repo hiện tại đã có
NautilusTrader ở nhóm phụ thuộc dành cho kiểm tra quá khứ, nên chỉ nên dùng
thêm khi cần thay hoặc mở rộng bộ chạy kiểm tra quá khứ.

Nguồn: [README chính thức](https://github.com/nautechsystems/nautilus_trader),
[tài liệu quyền chọn](https://github.com/nautechsystems/nautilus_trader/blob/develop/docs/concepts/options.md).

### 5. FinRL-Trading — tham khảo cách chia lớp

Kho mã nguồn: [AI4Finance-Foundation/FinRL-Trading](https://github.com/AI4Finance-Foundation/FinRL-Trading)

Kho này có cách chia riêng phần dữ liệu, chiến lược, kiểm tra quá khứ và thực
hiện giao dịch; có phần chọn cổ phiếu bằng học máy. Giấy phép Apache 2.0.

Tuy nhiên, phần dữ liệu và ví dụ chính là cổ phiếu, không phải quyền chọn tiền
điện tử. Nó phù hợp để tham khảo cách tổ chức lớp head và kiểm tra theo thời
gian, không phù hợp để đưa nguyên kho vào repo.

Nguồn: [README chính thức của FinRL-Trading](https://github.com/AI4Finance-Foundation/FinRL-Trading)
và [tài liệu phần chọn bằng học máy](https://github.com/AI4Finance-Foundation/FinRL-Trading/blob/master/ML_STOCK_SELECTION.md).

### 6. Bayesian ETF Option Strategy Selection Framework — tham khảo gần nhất về
lựa chọn cấu trúc quyền chọn

Kho mã nguồn:
[jainishm06/Bayesian_ETF_Option_Strategy_Selection_Framework](https://github.com/jainishm06/Bayesian_ETF_Option_Strategy_Selection_Framework)

Kho này có luồng từ tín hiệu thị trường đến chọn cấu trúc quyền chọn và kiểm
tra theo từng giai đoạn. Nó hỗ trợ các cấu trúc như mua quyền chọn mua, mua
quyền chọn bán và chênh lệch giá.

Nhưng kho chỉ tập trung vào quỹ ETF, dùng cách định giá gần đúng và README
nêu rõ chưa chạy lại đầy đủ giá mua bán lịch sử của chuỗi quyền chọn. Trang kho
không hiện giấy phép rõ ràng. Chỉ nên đọc để tham khảo, không nên dùng làm phụ
thuộc sản phẩm nếu chưa kiểm tra giấy phép với tác giả.

Nguồn: [README chính thức của kho](https://github.com/jainishm06/Bayesian_ETF_Option_Strategy_Selection_Framework).

## Cách ghép vào repo hiện tại

Repo hiện tại đã có sẵn trường danh sách chiến lược trong `ScanRequest` và bộ
quét dùng danh sách đó để chạy các chiến lược được chọn:

- [ScanRequest](../src/options_lib/opportunity_scanner.py)
- [scan_opportunities](../src/options_lib/opportunity_scanner.py)

Vì vậy luồng mới có thể là:

```text
dữ liệu thị trường
→ head chấm điểm các chiến lược
→ lấy danh sách chiến lược được chọn
→ truyền vào ScanRequest.strategies
→ scan_opportunities tìm hợp đồng và tạo signal
→ người dùng xem và tự quyết định giao dịch
```

Head không được gọi lệnh, không tự chọn một hợp đồng cụ thể và không thay đổi
cách định giá. Bộ quét vẫn chịu trách nhiệm kiểm tra giá, chi phí, thanh khoản,
rủi ro và lý do loại bỏ.

## Đề xuất triển khai

1. Dùng LightGBM cho head đầu tiên, theo kiểu chấm điểm từng chiến lược từ dữ
   liệu quá khứ.
2. Thêm lựa chọn `không giao dịch` để head không bị ép phải chọn một chiến
   lược.
3. Ở mỗi thời điểm quá khứ, cho tất cả chiến lược chạy qua bộ quét; lấy kết
   quả sau chi phí làm cơ sở chấm điểm.
4. Chia dữ liệu theo thứ tự thời gian, không trộn tương lai vào quá khứ.
5. Chỉ đưa phiên bản head vào chạy thật nếu kết quả trên giai đoạn chưa từng
   dùng tốt hơn cách chọn thủ công.
6. Chỉ cân nhắc MABWiser sau này nếu muốn head cập nhật dần theo kết quả signal
   thực tế.

