# Hướng dẫn triển khai Pipeline lên Cloud CPU

Tài liệu này giúp bạn di chuyển dự án từ máy cá nhân sang các máy chủ mạnh hơn (AWS, Google Cloud,...) để tăng tốc độ tạo dataset.

## 1. Chuẩn bị
Nén toàn bộ thư mục dự án (loại trừ thư mục `temp_data` và `.venv` để giảm dung lượng):
```bash
tar -czvf pbl5_project.tar.gz --exclude='temp_data' --exclude='.venv' --exclude='method_evolutions' .
```

## 2. Trên máy Cloud (Ubuntu/Debian)
Sau khi upload file `.tar.gz` lên máy Cloud:

```bash
# Giải nén
tar -xzvf pbl5_project.tar.gz
cd pbl5-queries

# Chạy script cài đặt tự động (mất khoảng 2-3 phút)
chmod +x setup_cloud.sh
./setup_cloud.sh
```

## 3. Khởi chạy
1.  **Bật Joern Server**:
    ```bash
    joern --server
    ```
    (Nên chạy trong một session `screen` hoặc `tmux` để server không bị tắt khi bạn ngắt kết nối SSH).

2.  **Khởi chạy Pipeline**:
    ```bash
    uv run main.py
    ```

## 4. Lưu ý khi dùng Cloud
- **Cấu hình mạnh**: Nên chọn instance có ít nhất 8-16 Core CPU để tận dụng tối đa khả năng xử lý song song lịch sử Git của Pipeline.
- **Dữ liệu**: Sau khi chạy xong, hãy tải file `dataset_output/final_dataset.jsonl` về máy để nộp báo cáo.
- **Tự động resume**: Nếu máy Cloud bị ngắt kết nối, bạn chỉ cần SSH lại và chạy lại lệnh `uv run main.py`, hệ thống sẽ tự động chạy tiếp từ repository đang dở dang nhờ `state.db`.
