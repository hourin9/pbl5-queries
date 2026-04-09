import asyncio
import json
import os
from concurrent.futures import ProcessPoolExecutor
from threading import Lock

from pydriller import Repository

from utils.logger import get_logger
from utils.state_manager import state_manager

try:
    from cpgqls_client import CPGQLSClient, import_code_query, workspace_query
except ImportError:
    pass

logger = get_logger(__name__)

joern_lock = asyncio.Lock()  # Khóa chặn tương tác song song cpg server của joern


class JoernServerClient:
    def __init__(self, endpoint="localhost:8080"):
        self.endpoint = endpoint
        # Ta không khởi tạo self.client ở đây để tránh capture event loop của main thread

    def _execute_command(self, command):
        """Hàm đồng bộ chạy trong thread, tự tạo loop nội bộ cho thư viện cpgqls"""
        # Tạo và thiết lập một event loop mới cho riêng thread này
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            client = CPGQLSClient(self.endpoint)
            # execute() của thư viện sẽ tìm thấy 'loop' chúng ta vừa set
            return client.execute(command)
        finally:
            loop.close()

    async def extract_features(self, repo_path, repo_url):
        async with joern_lock:
            try:
                abs_repo_path = os.path.abspath(repo_path)
                repo_name = os.path.basename(repo_path)
                # Tạo file tạm riêng cho từng repo để tránh xung đột
                tmp_json = os.path.abspath(f"temp_data/joern_{repo_name}.json")
                if os.path.exists(tmp_json):
                    os.remove(tmp_json)

                # Query sử dụng os.write của Scala để ghi thẳng xuống đĩa
                # Bổ sung lọc loc >= 5 để đảm bảo method có ý nghĩa
                combined_query = f"""
                {{
                  // Tự động nhận diện và nạp các extensions phổ biến
                  importCode("{abs_repo_path}", "{repo_name}")
                  import ujson._
                  
                  // Lọc các phương thức không phải boilerplate
                  val allMethods = cpg.method
                    .filterNot(m => m.name.startsWith("<") || m.filename.contains("test") || m.filename.contains("mock"))
                    .filter(m => m.lineNumber.isDefined && m.lineNumberEnd.isDefined)
                    .l

                  val nodesData = allMethods.flatMap {{ method =>
                    val lineStart = method.lineNumber.get
                    val lineEnd = method.lineNumberEnd.get
                    val loc = lineEnd - lineStart + 1
                    
                    // Chỉ lấy những method có chiều dài đáng kể (>= 5 dòng)
                    if (loc >= 5) {{
                      Some(Obj(
                        "id" -> method.id.toString, 
                        "name" -> method.name, 
                        "file_path" -> method.filename, 
                        "features" -> Obj(
                          "loc" -> loc, 
                          "cyclomatic_complexity" -> (method.controlStructure.size + 1),
                          "fan_in" -> method.caller.size, 
                          "fan_out" -> method.callee.size, 
                          "code" -> method.code
                        )
                      ))
                    }} else None
                  }}
                  
                  // Ghi trực tiếp ra file tạm
                  os.write.over(os.Path("{tmp_json}"), ujson.write(Obj("nodes" -> nodesData)))
                  "DONE"
                }}
                """

                logger.debug(f"[{repo_name}] Đang phân tích và ghi file: {tmp_json}")
                res = await asyncio.to_thread(self._execute_command, combined_query)

                # Kiểm tra file đã sinh ra chưa
                if not os.path.exists(tmp_json):
                    logger.error(
                        f"Joern không tạo được file kết quả tại: {tmp_json}. Response: {res}"
                    )
                    return None

                try:
                    with open(tmp_json, "r", encoding="utf-8") as f:
                        metrics_data = json.load(f)
                    # Xóa file tạm sau khi đọc thành công
                    os.remove(tmp_json)
                except Exception as e:
                    logger.error(f"Lỗi khi đọc file kết quả {tmp_json}: {e}")
                    return None

                # Clean workspace
                await asyncio.to_thread(self._execute_command, "workspace.reset")
                return metrics_data.get("nodes", [])

            except Exception as e:
                logger.error(f"Lỗi extract joern cpgqls (có thể do OOM): {e}")
                # Nếu sập server, có thể cần notify người dùng hoặc log lại trạng thái
                state_manager.update_phase(
                    repo_url, 2, "FAILED", f"Joern error: {str(e)}"
                )
                return None


def process_commit_history_worker(repo_path):
    """Worker chạy trong Multiprocessing (PyDriller)"""
    logger.info(f"[CPU Worker] Bắt đầu duyệt PyDriller trên: {repo_path}")
    changes_by_method = {}

    # Chỉ tính extensions thông dụng
    exts = [".c", ".cpp", ".h", ".hpp", ".java"]

    try:
        repo_obj = Repository(
            repo_path, only_no_merge=True, only_modifications_with_file_types=exts
        )
        for commit in repo_obj.traverse_commits():
            try:
                for m_file in commit.modified_files:
                    # Dùng new_path hoặc old_path để lấy đường dẫn tương đối chuẩn (ví dụ: src/main/java/...)
                    path = m_file.new_path or m_file.old_path
                    if not path:
                        continue
                        
                    for method in m_file.changed_methods:
                        # Chuẩn hóa tên method: PyDriller Java thường trả về ClassName::MethodName
                        # Chúng ta chỉ lấy phần MethodName để khớp với Joern
                        clean_method_name = method.name.split("::")[-1]
                        key = (path, clean_method_name)
                        change = {
                            "h": commit.hash[:8],
                            "d": str(commit.author_date),
                            "msg": commit.msg.strip(),
                            "nd": commit.deletions,
                            "ni": commit.insertions,
                            "cxc": method.complexity,
                        }
                        changes_by_method.setdefault(key, []).append(change)
            except Exception as commit_err:
                # Bỏ qua commit lỗi (thường do shallow clone thiếu lịch sử diff)
                logger.warning(f"Bỏ qua commit {commit.hash[:8]} do lỗi: {commit_err}")
                continue
                
        return {"repo_path": repo_path, "changes": changes_by_method, "status": "OK"}
    except Exception as e:
        return {"repo_path": repo_path, "error": str(e), "status": "ERROR"}


async def run_phase2_engineering(
    output_dir="method_evolutions", joern_endpoint="localhost:8080"
):
    os.makedirs(output_dir, exist_ok=True)
    repos = state_manager.get_pending_repos(2)  # [(url, name), ...]
    if not repos:
        logger.info("Không có Repos nào cần chạy Phase 2.")
        return

    logger.info(f"Phase 2: Bắt đầu xử lý {len(repos)} repository.")
    joern_client = JoernServerClient(joern_endpoint)

    # Setup process pool cho PyDriller
    max_workers = min(os.cpu_count() or 4, 8)
    executor = ProcessPoolExecutor(max_workers=max_workers)
    loop = asyncio.get_event_loop()

    tasks = []

    for rp in repos:
        repo_url, repo_name = rp
        local_path = os.path.join("temp_data", repo_name)
        if not os.path.exists(local_path):
            state_manager.update_phase(repo_url, 2, "FAILED", "Repo chưa được tải về")
            continue

        repo_output_dir = os.path.join(output_dir, repo_name)
        os.makedirs(repo_output_dir, exist_ok=True)

        async def process_one(r_url, r_name, l_path, r_out):
            # 0. Kiểm tra nhanh xem repo có chứa source code hợp lệ không
            def has_valid_files(path):
                valid_exts = (".c", ".cpp", ".h", ".hpp", ".java")
                for root, _, files in os.walk(path):
                    for f in files:
                        if f.endswith(valid_exts):
                            return True
                return False

            if not has_valid_files(l_path):
                state_manager.update_phase(r_url, 2, "FAILED", "Không tìm thấy source code hợp lệ (.c, .cpp, .java...)")
                logger.info(f"Repo {r_name} bị loại vì không chứa các tệp mã nguồn hợp lệ.")
                return

            # 1. Joern (Tuần tự thông qua Async Lock)
            logger.info(f"[{r_name}] Bước 1: Khởi chạy Joern trích xuất đặc trưng tĩnh...")
            static_metrics_list = await joern_client.extract_features(l_path, r_url)
            if not static_metrics_list:
                logger.error(f"[{r_name}] Joern returned zero methods. Check if Joern server is alive or if the code is parseable.")
                state_manager.update_phase(r_url, 2, "FAILED", "Joern parse thất bại (0 methods)")
                return

            # Tạo dictionary từ Joern
            joern_dt = {}
            for item in static_metrics_list:
                # Dùng trực tiếp file_path từ Joern (thường là đường dẫn tương đối chuẩn)
                key = (item["file_path"], item["name"])
                joern_dt[key] = item
            logger.info(f"[{r_name}] Joern tìm thấy {len(joern_dt)} methods tiềm năng.")

            # 2. PyDriller (Song song Multiprocessing)
            logger.info(f"[{r_name}] Bước 2: Khởi chạy PyDriller quét lịch sử commit...")
            result = await loop.run_in_executor(
                executor, process_commit_history_worker, l_path
            )

            if result["status"] == "ERROR":
                logger.error(f"[{r_name}] PyDriller worker error: {result['error']}")
                state_manager.update_phase(r_url, 2, "FAILED", result["error"])
                return

            history = result["changes"]
            logger.info(f"[{r_name}] PyDriller hoàn tất với {len(history)} methods có thay đổi.")

            # 3. Merge dữ liệu và xuất
            count = 0
            for key, ev_list in history.items():
                if key in joern_dt:
                    mid = joern_dt[key]["id"]
                    static_features = joern_dt[key]
                    ev_list.sort(key=lambda x: x["d"])  # Theo timeline

                    final_data = {"mid": mid, "sa": static_features, "ev": ev_list}

                    out_path = os.path.join(r_out, f"{mid}.json")
                    with open(out_path, "w", encoding="utf-8") as f:
                        json.dump(final_data, f, ensure_ascii=False)
                    count += 1
            
            if count <= 5 and len(history) > 0:
                logger.warning(f"[{r_name}] Debug Match: Sinh được {count} methods. Kiểm tra format:")
                logger.warning(f"Sample Joern keys: {list(joern_dt.keys())[:5]}")
                logger.warning(f"Sample PyDriller keys: {list(history.keys())[:5]}")
                
            state_manager.update_phase(r_url, 2, "DONE", f"Extracted {count} methods")
            logger.info(f"Repo {r_name}: Sinh {count} methods dataset qua Phase 2.")

        tasks.append(
            asyncio.create_task(
                process_one(repo_url, repo_name, local_path, repo_output_dir)
            )
        )

    await asyncio.gather(*tasks)
    executor.shutdown()
    logger.info("Hoàn thành Giai đoạn 2 (Engineering).")
