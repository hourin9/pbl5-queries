# Walkthrough: Code Smell Dataset Pipeline

Dự án đã được tái cấu trúc thành công thành một pipeline đa luồng và bất đồng bộ, giúp tăng hiệu suất tối đa khi thu thập và tạo dataset nhận dạng "Shotgun Surgery" và "Divergent Change". 

Các module đã chuyển sang tận dụng triệt để hệ sinh thái từ bên thứ 3 nhằm tăng tốc quá trình phát triển theo đúng định hướng. 

## 1. Những thay đổi chính (Architecture)

1. **Utils/State Manager (`sqlite3`)**:
    Việc theo dõi trạng thái tiến trình clone và sinh metrics được lưu vào local database `data/state.db`. Giúp tự động Self-Healing (chạy lại những repo bị lỗi mạng hoặc API limit bị ngắt nuwax chừng).
    
2. **Phase 1: Async Scraping**:
    - Dùng `aiohttp` để query GitHub API bất đồng bộ.
    - Dùng `tenacity` để tự động exponential backoff retry khi bị HTTP 403 Rate Limit.
    - Hỗ trợ đa dạng token (`GITHUB_TOKEN_1`, `GITHUB_TOKEN_2`,...) để xoay vòng.

3. **Phase 2: Hybrid Multiprocessing & Server Client**:
    - Sử dụng `multiprocessing` quét lịch sử Git qua `pydriller` (nặng tải xử lý CPU).
    - Sử dụng `cpgqls-client` nối với cổng `8080` của Joern thay vì spawn `joern-parse` nhiều lần trong Bash script, tiết kiệm rất nhiều Overhead (thời gian khởi động JVM tốn khoảng 5s-10s mỗi repo trước đây).
    - Dùng Async Lock chặn tránh tương tác đồng thời vào một instance workspace duy nhất của Joern, đảm bảo server không báo lỗi Override Workspace.

4. **Phase 3: AI Synthesis qua DeepSeek**:
    - Sử dụng `tenacity` retry linh hoạt kết hợp với cấu trúc Prompt Strict JSON.
    - Kiểm soát Semaphore giúp không làm nổ băng thông (429 Too Many Requests).

5. **Phase 4: JSON Validation layer**:
    - Sử dụng thư viện rà soát Validation schema nổi tiếng `jsonschema` để tránh Hallucination/Format sai lệch cấu trúc JSON.
    - Kết hợp check Logic mâu thuẫn (VD: Detected = True nhưng Smell = None => đánh lỗi).

## 2. Hướng dẫn chạy (How to run)

### B1. Khởi động backend Joern Server
Mở terminal riêng biệt chạy:
```bash
joern --server
```
*(Cổng mặc định sẽ là 8080, được config qua file `.env` tên `JOERN_PORT`)*

### B2. Khởi tạo môi trường
Do chúng ta dùng `uv`, mọi thứ đã nằm trong `pyproject.toml` và khóa ở `uv.lock`. Môi trường đã có sẵn các gói cần thiết: `loguru`, `tenacity`, `aiohttp`, `pydriller`, `cpgqls-client`...
Hãy chắc chắn `uv` đang active:
```bash
source .venv/bin/activate
```

Tạo file `.env` chứa token của bạn:
```env
DEEPSEEK_API=your-deepseek-api-key
TOKEN=github_token
MAX_REPOS=10
JOERN_PORT=9000
```

### B3. Run Pipeline Core
Chỉ việc gọi script chính:
```bash
uv run main.py
```
Hệ thống sẽ chạy và bạn có thể theo dõi qua log hiện lên Terminal, siêu rõ ràng nhờ `loguru`. Log cũng được lưu vào `logs/pipeline.log`.

> [!TIP] 
> Nếu tiến trình bị hỏng ngang do tắt ứng dụng hoặc mất kết nối mạng đoạn gọi API, bạn chỉ cần gõ lại lệnh trên. **State Manager** sẽ đọc từ SQLite và tìm ra những Repo nào chưa "DONE" hoặc đang "FAILED" để làm tiếp mà không ghi đè hay tốn quota API những file đã xử lý xong.
