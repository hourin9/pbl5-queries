# BÁO CÁO KỸ THUẬT: HỆ THỐNG TỰ ĐỘNG HÓA QUY TRÌNH XÂY DỰNG TẬP DỮ LIỆU CODE SMELL DỰA TRÊN PHƯƠNG PHÁP CHƯNG CẤT TRI THỨC

## 1. GIỚI THIỆU (INTRODUCTION)
Tài liệu này trình bày về kiến trúc và cơ chế vận hành của hệ thống xây dựng tập dữ liệu (dataset) tự động nhằm phục vụ bài toán phát hiện các khiếm khuyết thiết kế mã nguồn (Code Smells). Hệ thống tập trung vào việc trích xuất các đặc trưng phần mềm phức tạp như **Shotgun Surgery** và **Divergent Change** thông qua sự kết hợp giữa phân tích tĩnh đồ thị mã nguồn và phân tích lịch sử tiến hóa phần mềm. Dữ liệu đầu ra được chuẩn hóa để phục vụ quá trình huấn luyện các mô hình ngôn ngữ lớn kích thước nhỏ (Student LLMs) theo cơ chế **Knowledge Distillation** (Chưng cất tri thức).

## 2. PHƯƠNG PHÁP LUẬN VÀ KIẾN TRÚC HỆ THỐNG (METHODOLOGY)

Kiến trúc hệ thống được thiết kế dựa trên mô hình xử lý song song lai (Hybrid Parallel Processing), kết hợp giữa lập trình bất đồng bộ (Asynchronous Programming) cho các tác vụ I/O và đa tiến trình (Multiprocessing) cho các tác vụ tính toán chuyên sâu (CPU-bound). Trạng thái của hệ thống được quản lý tập trung thông qua thực thể `state_manager`, đảm bảo tính toàn vẹn dữ liệu và khả năng tự phục hồi (Fault Tolerance) trong quá trình thực thi.

Quy trình thực hiện được chia thành bốn giai đoạn (Phases) kế tiếp nhau:

### Giai đoạn 1: Thu thập dữ liệu (Data Acquisition)
Mục tiêu là xây dựng kho lưu trữ mã nguồn sơ cấp từ các dự án phần mềm thực tế.
- **Quy trình:** Hệ thống thực hiện truy vấn thông qua GitHub Search API dựa trên các tiêu chí về ngôn ngữ (Java, C++) và lĩnh vực ứng dụng. Các dự án được lọc qua bộ lọc từ khóa định sẵn để loại bỏ các nguồn dữ liệu nhiễu (mã nguồn giáo trình, bài tập thực hành).
- **Kỹ thuật áp dụng:** Sử dụng cơ chế xoay vòng khóa truy cập (Token Rotation) kết hợp với thuật toán Exponential Backoff nhằm tối ưu hóa hiệu suất truy vấn và tuân thủ giới hạn của API cung cấp (Rate Limits).

### Giai đoạn 2: Trích xuất đặc trưng đa chiều (Multidimensional Feature Engineering)
Giai đoạn này thực hiện phân tích chuyên sâu để trích xuất hồ sơ thuộc tính của từng phương thức (Method profile). Hệ thống áp dụng mô hình phân tích kết hợp giữa hai chiều: **Không gian (Tĩnh)** và **Thời gian (Tiến hóa)**.

- **Phân tích tĩnh (Static Analysis):** Sử dụng công cụ **Joern** để xây dựng Đồ thị thuộc tính mã nguồn (Code Property Graph - CPG). Tại đây, các chỉ số về cấu trúc được trích xuất bao gồm: Độ phức tạp tuần tự (Cyclomatic Complexity), Liên kết đầu vào/đầu ra (Fan-in/Fan-out) và thân mã nguồn thực tế.
- **Phân tích tiến hóa (Evolutionary Analysis):** Sử dụng **PyDriller** để truy xuất lịch sử thay đổi từ Git. Các đặc trưng bao gồm mật độ thay đổi (Commit Count), số lượng tệp tin đồng thay đổi (Avg Files Per Commit) và sự biến đổi của các thuộc tính tĩnh qua các phiên bản.

**Lưu ý về thứ tự thực thi và tính nhất quán dữ liệu:**
Quá trình phân tích tĩnh thông qua Joern được thực hiện trên phiên bản hiện tại (latest version) của mã nguồn để xác định cấu trúc và ngữ cảnh thực thi chi tiết. Ngay sau đó, quá trình phân tích lịch sử sẽ lồng ghép các chỉ số phức tạp tĩnh (Complexity) được tính toán định kỳ tại mỗi điểm commit. Phương pháp này cho phép hệ thống vừa nắm bắt được kiến trúc hiện tại của hàm (qua Joern), vừa theo dõi được sự biến thiên của các thuộc tính tĩnh theo thời gian (qua PyDriller), từ đó hình thành cơ sở dữ liệu đa chiều cho mô hình suy luận.

### Giai đoạn 3: Tổng hợp tri thức và Gán nhãn (Knowledge Synthesis & Labeling)
Hệ thống sử dụng mô hình ngôn ngữ lớn (Teacher Model - cụ thể là DeepSeek) để thực thi vai trò của một chuyên gia phân tích phần mềm.
- **Cơ chế lập luận:** Thay vì gán nhãn định tính, mô hình được yêu cầu thực hiện phân tích định lượng (Quantitative Reasoning) dựa trên các ngưỡng giá trị (Threshold-based) đã được thiết lập từ các nghiên cứu thực nghiệm về kỹ thuật phần mềm.
- **Tối ưu hóa tài nguyên:** Sử dụng hệ thống tự động hóa trình duyệt (Camoufox) kết hợp với cơ chế duy trì phiên đăng nhập (Auth Persistence) để tương tác trực tiếp với giao diện người dùng của mô hình, giúp giảm thiểu chi phí tích hợp API và tối ưu hóa context window cho các đoạn mã nguồn lớn.

### Giai đoạn 4: Kiểm chứng và Chuẩn hóa (Validation & Standardization)
Dữ liệu từ bước tổng hợp được đưa qua quy trình kiểm soát chất lượng nghiêm ngặt trước khi đóng gói.
- **Kỹ thuật kiểm chứng:** Sử dụng `jsonschema` để xác thực cấu trúc dữ liệu và thực hiện kiểm tra tính nhất quán logic (Logic Consistency Check). Các bản ghi có dấu hiệu ảo giác (Hallucination) hoặc có chỉ số tin cậy (Confidence Score) dưới ngưỡng 0.3 sẽ bị loại bỏ.
- **Định dạng dữ liệu:** Kết quả cuối cùng được xuất bản dưới định dạng JSONL, tuân thủ cấu trúc Instruction (`system`, `instruction`, `output`) chuyên dụng cho quá trình Fine-tuning.

## 3. THẢO LUẬN (DISCUSSION)
Điểm cốt lõi của hệ thống nằm ở khả năng tạo ra các tập dữ liệu minh bạch thông qua **Reasoning Track** (Lịch sử tư duy). Mỗi thực thể dữ liệu không chỉ chứa kết quả phân loại mà còn bao gồm quy trình suy luận từng bước (Step-by-step logic), từ việc đánh giá các đặc trưng tĩnh đến việc đối chiếu với các ngưỡng lịch sử tiến hóa. Đây là yếu tố then chốt giúp các mô hình Student LLM học được cách tư duy logic thay vì chỉ học máy móc các quan hệ tương quan.

## 4. KẾT LUẬN (CONCLUSION)
Hệ thống đã thiết lập một luồng xử lý tự động hiệu quả, giải quyết được bài toán thiếu hụt dữ liệu gán nhãn chất lượng cao trong lĩnh vực phân tích mã nguồn. Sự kết hợp giữa phân tích tĩnh, phân tích lịch sử tiến hóa và khả năng suy luận của AI tạo tiền đề vững chắc cho việc phát triển các công cụ phát hiện Code Smell thế hệ mới dựa trên học sâu.
/