import sqlite3
import shutil
import os
from utils.logger import logger

DB_PATH = "data/state.db"
TEMP_DATA_DIR = "temp_data"
EVOLUTIONS_DIR = "method_evolutions"

# Danh sách từ khóa "đen" cần loại bỏ
FORBIDDEN_KEYWORDS = [
    'algorithm', 'leetcode', 'interview', 'exercise', 'tutorial', 
    'course', 'solution', 'practice', 'competitive', 'demo', 'template', 'syllabus'
]

def cleanup():
    if not os.path.exists(DB_PATH):
        print("❌ Không tìm thấy database.")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 1. Lấy danh sách các repo cần xóa
    cursor.execute("SELECT repo_name FROM repo_state")
    all_repos = [row[0] for row in cursor.fetchall()]

    to_delete = []
    for repo in all_repos:
        if any(key in repo.lower() for key in FORBIDDEN_KEYWORDS):
            to_delete.append(repo)

    if not to_delete:
        print("✅ Không tìm thấy repo nào cần dọn dẹp.")
        return

    print(f"🧹 Phát hiện {len(to_delete)} repo không phù hợp: {to_delete}")

    for repo in to_delete:
        # Xóa trong DB
        cursor.execute("DELETE FROM repo_state WHERE repo_name = ?", (repo,))
        
        # Xóa thư mục code
        repo_path = os.path.join(TEMP_DATA_DIR, repo)
        if os.path.exists(repo_path):
            shutil.rmtree(repo_path)
            print(f"🗑️ Đã xóa thư mục: {repo_path}")
        
        # Xóa file đặc trưng đã trích xuất (nếu có)
        feat_path = os.path.join(EVOLUTIONS_DIR, f"{repo}.json")
        if os.path.exists(feat_path):
            os.remove(feat_path)
            print(f"🗑️ Đã xóa đặc trưng: {feat_path}")

    conn.commit()
    conn.close()
    print("✨ Dọn dẹp Database hoàn tất!")

if __name__ == "__main__":
    cleanup()
