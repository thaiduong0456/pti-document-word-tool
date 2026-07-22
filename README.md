# Tool tạo tờ trình thanh toán phí giám định

Ứng dụng Streamlit đọc ảnh/PDF của một bộ chứng từ bằng PaddleOCR chạy cục bộ, yêu cầu người dùng kiểm tra rồi tạo lại file Word từ một mẫu cố định. Ứng dụng không cần OpenAI API key.

## Nguyên tắc bảo vệ mẫu Word

Ứng dụng **chỉ thay nội dung nằm trong các run được tô vàng (`yellow highlight`)**. Nội dung không tô vàng không được sửa, kể cả khi AI trích xuất được giá trị tương ứng. Các trường chưa có vùng vàng vẫn được hiển thị trong bảng kiểm tra nhưng không được chèn vào Word.

Các vùng vàng hiện được ánh xạ trong `src/word_filler.py`: ngày tờ trình/ngày ký, tên tàu, số B/L, số GCNBH, hàng hóa, ngày giám định, số báo cáo, phí trước VAT, số/ngày hóa đơn, khối lượng B/L, thực nhận, thiếu hụt, tỷ lệ và số bồn.

Quy tắc nguồn bắt buộc: tên tàu và tên hàng lấy nguyên văn từ **Thông báo phí**; cảng/nước xuất phát lấy từ `Loading Port`; khối lượng ở câu mở đầu phải dùng đúng tổng khối lượng theo B/L và đồng nhất với bảng diễn biến bên dưới. Ngày tờ trình và ngày ký lấy ngày người dùng upload/xử lý bộ chứng từ, không lấy ngày hóa đơn.

## Cài đặt

Yêu cầu Python 3.11 trở lên.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Khi triển khai Streamlit Cloud, tạo `.streamlit/secrets.toml`:

```toml
TEMPLATE_DOCX_BASE64 = "..."
```

Khi chạy cục bộ, đặt mẫu tại `templates/template.docx`. Khi deploy repo công khai, mã hóa mẫu bằng `base64` và chỉ lưu giá trị trong Streamlit Secrets.

Không commit `.env`, `secrets.toml`, file Word mẫu hoặc chứng từ thật lên GitHub.

## Chạy

```bash
streamlit run app.py
```

1. Tải toàn bộ ảnh/PDF của một bộ chứng từ.
   - Chọn **một hoặc nhiều file**; hoặc
   - Chọn **cả thư mục** để tải tất cả PDF/ảnh trong thư mục và thư mục con.
2. Ứng dụng tự động xử lý bằng PaddleOCR ngay sau khi tải chứng từ; không cần API key.
3. Kiểm tra bằng chứng, sửa giá trị nếu cần và đánh dấu **Xác nhận**.
4. Chỉ khi các trường bắt buộc dùng trong vùng vàng đã được xác nhận, nút tạo Word mới được mở.
5. Tải Word, JSON hoặc bảng kiểm tra Excel. Bản Word tải xuống được tự động bỏ toàn bộ bôi vàng.

## Kiểm thử

Mã nguồn được kiểm thử cục bộ với các bộ chứng từ hồi quy riêng tư. Chứng từ, fixture chứa dữ liệu thật và file Word mẫu không được đưa lên repository công khai.

Nếu dữ liệu mới dài hơn đáng kể so với nội dung vàng trong mẫu (đặc biệt khi có nhiều số GCNBH), giao diện sẽ cảnh báo nguy cơ dồn trang trước khi tạo Word. Tool không tự giảm font hoặc sửa vùng không tô vàng để chữa bố cục.

## Độ chính xác và bảo mật

- Kết quả OCR và các quy tắc trích xuất được kiểm tra bằng Pydantic.
- Tổng khối lượng và tỷ lệ được tính lại từ từng chứng thư, không dùng tổng do AI tự cộng.
- Trường không tìm thấy để trống; xung đột bị cảnh báo.
- OCR chạy trên máy chủ Streamlit; chứng từ không được gửi tới OpenAI.
- File tạm nằm theo session trong thư mục tạm của hệ thống.
- Không ghi nội dung chứng từ hoặc API key vào log.

OCR không thể bảo đảm đúng tuyệt đối với ảnh mờ. Bước xác nhận của người dùng là bắt buộc trước khi xuất Word.

## Triển khai Streamlit Community Cloud

1. Đưa source lên repository; không commit file Word mẫu hoặc chứng từ thật.
2. Tạo app mới, chọn `app.py` làm entrypoint.
3. Thêm `TEMPLATE_DOCX_BASE64` vào Secrets của app.
4. Đặt runtime Python 3.12 để tương thích với PaddlePaddle.
