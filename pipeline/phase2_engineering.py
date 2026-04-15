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

# Cấu hình đa máy chủ Joern để phân tích song song thực thụ
JOERN_ENDPOINTS = [
    {"url": "localhost:8080", "sem": asyncio.Semaphore(1)},
    {"url": "localhost:8081", "sem": asyncio.Semaphore(1)},
    {"url": "localhost:8082", "sem": asyncio.Semaphore(1)},
]

class JoernServerClient:
    def __init__(self):
        self.tmp_dir = "temp_data"
        os.makedirs(self.tmp_dir, exist_ok=True)

    def _execute_command(self, command, endpoint_url):
        """Hàm đồng bộ chạy trong thread, tự tạo loop nội bộ cho thư viện cpgqls"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            client = CPGQLSClient(endpoint_url)
            return client.execute(command)
        finally:
            loop.close()

    async def extract_features(self, repo_path, repo_url, target_methods=None):
        """Phân tích bằng server Joern. Tự động tìm server rảnh từ pool."""
        # Tìm server đang rảnh trong JOERN_ENDPOINTS
        endpoint_info = None
        for ep in JOERN_ENDPOINTS:
            if not ep["sem"].locked():
                endpoint_info = ep
                break
        
        # Nếu tất cả bận, ưu tiên lấy cái đầu tiên (sẽ phải chờ ở dòng async with)
        if not endpoint_info:
            endpoint_info = JOERN_ENDPOINTS[0]
            
        endpoint_url = endpoint_info["url"]
        
        async with endpoint_info["sem"]:
            try:
                abs_repo_path = os.path.abspath(repo_path)
                repo_name = os.path.basename(repo_path)
                logger.info(f"[{repo_name}] Sử dụng Joern Server tại cổng {endpoint_url}")
                
                
                os.system('git config --global --add safe.directory "*"')

                tmp_json = os.path.abspath(f"temp_data/joern_{repo_name}.json")

                # 2. Tạo logic filter cho Joern
                method_filter = ""
                if target_methods:
                    unique_base_files = list(set([os.path.basename(f) for f in [m[0] for m in target_methods]]))
                    target_files_str = ', '.join([f'"{f}"' for f in unique_base_files])
                    # Dùng fuzzy endsWith để khớp đường dẫn
                    method_filter = f"""    val targetFiles = Set({target_files_str})
    val filteredMethods = allMethods.filter(m => targetFiles.exists(t => m.filename.endsWith(t))).l"""
                else:
                    method_filter = "    val filteredMethods = allMethods.l"

                import random
                import string
                # Tạo một ID ngẫu nhiên để không bị trùng project trong workspace của Joern
                rand_id = ''.join(random.choices(string.ascii_lowercase + string.digits, k=6))
                unique_project_name = f"{repo_name}_{rand_id}"

                # 3. Script Scala nhập mã trực tiếp phân tích trên Server
                scala_script = f"""{{
  try {{
    import ujson._
    
    // Nạp mã nguồn sử dụng tên project duy nhất
    println(s"DEBUG: Importing code from {abs_repo_path} into project {unique_project_name}")
    val cpg = importCode(inputPath="{abs_repo_path}", projectName="{unique_project_name}")
    
    // Lấy tất cả methods của dự án
    val allMethods = cpg.method.isExternal(false).l
    println(s"DEBUG: [{repo_name}] Total non-external methods: ${{allMethods.size}}")

    val nodesData = allMethods.flatMap {{ method => 
      val lineStart = method.lineNumber.getOrElse(0)
      val lineEnd = method.lineNumberEnd.getOrElse(0)
      val loc = if (lineStart > 0 && lineEnd > 0) (lineEnd - lineStart + 1) else 0
      
      Some(Obj(
        "id" -> method.id.toString, 
        "name" -> method.name, 
        "signature" -> method.signature,
        "file_path" -> method.filename, 
        "features" -> Obj(
          "loc" -> loc, 
          "cyclomatic_complexity" -> (method.controlStructure.size + 1),
          "fan_in" -> method.caller.size, 
          "fan_out" -> method.callee.size, 
          "external_calls" -> method.callee.name.filterNot(_.startsWith("<operator")).dedup.l,
          "code" -> method.code
        )
      ))
    }}
    
    val outputJson = Obj("nodes" -> nodesData)
    os.write.over(os.Path("{tmp_json}"), ujson.write(outputJson))
    println(s"DEBUG: Success! Metrics written to {tmp_json}")
    
    // Dọn dẹp project ngay sau khi xong để giải phóng RAM
    delete("{unique_project_name}")
    "SUCCESS"
  }} catch {{
    case e: Exception => 
      val msg = "SCALA ERROR: " + e.getMessage
      println(msg)
      msg
  }}
}}"""
                res = await asyncio.to_thread(self._execute_command, scala_script, endpoint_url)
                
                if not os.path.exists(tmp_json):
                    logger.error(f"Joern Server fail [{repo_name}] at {endpoint_url}. Response: {res}")
                    return None

                try:
                    with open(tmp_json, "r", encoding="utf-8") as f:
                        metrics_data = json.load(f)
                    os.remove(tmp_json)
                except Exception as e:
                    logger.error(f"JSON Error: {e}")
                    return None

                return metrics_data.get("nodes", [])

            except Exception as e:
                state_manager.update_phase(repo_url, 2, "FAILED", str(e))
                return None


def process_commit_history_worker(repo_path):
    """Worker chạy trong Multiprocessing (PyDriller)"""
    logger.info(f"[CPU Worker] Bắt đầu duyệt PyDriller trên: {repo_path}")
    changes_by_method = {}

    # Chỉ tính extensions chứa logic nghiệp vụ Java
    exts = [".java"]

    try:
        from datetime import datetime, timedelta
        dt_since = datetime.now() - timedelta(days=365*10)
        repo_obj = Repository(
            repo_path, 
            only_no_merge=True, 
            only_modifications_with_file_types=exts,
            since=dt_since
        )
        repo_iter = iter(repo_obj.traverse_commits())
        count = 0
        while True:
            try:
                commit = next(repo_iter)
                count += 1
                if count % 100 == 0:
                    logger.info(f"[CPU Worker] {repo_path}: Đã duyệt {count} commits...")
            except StopIteration:
                break
            except Exception as e:
                logger.warning(f"Lỗi Git tại commit {count} (có thể do lazy load): {e}. Đang lướt kế...")
                continue

            try:
                # 1. NOISE FILTERING: Bỏ qua commit refactor/style/docs
                msg_lower = commit.msg.lower()
                if any(kw in msg_lower for kw in ["[ci]", "format", "style", "docs", "readme"]):
                    continue

                # 2. Xử lý tập trung các tệp tin thay đổi
                commit_classes = set()
                relevant_modifications = []
                for m_file in commit.modified_files:
                    path = m_file.new_path or m_file.old_path
                    if path and any(path.endswith(ex) for ex in exts):
                        commit_classes.add(path.split('/')[-1])
                        relevant_modifications.append(m_file)

                # 3. Phân tích phương thức thay đổi
                for m_file in relevant_modifications:
                    path = m_file.new_path or m_file.old_path
                    for method in m_file.changed_methods:
                        clean_method_name = method.name.split("::")[-1]
                        key = (path, clean_method_name)

                        # DEDUPLICATION: Tránh lặp lại method giống nhau trong cùng 1 file ở cùng commit
                        if key in changes_by_method and changes_by_method[key][-1]["h"] == commit.hash[:8]:
                            continue

                        # Loại bỏ chính class hiện tại để chỉ giữ lại các list classes khác
                        other_classes = list(commit_classes - {path.split('/')[-1]})

                        changes_by_method.setdefault(key, []).append({
                            "h": commit.hash[:8],
                            "d": str(commit.author_date),
                            "msg": commit.msg.strip()[:100],
                            "nd": commit.deletions,
                            "ni": commit.insertions,
                            "nf": commit.files,
                            "co_classes": other_classes
                        })
            except Exception as commit_err:
                # Bỏ qua commit lỗi (thường do shallow clone thiếu lịch sử diff)
                logger.warning(f"Bỏ qua commit {commit.hash[:8]} do lỗi: {commit_err}")
                continue
        
        logger.info(f"[CPU Worker] PyDriller hoàn tất: {len(changes_by_method)} methods có thay đổi.")
        return {"repo_path": repo_path, "changes": changes_by_method, "status": "OK"}
    except Exception as e:
        return {"repo_path": repo_path, "error": str(e), "status": "ERROR"}


import socket

def check_joern_health(host="localhost", port=8080, timeout=3):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False

async def run_phase2_engineering(
    output_dir="method_evolutions"
):
    # Khắc phục lỗi Dubious Ownership của Git trước khi bất kỳ file/worker nào chạy
    os.system('git config --global --add safe.directory "*"')

    os.makedirs(output_dir, exist_ok=True)
    repos = state_manager.get_pending_repos(2)  # [(url, name), ...]
    if not repos:
        logger.info("Không có Repos nào cần chạy Phase 2.")
        return

    global JOERN_ENDPOINTS
    # Heartbeat Check toàn bộ Server Pool và lọc ra các máy chủ còn sống
    alive_endpoints = []
    for ep in JOERN_ENDPOINTS:
        host, port = ep["url"].split(":")
        if check_joern_health(host, int(port)):
            alive_endpoints.append(ep)

    if not alive_endpoints:
        logger.error("❌ TẤT CẢ CPG Server (Joern Pool) đều MẤT KẾT NỐI! Vui lòng khởi động ít nhất 1 server.")
        return
    else:
        logger.info(f"✅ Hệ thống bắt được tín hiệu từ {len(alive_endpoints)} Joern Server đang rảnh rỗi. Đang làm mới Pool.")
        JOERN_ENDPOINTS = alive_endpoints

    logger.info(f"Phase 2: Bắt đầu xử lý {len(repos)} repository.")
    joern_client = JoernServerClient()


    # Setup process pool cho PyDriller
    max_workers = 2
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

            # 2. PyDriller (Song song Multiprocessing)
            logger.info(f"[{r_name}] Bước 2: Khởi chạy PyDriller quét lịch sử commit...")
            evolution_data = await loop.run_in_executor(
                executor, process_commit_history_worker, l_path
            )

            if evolution_data["status"] == "ERROR":
                logger.error(f"[{r_name}] PyDriller worker error: {evolution_data['error']}")
                state_manager.update_phase(r_url, 2, "FAILED", evolution_data["error"])
                return

            # 2. Joern Static Analysis (Thử bắn tỉa trước)
            target_methods = list(evolution_data["changes"].keys())
            metrics_nodes = await joern_client.extract_features(l_path, r_url, target_methods)
            
            # FALLBACK: Nếu bắn tỉa không ra gì, quét toàn bộ repo
            if not metrics_nodes:
                logger.warning(f"[{r_name}] Targeted Joern failed. Falling back to Full Scan...")
                metrics_nodes = await joern_client.extract_features(l_path, r_url, target_methods=None)

            if not metrics_nodes:
                logger.error(f"[{r_name}] Joern returned zero methods even in Full Scan.")
                state_manager.update_phase(r_url, 2, "FAILED", "Joern parse thất bại hoàn toàn")
                return

            # 3. Tạo dictionary từ Joern
            joern_dt = {}
            overloaded_keys = set()
            for item in metrics_nodes:
                key = (item["file_path"], item["name"])
                if key in joern_dt:
                    overloaded_keys.add(key)
                joern_dt[key] = item
            
            # Loại bỏ các phương thức bị Overloaded (nhiều phương thức cùng tên trong 1 file) để chống Nhiễu Nhãn (Label Noise)
            for k in overloaded_keys:
                del joern_dt[k]

            logger.info(f"[{r_name}] Joern tìm thấy {len(joern_dt)} methods mục tiêu.")

            history = evolution_data["changes"]
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
