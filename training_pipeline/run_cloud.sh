#!/bin/bash

# Đảm bảo setup_train.sh có quyền thực thi
chmod +x setup_train.sh

# Khởi tạo môi trường
./setup_train.sh

# Cấu hình tối ưu bộ nhớ cho PyTorch
export PYTORCH_ALLOC_CONF=expandable_segments:True

# Chạy pipeline thông qua uv run, truyền toàn bộ tham số người dùng nhập vào cho train.py
echo "🚀 Bắt đầu quá trình Training với tham số: $@"
uv run train.py "$@"
