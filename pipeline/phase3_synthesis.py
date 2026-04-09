import os
import json
import asyncio
import aiohttp
import glob
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
try:
    from camoufox.async_api import Camoufox
except ImportError:
    Camoufox = None
from utils.logger import get_logger
from utils.state_manager import state_manager

logger = get_logger(__name__)

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API")

SYSTEM_PROMPT = """You are a senior expert in Static Analysis and Software Architecture.
Analyze the evolution history of a function to identify Code Smell signs, specifically Divergent Change or Shotgun Surgery.
Return a STRICT JSON object ONLY, NO backticks, NO markdown, NO extra text.
Schema exactly as:
{
  "Reasoning_Step_1": "string",
  "Reasoning_Step_2": "string",
  "Conclusion": "string",
  "Code_Smell_Detected": false,
  "Smell_Type": "Divergent Change | Shotgun Surgery | None"
}"""

class DeepSeekLabeler:
    def __init__(self, output_dir="ground_truth"):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)
        if not DEEPSEEK_API_KEY:
            logger.error("DEEPSEEK_API key is missing in .env")

    @retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, min=2, max=60), retry=retry_if_exception_type(Exception))
    async def get_teacher_explanation(self, session, item_data):
        # Chọn base_url tùy theo API provider. (Ví dụ: chính thức của deepseek là api.deepseek.com)
        url = "https://api.deepseek.com/chat/completions"
        headers = {
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json"
        }
        
        # Context compression
        input_str = json.dumps(item_data, ensure_ascii=False, separators=(",", ":"))
        
        payload = {
            "model": "deepseek-coder",
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Input Data: {input_str}"}
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.1,
            "max_tokens": 1024
        }
        
        async with session.post(url, headers=headers, json=payload, timeout=aiohttp.ClientTimeout(total=45)) as resp:
            resp.raise_for_status()
            data = await resp.json()
            return data["choices"][0]["message"]["content"]

class WebDeepSeekLabeler:
    def __init__(self, auth_file="google_auth.json"):
        self.auth_file = auth_file
        self.browser = None
        self.context = None
        self.page = None
        if not Camoufox:
            logger.error("Thư viện 'camoufox' chưa được cài đặt. Hãy chạy: pip install camoufox")

    async def init_browser(self):
        if self.browser: return
        
        logger.info("Initializing Camoufox Browser (Headless Mode)...")
        self.camou = Camoufox(headless=True, humanize=True)
        self.browser = await self.camou.start()
        
        storage_state = None
        if os.path.exists(self.auth_file):
            with open(self.auth_file, 'r') as f:
                storage_state = json.load(f)
        
        self.context = await self.browser.new_context(storage_state=storage_state)
        self.page = await self.context.new_page()
        
        await self.page.goto("https://chat.deepseek.com")
        await self.page.wait_for_load_state("networkidle")
        
        # Thiết lập ban đầu: Bật DeepThink, Tắt Search
        try:
            await self._toggle_feature("DeepThink", True)
            await self._toggle_feature("Search", False)
        except Exception as e:
            logger.warning(f"Không thể thiết lập toggle: {e}")

    async def _toggle_feature(self, text, enable):
        button = self.page.locator(f"div[role='button']:has-text('{text}')").first
        if await button.count() > 0:
            class_str = await button.get_attribute("class") or ""
            is_selected = "ds-toggle-button--selected" in class_str
            if (enable and not is_selected) or (not enable and is_selected):
                await button.click()
                await asyncio.sleep(0.5)

    async def get_teacher_explanation(self, item_data):
        # Đảm bảo trình duyệt đã sẵn sàng
        await self.init_browser()
        
        prompt = f"{SYSTEM_PROMPT}\n\nInput Data: {json.dumps(item_data, ensure_ascii=False)}"
        
        # Tìm ô nhập liệu
        textarea = self.page.locator("textarea").first
        if await textarea.count() == 0:
            textarea = self.page.locator("div[contenteditable='true']").first
        
        await textarea.click()
        await textarea.fill(prompt)
        
        # Gửi
        submit_button = self.page.get_by_role("button").filter(has=self.page.locator("svg")).last
        if await submit_button.count() == 0:
            submit_button = self.page.locator("button[type='submit']").first
        
        await submit_button.click()
        
        # Đợi phản hồi
        markdown_divs = self.page.locator(".ds-markdown")
        await markdown_divs.first.wait_for(state="visible", timeout=15000)
        
        content = ""
        stable_count = 0
        for _ in range(60): # Max 30s
            last_reply = markdown_divs.last
            curr_text = await last_reply.inner_text()
            if content == curr_text and len(curr_text) > 0:
                stable_count += 1
            else:
                content = curr_text
                stable_count = 0
            
            if stable_count >= 5:
                break
            await asyncio.sleep(0.5)
            
        return content

    async def close(self):
        if self.browser:
            await self.browser.close()
            await self.camou.stop()

async def process_method_file(session, labeler, repo_url, r_name, method_json_path, gt_out_dir, semaphore):
    filename = os.path.basename(method_json_path)
    out_path = os.path.join(gt_out_dir, filename)
    
    if os.path.exists(out_path):
        return True
        
    with open(method_json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    # Không có evolutions (do không thay đổi) -> không có code smell
    if not data.get("ev"):
        return True

    # Giới hạn số lượng token/request đồng thời để tránh Rate Limit Timeout
    async with semaphore:
        try:
            if isinstance(labeler, DeepSeekLabeler):
                raw_json_str = await labeler.get_teacher_explanation(session, data)
            else:
                raw_json_str = await labeler.get_teacher_explanation(data)
                
            # Xử lý text thô từ Web để lấy nội dung JSON
            # Thỉnh thoảng AI trên Web trả về kèm ```json ... ```
            clean_json = raw_json_str.strip()
            if "```json" in clean_json:
                clean_json = clean_json.split("```json")[1].split("```")[0].strip()
            elif "```" in clean_json:
                clean_json = clean_json.split("```")[1].split("```")[0].strip()
                
            parsed = json.loads(clean_json) # test JSON thuần túy
            
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(parsed, f, ensure_ascii=False, indent=4)
            return True
        except json.JSONDecodeError as e:
            logger.error(f"Lỗi Decode JSON từ DeepSeek ({filename}): {e}")
            return False
        except Exception as e:
            logger.error(f"Lỗi AI API file {filename} (Repo {r_name}): {e}")
            return False

async def run_phase3_synthesis(input_dir="method_evolutions", output_dir="ground_truth", mode="api"):
    repos = state_manager.get_pending_repos(3)
    if not repos:
        logger.info("Không có Repos nào chờ AI Phase 3.")
        return

    logger.info(f"Phase 3: Bắt đầu gán nhãn cho {len(repos)} repository bằng chế độ: {mode.upper()}")
    
    if mode == "web":
        labeler = WebDeepSeekLabeler()
        # Chế độ Web chỉ chạy 1 luồng duy nhất để tránh xung đột trình duyệt
        api_semaphore = asyncio.Semaphore(1)
        session = None # Không dùng aiohttp session cho Web
    else:
        labeler = DeepSeekLabeler(output_dir)
        api_semaphore = asyncio.Semaphore(10)
        session = aiohttp.ClientSession()

    try:
        if session:
            # Code cũ cho API
            for rp_idx, rp in enumerate(repos):
                repo_url, repo_name = rp
                repo_input = os.path.join(input_dir, repo_name)
                repo_output = os.path.join(output_dir, repo_name)
                
                if not os.path.exists(repo_input):
                    state_manager.update_phase(repo_url, 3, 'FAILED', "Thư mục input không tồn tại")
                    continue
                    
                os.makedirs(repo_output, exist_ok=True)
                files = glob.glob(os.path.join(repo_input, "*.json"))
                if not files:
                     state_manager.update_phase(repo_url, 3, 'DONE')
                     continue
                     
                logger.info(f"[{repo_name}] Tiến hành gọi DeepSeek API cho {len(files)} methods...")
                tasks = [asyncio.create_task(process_method_file(session, labeler, repo_url, repo_name, f, repo_output, api_semaphore)) for f in files]
                results = await asyncio.gather(*tasks)
                
                if all(results):
                    state_manager.update_phase(repo_url, 3, 'DONE')
                else:
                    fail_count = len(results) - sum(results)
                    state_manager.update_phase(repo_url, 3, 'FAILED', f"{fail_count} methods failed")
        else:
            # Chế độ Web (Tuần tự hoặc giới hạn Semaphore=1)
            for repo_url, repo_name in repos:
                repo_input = os.path.join(input_dir, repo_name)
                repo_output = os.path.join(output_dir, repo_name)
                os.makedirs(repo_output, exist_ok=True)
                
                files = glob.glob(os.path.join(repo_input, "*.json"))
                if not files:
                    state_manager.update_phase(repo_url, 3, 'DONE')
                    continue

                logger.info(f"[{repo_name}] Tiến hành gán nhãn Web (Camoufox) cho {len(files)} methods...")
                for f in files:
                    await process_method_file(None, labeler, repo_url, repo_name, f, repo_output, api_semaphore)
                
                state_manager.update_phase(repo_url, 3, 'DONE')
    finally:
        if session: await session.close()
        if mode == "web": await labeler.close()

    logger.info("Hoàn thành Giai đoạn 3 (AI Synthesis).")
