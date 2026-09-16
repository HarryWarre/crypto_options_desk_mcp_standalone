# Task: Nâng cấp volatility surface bằng SVI/SSVI

## Prompt giao cho conversation mới

> Cải thiện volatility surface của dự án crypto options scanner. Bản hiện tại
> dùng nội suy xác định trên log-moneyness và total variance. Hãy nghiên cứu,
> triển khai và kiểm định SVI/SSVI trên dữ liệu lịch sử theo từng snapshot,
> giữ nguyên khả năng fallback về mô hình MVP khi dữ liệu thưa hoặc fitting
> thất bại. Không được tuyên bố mô hình tốt hơn nếu chưa có kiểm định ngoài
> mẫu. Đọc task này trước khi sửa code, kiểm tra thay đổi đang có trong
> working tree và không ghi đè thay đổi của người dùng.

## Bối cảnh hiện tại

- Repository: `crypto_options_desk_mcp`.
- Surface MVP: `src/options_lib/volatility_surface.py`.
- Fair value dùng surface: `src/options_lib/pricing/fair_value.py`.
- Scanner dùng surface để định giá: `src/options_lib/opportunity_scanner.py`.
- API surface summary: `GET /api/v1/surfaces/{asset}` trong
  `src/options_app/api.py`.
- Test hiện tại: `tests/test_volatility_surface.py`,
  `tests/test_fair_value.py`, `tests/test_opportunity_scanner.py`.
- Dữ liệu lịch sử dự kiến có thể lấy từ ChainVector theo snapshot `as_of`.
  Phải lưu rõ `source`, `venue`, `as_of` và không trộn dữ liệu Bybit với
  Deribit trong cùng một phép đánh giá.

## Mục tiêu

Tạo một lớp surface có thể chọn phương pháp:

```text
baseline     -> nội suy MVP hiện tại
svi          -> SVI theo từng kỳ hạn
ssvi         -> SSVI có ràng buộc giữa các kỳ hạn
auto         -> ưu tiên SSVI/SVI, fallback baseline với lý do rõ ràng
```

Mặc định của hệ thống hiện tại phải tiếp tục là `baseline` cho đến khi có
đủ bằng chứng lịch sử rằng phương pháp mới ổn định hơn.

## Phạm vi bắt buộc

1. Thiết kế interface fitting độc lập với adapter dữ liệu. Không để API
   hoặc Bybit adapter biết chi tiết công thức SVI/SSVI.
2. Fit theo log-moneyness và total variance, có trọng số theo liquidity hoặc
   chất lượng báo giá.
3. Kiểm tra đầu vào và kết quả:
   - IV/variance hữu hạn và không âm.
   - Không dùng điểm đã hết hạn.
   - Không cho fitting thất bại biến thành fair value im lặng.
   - Gắn trạng thái `observed`, `fitted`, `interpolated`, `extrapolated`,
     `fit_failed` hoặc tương đương.
4. Có fallback rõ ràng khi một kỳ hạn thiếu điểm, dữ liệu lỗi hoặc optimizer
   không hội tụ.
5. Trả diagnostics cho từng kỳ hạn:
   - số điểm dùng để fit;
   - RMSE IV và sai số lớn nhất;
   - trạng thái hội tụ;
   - số vi phạm variance âm hoặc điều kiện kiểm tra arbitrage;
   - cảnh báo dữ liệu thưa/extrapolation.
6. Tích hợp vào `VolatilitySurface.quote()` mà không làm hỏng API public hiện
   tại. Fair value và opportunity scanner phải nhận được phương pháp surface
   qua cấu hình, không hardcode trong scanner.
7. Tạo bộ đánh giá lịch sử theo thời gian:
   - chia train/test theo thời gian, không random split;
   - snapshot trước dùng để fit, snapshot sau dùng để đánh giá;
   - so sánh baseline với SVI/SSVI;
   - đo IV RMSE, giá quyền chọn MAE, coverage, fit failure rate và arbitrage
     violations;
   - báo cáo độ nhạy khi loại bỏ thanh khoản thấp và khi thêm phí/trượt giá.

## Acceptance criteria

- `pytest` hiện tại vẫn pass.
- Có test dữ liệu thưa, duplicate, missing quote, expiry không theo thứ tự,
  smile phẳng, smile méo và điểm ngoại suy.
- Có test optimizer không hội tụ và xác nhận fallback không im lặng.
- Có test chứng minh không có look-ahead trong đánh giá lịch sử.
- Có fixture nhỏ cho ít nhất hai kỳ hạn và hai tài sản.
- API summary hiển thị phương pháp surface, trạng thái fit và diagnostics.
- Opportunity scanner không dùng kết quả `fit_failed` làm cơ hội hợp lệ.
- Không bật SVI/SSVI mặc định trong production nếu chưa có báo cáo so sánh
  ngoài mẫu.
- Có tài liệu giải thích đơn giản SVI/SSVI, giả định, giới hạn và cách đọc
  diagnostics.

## Không làm trong task này

- Không đặt lệnh hoặc kết nối tài khoản riêng.
- Không khẳng định SVI/SSVI tạo ra EV dương.
- Không tối ưu danh mục nhiều tài sản.
- Không thêm machine learning hoặc mô hình stochastic volatility khác.
- Không xóa baseline surface đang chạy ổn định.

## Đề xuất chia sub-issue

- `SURF-001`: Chốt interface và schema diagnostics cho surface fitter.
- `SURF-002`: Implement SVI theo từng expiry + unit tests.
- `SURF-003`: Implement SSVI/liên kết giữa expiry + arbitrage checks.
- `SURF-004`: Tích hợp quote/fair value/scanner với cấu hình phương pháp.
- `SURF-005`: Adapter và loader dữ liệu snapshot lịch sử.
- `SURF-006`: Backtest so sánh baseline/SVI/SSVI ngoài mẫu.
- `SURF-007`: API/UI diagnostics, tài liệu và defect-first review.

## Kết quả cần bàn giao

1. Code và test có thể chạy lại bằng một lệnh.
2. Báo cáo so sánh baseline/SVI/SSVI trên cùng dữ liệu và cùng thời điểm.
3. Danh sách snapshot, khoảng thời gian, tài sản, venue và giả định phí.
4. Kết luận rõ: phương pháp nào được bật, phương pháp nào chỉ nghiên cứu,
   và các trường hợp phải fallback.
