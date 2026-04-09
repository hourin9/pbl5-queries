# Sử dụng Python 3.13 làm gốc
FROM python:3.13-slim

# Cài đặt các gói hệ thống cần thiết
RUN mkdir -p /usr/share/man/man1 && \
    apt-get update && apt-get install -y \
    default-jdk-headless \
    git \
    curl \
    unzip \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# Cài đặt uv (Package Manager)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Cài đặt Joern
RUN mkdir -p /opt/joern && \
    curl -L "https://github.com/joernio/joern/releases/latest/download/joern-install.sh" -o joern-install.sh && \
    chmod +x joern-install.sh && \
    ./joern-install.sh --install-dir=/opt/joern && \
    ln -s /opt/joern/joern /usr/local/bin/joern

# Thiết lập thư mục làm việc
WORKDIR /app

# Copy toàn bộ mã nguồn vào container
COPY . .

# Cài đặt dependencies Python qua uv
RUN uv sync --frozen

# Expose cổng 8080 của Joern Server
EXPOSE 8080

# Cấp quyền cho script khởi động
RUN chmod +x entrypoint.sh

# Sử dụng entrypoint script để quản lý server và pipeline
CMD ["./entrypoint.sh"]
