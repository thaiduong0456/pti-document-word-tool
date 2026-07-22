# Tool tạo tờ trình thanh toán phí giám định

Ứng dụng Streamlit đọc ảnh/PDF của một bộ chứng từ, trích xuất dữ liệu bằng AI Vision, yêu cầu người dùng kiểm tra rồi tạo lại file Word từ một mẫu cố định.

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

Đặt API key trong môi trường:

```bash
export OPENAI_API_KEY="..."
export OPENAI_MODEL="gpt-5.6"
```

Hoặc khi triển khai Streamlit Cloud, tạo `.streamlit/secrets.toml`:

```toml
OPENAI_API_KEY = "..."
TEMPLATE_DOCX_BASE64 = "..."
```

`OPENAI_API_KEY` là tùy chọn vì người dùng có thể nhập key riêng trong giao diện. Khi chạy cục bộ, đặt mẫu tại `templates/template.docx`. Khi deploy repo công khai, mã hóa mẫu bằng `base64` và chỉ lưu giá trị trong Streamlit Secrets.

Không commit `.env`, `secrets.toml`, file Word mẫu hoặc chứng từ thật lên GitHub.

## Chạy

```bash
streamlit run app.py
```

1. Tải toàn bộ ảnh/PDF của một bộ chứng từ.
   - Chọn **một hoặc nhiều file**; hoặc
   - Chọn **cả thư mục** để tải tất cả PDF/ảnh trong thư mục và thư mục con.
2. Nhập OpenAI API key nếu máy chủ chưa cấu hình sẵn. Ứng dụng tự động xử lý ngay sau khi tải chứng từ.
3. Kiểm tra bằng chứng, sửa giá trị nếu cần và đánh dấu **Xác nhận**.
4. Chỉ khi các trường bắt buộc dùng trong vùng vàng đã được xác nhận, nút tạo Word mới được mở.
5. Tải Word, JSON hoặc bảng kiểm tra Excel. Bản Word tải xuống được tự động bỏ toàn bộ bôi vàng.

## Kiểm thử

Mã nguồn được kiểm thử cục bộ với các bộ chứng từ hồi quy riêng tư. Chứng từ, fixture chứa dữ liệu thật và file Word mẫu không được đưa lên repository công khai.

Nếu dữ liệu mới dài hơn đáng kể so với nội dung vàng trong mẫu (đặc biệt khi có nhiều số GCNBH), giao diện sẽ cảnh báo nguy cơ dồn trang trước khi tạo Word. Tool không tự giảm font hoặc sửa vùng không tô vàng để chữa bố cục.

## Độ chính xác và bảo mật

- Structured Output được kiểm tra bằng Pydantic.
- Tổng khối lượng và tỷ lệ được tính lại từ từng chứng thư, không dùng tổng do AI tự cộng.
- Trường không tìm thấy để trống; xung đột bị cảnh báo.
- Chứng từ chỉ được gửi tới OpenAI khi người dùng chủ động chọn AI Vision và bấm xử lý.
- File tạm nằm theo session trong thư mục tạm của hệ thống.
- Không ghi nội dung chứng từ hoặc API key vào log.

AI/OCR không thể bảo đảm đúng tuyệt đối với ảnh mờ. Bước xác nhận của người dùng là bắt buộc trước khi xuất Word.

## Triển khai Streamlit Community Cloud

1. Đưa source lên repository; không commit file Word mẫu hoặc chứng từ thật.
2. Tạo app mới, chọn `app.py` làm entrypoint.
3. Thêm `TEMPLATE_DOCX_BASE64` vào Secrets của app.
4. Có thể thêm `OPENAI_API_KEY`, hoặc để người dùng nhập key riêng theo từng phiên.
