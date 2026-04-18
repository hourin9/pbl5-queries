#!/bin/bash

# Đảm bảo setup_train.sh có quyền thực thi
chmod +x setup_train.sh

# Khởi tạo môi trường
./setup_train.sh

# Cấu hình tối ưu bộ nhớ cho PyTorch
export PYTORCH_ALLOC_CONF=expandable_segments:True

# Chạy pipeline thông qua uv run, truyền toàn bộ tham số người dùng nhập vào cho train.py
echo "🚀 Bắt đầu quá trình Training..."
if uv run train.py "$@"; then
    echo "✅ Training hoàn tất thành công! Bắt đầu quá trình Export & Upload..."
    # Tự động export sang 16bit và upload lên WandB
    uv run export.py --method merged_16bit
else
    echo "❌ Training bị lỗi. Bỏ qua bước Export."
    exit 1
fi
