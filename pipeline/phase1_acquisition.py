import asyncio
import os

import aiohttp
from tenacity import retry, stop_after_attempt, wait_exponential

from utils.logger import get_logger
from utils.state_manager import state_manager

logger = get_logger(__name__)

# Cấu trúc đọc rotation tokens từ môi trường
GITHUB_TOKENS = [
    os.getenv(f"GITHUB_TOKEN_{i}") or os.getenv("TOKEN")
    for i in range(1, 10)
    if os.getenv(f"GITHUB_TOKEN_{i}") or (i == 1 and os.getenv("TOKEN"))
]
GITHUB_TOKENS = list(filter(None, set(GITHUB_TOKENS)))

if not GITHUB_TOKENS:
    logger.warning(
        "Không tìm thấy GITHUB_TOKEN trong .env. Quá trình fetch API có thể bị giới hạn."
    )
    GITHUB_TOKENS = [""]


class GitHubAcquisition:
    def __init__(self, output_dir="temp_data"):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)
        self.token_idx = 0
        self.lock = asyncio.Lock()

    async def _get_next_token(self):
        async with self.lock:
            token = GITHUB_TOKENS[self.token_idx]
            self.token_idx = (self.token_idx + 1) % len(GITHUB_TOKENS)
            return token

    @retry(
        stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, min=4, max=60)
    )
    async def fetch_repos_page(self, session, query, page=1):
        url = "https://api.github.com/search/repositories"
        token = await self._get_next_token()
        headers = {"Accept": "application/vnd.github.v3+json"}
        if token:
            headers["Authorization"] = f"token {token}"

        params = {
            "q": query,
            "per_page": 100,
            "page": page,
            "sort": "stars",
            "order": "desc",
        }

        async with session.get(url, headers=headers, params=params) as resp:
            if resp.status == 403:
                logger.warning("Rate limit exceeded. Đang chờ tenacity tự retry...")
                resp.raise_for_status()
            if resp.status != 200:
                logger.error(f"Lỗi truy vấn GitHub: {resp.status}")
                resp.raise_for_status()

            data = await resp.json()
            return data.get("items", [])

    async def crawl_repositories(self, max_repos=100):
        queries = [
            "language:java management system",
            'language:java "web server" http',
            "language:java database engine",
            'language:C++ "game engine" graphics',
            'language:C++ "operating system" kernel',
            "language:C++ computer-vision library",
            "language:C++ networking tool",
            "language:C++ driver hardware",
        ]
        # Giới hạn mỗi query chỉ lấy 3-4 repo để đảm bảo đa dạng
        REPOS_PER_QUERY = 4

        # Từ khóa tuyệt đối không được xuất hiện
        forbidden = [
            "algorithm",
            "leetcode",
            "interview",
            "exercise",
            "tutorial",
            "course",
            "solution",
            "practice",
            "competitive",
            "demo",
            "template",
            "syllabus",
            "handbook",
            "learning",
            "example",
        ]

        collected_repos = []

        async with aiohttp.ClientSession() as session:
            for query in queries:
                logger.info(f"Đang fetch repositories với query: {query}")
                page = 1
                query_count = 0
                while (
                    len(collected_repos) < max_repos and query_count < REPOS_PER_QUERY
                ):
                    try:
                        items = await self.fetch_repos_page(session, query, page)
                        if not items:
                            break

                        for item in items:
                            if query_count >= REPOS_PER_QUERY:
                                break

                            name = item["name"].lower()
                            description = (item["description"] or "").lower()

                            if any(f in name or f in description for f in forbidden):
                                continue

                            clone_url = item["clone_url"]
                            repo_name = item["name"]
                            state_manager.upsert_repo(clone_url, repo_name)
                            collected_repos.append(item)
                            query_count += 1

                            if len(collected_repos) >= max_repos:
                                break
                        page += 1
                        await asyncio.sleep(
                            2
                        )  # Nghỉ giữa mỗi query để tránh chặn rate limit
                    except Exception as e:
                        logger.error(f"Lỗi khi crawl query '{query}': {e}")
                        break

        logger.info(f"Hoàn thành crawl {len(collected_repos)} repos.")
        return collected_repos


async def clone_repository(repo_url, repo_name, output_dir):
    try:
        logger.info(f"Đang shallow clone {repo_name}...")
        local_path = os.path.join(output_dir, repo_name)
        if os.path.exists(local_path):
            logger.info(f"Repo {repo_name} đã tồn tại, skip clone.")
            state_manager.update_phase(repo_url, 1, "DONE")
            return local_path

        cmd = f"git clone {repo_url} {local_path}"
        proc = await asyncio.create_subprocess_shell(
            cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            err_msg = stderr.decode()
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
    acq = GitHubAcquisition()
    collected = await acq.crawl_repositories(max_repos)
    logger.info("Bắt đầu clone các repo đã thu thập...")

    tasks = []
    # Clone 3 Repo cùng một lúc
    semaphore = asyncio.Semaphore(3)

    async def sem_clone(url, name, d):
        async with semaphore:
            return await clone_repository(url, name, d)

    for repo in collected:
        tasks.append(
            asyncio.create_task(
                sem_clone(repo["clone_url"], repo["name"], acq.output_dir)
            )
        )

    await asyncio.gather(*tasks)
    logger.info("Hoàn thành Giai đoạn 1 (Data Acquisition).")
