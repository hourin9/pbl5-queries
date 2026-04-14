import sqlite3
import os
import threading
from utils.logger import get_logger

logger = get_logger(__name__)

class StateManager:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, db_path="data/state.db"):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(StateManager, cls).__new__(cls)
                cls._instance._init_db(db_path)
            return cls._instance

    def _init_db(self, db_path):
        self.db_path = db_path
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS repo_state (
                    repo_url TEXT PRIMARY KEY,
                    repo_name TEXT,
                    phase1_status TEXT DEFAULT 'PENDING',
                    phase2_status TEXT DEFAULT 'PENDING',
                    phase3_status TEXT DEFAULT 'PENDING',
                    phase4_status TEXT DEFAULT 'PENDING',
                    error_log TEXT,
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()

    def upsert_repo(self, repo_url, repo_name):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            # Chỉ chèn nếu chưa tồn tại repo_url. Không dùng UPDATE để tránh reset tiến trình cũ.
            cursor.execute("""
                INSERT OR IGNORE INTO repo_state (repo_url, repo_name)
                VALUES (?, ?)
            """, (repo_url, repo_name))
            conn.commit()

    def update_phase(self, repo_url, phase_num, status, error_log=None):
        phase_col = f"phase{phase_num}_status"
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            query = f"""
                UPDATE repo_state 
                SET {phase_col} = ?, error_log = ?, last_updated = CURRENT_TIMESTAMP
                WHERE repo_url = ?
            """
            cursor.execute(query, (status, error_log, repo_url))
            conn.commit()
            
    def get_pending_repos(self, phase_num):
        phase_col = f"phase{phase_num}_status"
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            if phase_num == 1:
                # Giai đoạn 1 không cần điều kiện phase trước
                cursor.execute(f"SELECT repo_url, repo_name FROM repo_state WHERE {phase_col} != 'DONE'")
            else:
                # Các giai đoạn sau chỉ lấy nếu giai đoạn trước đã DONE và giai đoạn này chưa DONE
                prev_phase_col = f"phase{phase_num-1}_status"
                cursor.execute(f"""
                    SELECT repo_url, repo_name 
                    FROM repo_state 
                    WHERE {prev_phase_col} = 'DONE' AND {phase_col} != 'DONE'
                """)
            return cursor.fetchall()
            
    def get_repo_status(self, repo_url):
         with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM repo_state WHERE repo_url = ?", (repo_url,))
            return cursor.fetchone()

state_manager = StateManager()
