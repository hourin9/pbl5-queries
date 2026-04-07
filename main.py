import json
import os
import shutil
import stat
import subprocess
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from glob import glob

from build_training_sample import build_training_sample
from deepseek_calls import process_all_methods_with_ai
from dotenv import load_dotenv
from github import Auth, Github

# Import các hàm từ các file trong dự án
from build_dataset import build_method_evolution

# ================= CẤU HÌNH =================
load_dotenv()
GITHUB_TOKEN = os.getenv("TOKEN")

STARS_LIMIT = 1000
MAX_REPOS = 10
MAX_WORKERS = 4  # Số lượng repo xử lý song song (tùy vào CPU/RAM/VRAM)
REPOS_LIST_FILE = "data/repos.txt"

# Pipeline directories
TEMP_WORKSPACE = "./temp_data"
METHOD_EVO_DIR = "./method_evolutions"
GROUND_TRUTH_DIR = "./ground_truth"
FINAL_DATASET_DIR = "./dataset_output"
# ============================================


def handle_remove_readonly(func, path, exc_info):
    """Xử lý lỗi Permission khi xóa thư mục .git"""
    os.chmod(path, stat.S_IWRITE)
    func(path)


def run_shell_command(command, repo_name=""):
    """Chạy lệnh và log theo tên repo để dễ debug"""
    process = subprocess.Popen(
        command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
    )
    # Ta không in toàn bộ log ra console để tránh rối khi chạy đa tiến trình
    stdout, _ = process.communicate()
    if process.returncode != 0:
        print(f"⚠️ [{repo_name}] Lệnh thất bại: {command}")
        return False
    return True


def process_single_repo(repo_url):
    """Worker function: Xử lý trọn gói một repository"""
    repo_name = repo_url.rstrip("/").split("/")[-1].replace(".git", "")

    # Định nghĩa đường dẫn riêng cho từng tiến trình để tránh xung đột Lock
    local_repo_dir = os.path.join(TEMP_WORKSPACE, repo_name)
    cpg_file = os.path.join(TEMP_WORKSPACE, f"{repo_name}_cpg.bin")
    joern_json_out = os.path.join(TEMP_WORKSPACE, f"{repo_name}_graph.json")
    repo_evo_dir = os.path.join(METHOD_EVO_DIR, repo_name)
    repo_gt_dir = os.path.join(GROUND_TRUTH_DIR, repo_name)
    final_jsonl_path = os.path.join(FINAL_DATASET_DIR, "train_dataset_english.jsonl")
    joern_workspace = os.path.join(
        "./workspace", repo_name
    )  # Workspace riêng cho Joern

    os.makedirs(repo_evo_dir, exist_ok=True)
    os.makedirs(repo_gt_dir, exist_ok=True)

    try:
        print(f"🚀 [{repo_name}] Bắt đầu xử lý...")

        # 1. Clone
        if not os.path.exists(local_repo_dir):
            if not run_shell_command(
                f"git clone {repo_url} {local_repo_dir}", repo_name
            ):
                return f"Error: Clone failed for {repo_name}"

        # 2. Joern Parse (Sử dụng tham số --import để tránh dùng chung workspace mặc định)
        run_shell_command(
            f"joern-parse {local_repo_dir} --output {cpg_file}", repo_name
        )

        # 3. Scala Extract
        if os.path.exists(cpg_file):
            run_shell_command(
                f"joern --script extract_features.sc --param cpgPath={os.path.abspath(cpg_file)} "
                f"--param outPath={os.path.abspath(joern_json_out)}",
                repo_name,
            )

        # 4. Evolution History (PyDriller)
        if os.path.exists(joern_json_out):
            build_method_evolution(joern_json_out, local_repo_dir, repo_evo_dir)
        else:
            return f"Skip: Joern failed for {repo_name}"

        # 5. AI Labeling (DeepSeek)
        process_all_methods_with_ai(repo_evo_dir, repo_gt_dir)

        # 6. Ghi Append vào JSONL (Sử dụng File Lock nếu cần, nhưng 'a' thường an toàn trên OS hiện đại)
        added_count = 0
        input_files = glob(os.path.join(repo_evo_dir, "*.json"))

        with open(final_jsonl_path, "a", encoding="utf-8") as f_out:
            for in_path in input_files:
                base_name = os.path.basename(in_path)
                out_path = os.path.join(repo_gt_dir, base_name)
                if os.path.exists(out_path):
                    with (
                        open(in_path, "r", encoding="utf-8") as f_in,
                        open(out_path, "r", encoding="utf-8") as f_gt,
                    ):
                        sample = build_training_sample(json.load(f_in), json.load(f_gt))
                        f_out.write(json.dumps(sample, ensure_ascii=False) + "\n")
                        added_count += 1

        return f"✅ [{repo_name}] Hoàn tất: {added_count} samples."

    except Exception as e:
        return f"❌ [{repo_name}] Lỗi: {str(e)}"
    finally:
        # Dọn dẹp tài nguyên ngay lập tức
        if os.path.exists(local_repo_dir):
            shutil.rmtree(local_repo_dir, onerror=handle_remove_readonly)
        if os.path.exists(cpg_file):
            os.remove(cpg_file)
        if os.path.exists(joern_json_out):
            os.remove(joern_json_out)
        if os.path.exists(joern_workspace):
            shutil.rmtree(joern_workspace, ignore_errors=True)


def main():
    print("🔥 KHỞI CHẠY PIPELINE ĐA TIẾN TRÌNH (REPO-LEVEL) 🔥")
    for d in [TEMP_WORKSPACE, METHOD_EVO_DIR, GROUND_TRUTH_DIR, FINAL_DATASET_DIR]:
        os.makedirs(d, exist_ok=True)

    # Lấy danh sách URL (Giữ nguyên hàm crawl cũ của bạn)
    from advanced_repo_crawler import path_to_repo  # Hoặc hàm crawl của bạn

    # Giả sử repo_urls là list các string URL
    repo_urls = (
        [line.strip() for line in open(REPOS_LIST_FILE)]
        if os.path.exists(REPOS_LIST_FILE)
        else []
    )

    # Sử dụng ProcessPoolExecutor để chạy song song
    with ProcessPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(process_single_repo, url): url for url in repo_urls}

        for future in as_completed(futures):
            result = future.result()
            print(result)

    print("\n🎉 TOÀN BỘ TIẾN TRÌNH KẾT THÚC.")


if __name__ == "__main__":
    main()
