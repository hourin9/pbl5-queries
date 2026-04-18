#!/bin/bash

echo "🚀 Đang khởi tạo môi trường training trên Cloud..."

# 1. Cài đặt Compiler (triton yêu cầu gcc/g++ để biên dịch các custom kernel của unsloth)
if ! command -v gcc &> /dev/null
then
    echo "🛠️ Đang cài đặt C/C++ Compiler (gcc, g++, build-essential)..."
    if [ -x "$(command -v apt-get)" ]; then
        sudo apt-get update
        sudo apt-get install -y gcc g++ build-essential
    elif [ -x "$(command -v yum)" ]; then
        sudo yum install -y gcc gcc-c++ make
    else
        echo "⚠️ Không tìm thấy apt-get hoặc yum. Vui lòng tự cài đặt gcc/g++."
    fi
else
    echo "✅ Compiler (gcc) đã có sẵn."
fi

# 2. Kiểm tra và cài đặt uv
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
fi

# 3. Cài đặt các thư viện cần thiết thông qua uv add
echo "⏳ Đang cài đặt dependencies (quá trình này sẽ diễn ra rất nhanh nhờ uv)..."
uv add torch transformers peft unsloth accelerate bitsandbytes wandb gdown xformers triton trl

# Theo khuyến nghị cài đặt của unsloth

echo "✅ Hoàn tất cài đặt môi trường!"
