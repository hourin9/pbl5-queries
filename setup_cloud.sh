#!/bin/bash

# --- AUTOMATED SETUP SCRIPT FOR CODE SMELL PIPELINE ---
echo "🚀 Đang khởi tạo môi trường nghiên cứu..."

# 1. Cài đặt uv (Package Manager siêu tốc)
if ! command -v uv &> /dev/null
then
    echo "📦 Đang cài đặt uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    source $HOME/.cargo/env
else
    echo "✅ uv đã có sẵn."
fi

# 2. Cài đặt Joern (Công cụ phân tích tĩnh)
if ! command -v joern &> /dev/null
then
    echo "🔍 Đang cài đặt Joern..."
    mkdir -p $HOME/bin
    curl -L "https://github.com/joernio/joern/releases/latest/download/joern-install.sh" -o joern-install.sh
    chmod +x joern-install.sh
    ./joern-install.sh --install-dir=$HOME/bin/joern --interactive=false
    echo 'export PATH="$HOME/bin/joern:$PATH"' >> ~/.bashrc
    export PATH="$HOME/bin/joern:$PATH"
else
    echo "✅ Joern đã có sẵn."
fi

# 3. Thiết lập dự án
echo "📂 Đang cài đặt dependencies Python..."
uv sync

# 4. Kiểm tra file .env
if [ ! -f .env ]; then
    echo "⚠️  Cảnh báo: Chưa tìm thấy file .env. Đang tạo file mẫu..."
    echo "GITHUB_TOKEN=your_token_here" > .env
    echo "DEEPSEEK_API=your_key_here" >> .env
    echo "MAX_REPOS=50" >> .env
    echo "JOERN_PORT=8080" >> .env
fi

echo "------------------------------------------------"
echo "✅ HOÀN TẤT THIẾT LẬP!"
echo "👉 Bước 1: Mở một terminal mới và chạy: joern --server"
echo "👉 Bước 2: Tại terminal này, chạy: uv run main.py"
echo "------------------------------------------------"
