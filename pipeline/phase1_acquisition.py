import asyncio
import os

from utils.logger import get_logger
from utils.state_manager import state_manager

logger = get_logger(__name__)

async def clone_repository(repo_url, repo_name, output_dir):
    try:
        logger.info(f"Đang clone {repo_name}...")
        local_path = os.path.join(output_dir, repo_name)
        if os.path.exists(local_path):
            logger.info(f"Repo {repo_name} đã tồn tại, skip clone.")
            state_manager.update_phase(repo_url, 1, "DONE")
            return local_path

        # Loại bỏ các flag "--filter=blob" và "--single-branch" vì PyDriller cần duyệt full lịch sử commit.
        # Nếu clone bị lỗi mất file tree (exit code -2) thì là do clone chưa đầy đủ.
        cmd = f"git clone {repo_url} {local_path}"
        logger.info(f"Thực thi clone đầy đủ: {cmd}")
        
        proc = await asyncio.create_subprocess_shell(
            cmd, 
            stdout=asyncio.subprocess.PIPE, 
            stderr=asyncio.subprocess.STDOUT
        )
        
        stdout_bytes, _ = await proc.communicate()
        raw_output = stdout_bytes.decode('utf-8', errors='ignore')

        if proc.returncode != 0:
            err_msg = raw_output
            logger.error(f"Lỗi clone {repo_name}: {err_msg}")
            state_manager.update_phase(repo_url, 1, "FAILED", err_msg)
            return None

        logger.info(f"Clone {repo_name} thành công.")
        state_manager.update_phase(repo_url, 1, "DONE")
        return local_path
    except Exception as e:
        logger.error(f"Lỗi Exception khi clone {repo_name}: {e}")
        state_manager.update_phase(repo_url, 1, "FAILED", str(e))
        return None


async def run_phase1_acquisition(max_repos=100):
    logger.info("🗑️ Đã tắt GitHub API Search. Chuyển sang đọc trực tiếp từ danh sách `listrepo.txt`.")
    output_dir = "temp_data"
    os.makedirs(output_dir, exist_ok=True)
    
    if not os.path.exists("listrepo.txt"):
        logger.warning("Không tìm thấy file listrepo.txt. Vui lòng tạo file và điền danh sách URL GitHub để Clone.")
        logger.info("Hoàn thành Giai đoạn 1 (Data Acquisition).")
        return
        
    with open("./data/listrepo.txt", "r", encoding="utf-8") as f:
        urls = [line.strip() for line in f if line.strip() and not line.startswith("#")]
        
    collected = []
    for url in urls:
        # Tách tên repo từ URL (ví dụ: https://github.com/longqt321/ATM_MANAGEMENT.git)
        repo_name = url.split("/")[-1].replace(".git", "")
        collected.append({"clone_url": url, "name": repo_name})
        # Upsert repo vào SQLite Database
        state_manager.upsert_repo(url, repo_name)
    
    CLONE_SEMAPHORE_LIMIT = 5
    semaphore = asyncio.Semaphore(CLONE_SEMAPHORE_LIMIT)
    tasks = []

    async def sem_clone(repo):
        async with semaphore:
            return await clone_repository(repo["clone_url"], repo["name"], output_dir)

    for repo in collected:
        tasks.append(asyncio.create_task(sem_clone(repo)))

    if tasks:
        logger.info(f"🚀 Bắt đầu fetch {len(tasks)} repositories song song từ listrepo.txt (limit={CLONE_SEMAPHORE_LIMIT})...")
        await asyncio.gather(*tasks)
    
    logger.info("Hoàn thành Giai đoạn 1 (Data Acquisition).")
