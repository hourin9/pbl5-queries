#!/bin/bash

echo "🚀 Đang khởi tạo môi trường training trên Cloud..."

# 1. Kiểm tra và cài đặt uv
if ! command -v uv &> /dev/null
then
    echo "📦 Đang cài đặt uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    source $HOME/.cargo/env
else
    echo "✅ uv đã có sẵn."
fi

# 2. Khởi tạo một project uv cục bộ nếu chưa có
if [ ! -f pyproject.toml ]; then
    echo "📄 Khởi tạo môi trường uv..."
    uv init
    uv add torch transformers peft unsloth accelerate bitsandbytes wandb gdown
fi

# 3. Cài đặt các thư viện cần thiết thông qua uv add
echo "⏳ Đang cài đặt dependencies (quá trình này sẽ diễn ra rất nhanh nhờ uv)..."

# Theo khuyến nghị cài đặt của unsloth

echo "✅ Hoàn tất cài đặt môi trường!"
