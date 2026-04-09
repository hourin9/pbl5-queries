#!/bin/bash

# 1. Khởi động Joern Server với giới hạn RAM cao (8GB-12GB khuyến nghị)
echo "🚀 Starting Joern Server with high memory allocation..."
export JAVA_OPTS="-Xmx12G"
joern --server &

# Đợi server sẵn sàng (khoảng 15-20s)
echo "⏳ Waiting for Joern Server to initialize (20s)..."
sleep 20

# 2. Khởi chạy Pipeline chính
echo "🔥 Starting Code Smell Pipeline..."
uv run main.py

# Giữ container sống nếu bạn muốn log vẫn hiện ra
wait
