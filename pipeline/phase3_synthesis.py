import asyncio
import glob
import json
import os
import random
from datetime import datetime

import aiohttp
from tenacity import (retry, retry_if_exception_type, stop_after_attempt,
                      wait_exponential)

try:
    from camoufox import AsyncCamoufox
except ImportError:
    AsyncCamoufox = None

from utils.logger import get_logger
from utils.state_manager import state_manager

logger = get_logger(__name__)

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API")
AUTH_STATE_FILE = "data/auth_state.json"
METHOD_BODY_MAX_CHARS = 8000

# ---------------------------------------------------------------------------
# System Prompt — English, threshold-based, quantitative reasoning
# ---------------------------------------------------------------------------
SYSTEM_PROMPT_TEMPLATE = """You are a Senior Software Architectural Analyst. Your objective is to perform a multidimensional evaluation of Java/C++ methods to identify architectural anti-patterns, specifically focusing on Shotgun Surgery and Divergent Change.

### 1. THEORETICAL FRAMEWORK:
*   **SHOTGUN SURGERY (Scattered Functionality):** A manifestation of Poor Modularity where a modification to a single logical requirement necessitates synchronized changes across multiple disjoint software components. 
    *   *E.g.*: A modification in the "Payment Gateway" logic forces updates in 25 disparate Controller, Service, and Repository classes.
*   **DIVERGENT CHANGE (Tangled Responsibilities):** A violation of the Single Responsibility Principle (SRP), where a single method/module acts as an "Incoherent Hub" for multiple domain concerns. 
    *   *E.g.*: A method `processTransaction` is modified for "Interest Rate Calculation" in one commit and "User Notification Formatting" in another, indicating a lack of internal cohesion.

### 2. HEURISTIC ANALYSIS CONSTRAINTS:
1.  **Quantitative-Qualitative Correlation**: Perform a first-order comparison of Actual Metrics (V) against established Repository-Specific Thresholds (T): [THRESHOLDS].
2.  **Architectural Contextualization**: Deduce the Layered Position (e.g., Domain Service, Infrastructure Adapter, Web Controller) to calibrate the expected Fan-out and Fan-in density.
3.  **Conflict Resolution (Critical)**: Address "Metrics-Semantics Mismatch". 
    *   *E.g.*: A high `total_unique_co_changed_classes` might be a "False Positive" caused by a monolithic library version upgrade rather than architectural coupling.

### 3. FORMALIZED JSON SCHEMA:
{
  "semantic_analysis": {
    "architectural_roles": ["Primary responsibilities identified via code and commit semantics"],
    "cohesion_assessment": "High" | "Medium" | "Low",
    "is_srp_violated": <bool>,
    "architectural_context": {
      "layer": "Controller" | "Service" | "Infrastructure" | "Domain" | "Other",
      "pattern": "Layered" | "Microservices" | "Hexagonal" | "Monolithic"
    },
    "conflict_resolution": "Justification for overriding metrics via semantic design principles"
  },
  "final_decision": {
    "label": "none" | "shotgun_surgery" | "divergent_change",
    "confidence": <float>,
    "reasoning_chain": [
      "[Metric Comparison]: Differential analysis of actual stats vs Thresholds: [THRESHOLDS].",
      "[Design Integrity]: Analysis of Responsibility Cohesion and Ripple Effect probability.",
      "[Conclusion]: Final synthesis and validation of the identified anti-pattern."
    ]
  },
  "suggested_refactor": "Formal restructuring command (e.g., Apply Strategy Pattern to decouple Domain logic)"
}

ONLY VALID JSON. NO MARKDOWN. NO EXPLANATIONS."""


def get_dynamic_prompt(repo_dir):
    thresholds_path = os.path.join(repo_dir, "thresholds.json")
    if os.path.exists(thresholds_path):
        with open(thresholds_path, "r", encoding="utf-8") as f:
            th = json.load(f)
    else:
        th = {"fan_out": 7, "commit_count": 5, "co_classes": 5}
    
    # Tạo chuỗi mô tả các ngưỡng thực tế cho repo này
    th_str = f"fan_out: {th.get('fan_out', 7)}, co_changed_classes: {th.get('co_classes', 5)}, commit_count: {th.get('commit_count', 5)}"
    
    prompt = SYSTEM_PROMPT_TEMPLATE.replace("[THRESHOLDS]", th_str)
    return prompt

# ---------------------------------------------------------------------------
# Helpers: Pre-compute metrics & build AI input
# ---------------------------------------------------------------------------

def precompute_metrics(data):
    """Pre-compute derived metrics from raw method evolution data.
    Returns a dict suitable for including in the AI prompt, or None if data is insufficient."""
    ev = data.get("ev", [])
    sa = data.get("sa", {})
    features = sa.get("features", {})

    if not ev:
        return None

    # Deduplicate by commit hash
    seen_hashes = set()
    unique_ev = []
    for e in ev:
        if e["h"] not in seen_hashes:
            seen_hashes.add(e["h"])
            unique_ev.append(e)
    ev = unique_ev

    commit_count = len(ev)
    total_ins = sum(e.get("ni", 0) for e in ev)
    total_del = sum(e.get("nd", 0) for e in ev)

    # Parse dates for time span
    dates = []
    for e in ev:
        try:
            d = e["d"]
            if "+" in d or d.endswith("Z"):
                dt = datetime.fromisoformat(d.replace("Z", "+00:00"))
            else:
                dt = datetime.fromisoformat(d)
            dates.append(dt)
        except Exception:
            pass

    if len(dates) >= 2:
        dates.sort()
        time_span = (dates[-1] - dates[0]).days or 1
    else:
        time_span = 1

    complexity_values = [e.get("cxc", 0) for e in ev]
    avg_files = sum(e.get("nf", 1) for e in ev) / commit_count
    max_files = max(e.get("nf", 1) for e in ev)

    unique_co_classes = set()
    for e in ev:
        if "co_classes" in e:
            unique_co_classes.update(e["co_classes"])

    return {
        "commit_count": commit_count,
        "time_span_days": time_span,
        "change_frequency_monthly": round(commit_count / time_span * 30, 2),
        "total_insertions": total_ins,
        "total_deletions": total_del,
        "avg_churn_per_commit": round((total_ins + total_del) / commit_count, 1),
        "complexity_start": complexity_values[0],
        "complexity_end": complexity_values[-1],
        "complexity_delta": complexity_values[-1] - complexity_values[0],
        "avg_files_per_commit": round(avg_files, 1),
        "max_files_single_commit": max_files,
        "total_unique_co_changed_classes": len(unique_co_classes)
    }


def build_ai_input(data):
    """Build the structured input dict sent to DeepSeek."""
    sa = data.get("sa", {})
    features = sa.get("features", {})
    ev = data.get("ev", [])

    # Deduplicate evolution entries by commit hash
    seen = set()
    unique_ev = []
    for e in ev:
        if e["h"] not in seen:
            seen.add(e["h"])
            unique_ev.append(e)

    # Truncate method body
    method_body = features.get("code", "")
    if len(method_body) > METHOD_BODY_MAX_CHARS:
        method_body = method_body[:METHOD_BODY_MAX_CHARS] + "\n// ... truncated"

    pre_computed = precompute_metrics(data)
    if not pre_computed or pre_computed.get("commit_count", 0) < 3:
        # Point 1: Skip poverty git history
        return None

    return {
        "method_name": sa.get("name", "unknown"),
        "file_path": sa.get("file_path", "unknown"),
        "method_body": method_body,
        "static_analysis": {
            "loc": features.get("loc", 0),
            "cyclomatic_complexity": features.get("cyclomatic_complexity", 0),
            "fan_in": features.get("fan_in", 0),
            "fan_out": features.get("fan_out", 0),
            "external_calls": features.get("external_calls", []),
        },
        "pre_computed": pre_computed,
        "commit_messages": [e.get("msg", "")[:500] for e in unique_ev],
    }


# ---------------------------------------------------------------------------
# Labeler: DeepSeek API mode
# ---------------------------------------------------------------------------

class DeepSeekLabeler:
    """Calls DeepSeek API (api.deepseek.com) for labeling."""

    def __init__(self):
        if not DEEPSEEK_API_KEY:
            logger.error("DEEPSEEK_API key is missing in .env")

    @retry(stop=stop_after_attempt(5),
           wait=wait_exponential(multiplier=1, min=2, max=60),
           retry=retry_if_exception_type(Exception))
    async def get_teacher_explanation(self, session, ai_input, dynamic_prompt):
        url = "https://api.deepseek.com/chat/completions"
        headers = {
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json"
        }

        input_str = json.dumps(ai_input, ensure_ascii=False, separators=(",", ":"))

        payload = {
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": dynamic_prompt},
                {"role": "user", "content": f"Analyze this method:\n{input_str}"}
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.1,
            "max_tokens": 2048
        }

        async with session.post(url, headers=headers, json=payload,
                                timeout=aiohttp.ClientTimeout(total=60)) as resp:
            resp.raise_for_status()
            data = await resp.json()
            return data["choices"][0]["message"]["content"]


# ---------------------------------------------------------------------------
# Labeler: Camoufox Web mode with auth persistence
# ---------------------------------------------------------------------------

class WebDeepSeekLabeler:
    """Uses Camoufox browser to interact with chat.deepseek.com for labeling."""

    def __init__(self):
        self.camou = None
        self.browser = None
        self.context = None
        self.page = None
        if not AsyncCamoufox:
            logger.error("Library 'camoufox' is not installed. Run: pip install camoufox")

    async def init_browser(self, force_visible=False):
        """Initialize browser. If auth state exists, run headless. Otherwise visible for login."""
        if self.browser:
            return

        has_auth = os.path.exists(AUTH_STATE_FILE) and not force_visible
        headless = has_auth and not force_visible

        logger.info(f"Initializing Camoufox ({'headless' if headless else 'visible'} mode)...")
        self.camou = AsyncCamoufox(headless=headless, humanize=True)
        self.browser = await self.camou.start()

        # Create context with or without saved auth
        if has_auth:
            self.context = await self.browser.new_context(
                storage_state=AUTH_STATE_FILE
            )
        else:
            self.context = await self.browser.new_context()

        self.page = await self.context.new_page()
        await self.page.goto("https://chat.deepseek.com/")
        await self.page.wait_for_load_state("networkidle")

        if not has_auth:
            logger.info("⏳ Please log in to DeepSeek in the browser window...")
            logger.info("   Waiting up to 2 minutes for login to complete...")
            try:
                await self.page.wait_for_url("https://chat.deepseek.com/**", timeout=120000)
                await asyncio.sleep(2)
                await self._save_auth()
                logger.info(f"✅ Auth state saved to {AUTH_STATE_FILE}")
            except Exception as e:
                logger.error(f"Login timeout or error: {e}")
                raise

    async def _save_auth(self):
        """Save browser auth state (cookies, localStorage) to file."""
        if self.context:
            state = await self.context.storage_state()
            os.makedirs(os.path.dirname(AUTH_STATE_FILE) or ".", exist_ok=True)
            with open(AUTH_STATE_FILE, "w") as f:
                json.dump(state, f)

    async def get_teacher_explanation(self, ai_input, dynamic_prompt):
        """Send prompt to DeepSeek via browser and collect response."""
        await self.init_browser()

        prompt = f"{dynamic_prompt}\n\nAnalyze this method:\n{json.dumps(ai_input, ensure_ascii=False)}"

        # Chỉ navigate nếu không ở trang chat
        if self.page.url != "https://chat.deepseek.com/":
            logger.debug("Navigating to DeepSeek home...")
            await self.page.goto("https://chat.deepseek.com/")
            await self.page.wait_for_load_state("networkidle")
            await asyncio.sleep(1)

        # Tìm textarea
        textarea = self.page.locator("textarea#chat-input")
        if await textarea.count() == 0:
            textarea = self.page.locator("textarea").first
        if await textarea.count() == 0:
            textarea = self.page.locator("div[contenteditable='true']").first

        await textarea.wait_for(state="visible", timeout=60000)
        await textarea.click()
        logger.debug("Filling prompt...")
        await textarea.fill(prompt)

        # Submit
        await self.page.keyboard.press("Enter")

        # Wait for response
        try:
            # Chờ 1 trong 2: markdown hiện ra hoặc toast lỗi hiện ra
            await asyncio.wait_for(
                asyncio.gather(
                    self.page.wait_for_selector(".ds-markdown", timeout=60000),
                    return_exceptions=False
                ),
                timeout=60
            )
        except asyncio.TimeoutError:
            # Kiểm tra xem có Toast lỗi Rate Limit không
            toast = self.page.locator("div:has-text('Too many requests'), div:has-text('Please try again')")
            if await toast.count() > 0:
                logger.error("🛑 Web Rate-limit hit! Sleeping for 5 minutes...")
                self.rate_limit_hit = True
                await asyncio.sleep(300)
                return None
            return None

        # Reset rate limit flag if success
        self.rate_limit_hit = False
        
        # Poll until response stabilizes
        markdown_divs = self.page.locator(".ds-markdown")
        content = ""
        stable_count = 0
        for _ in range(120):  # Max 60s
            last_reply = markdown_divs.last
            curr_text = await last_reply.inner_text()
            if content == curr_text and len(curr_text) > 10:
                stable_count += 1
            else:
                content = curr_text
                stable_count = 0

            if stable_count >= 6:
                break
            await asyncio.sleep(0.5)

        return content

    async def close(self):
        """Save auth and clean up browser resources."""
        try:
            if self.context:
                await self._save_auth()
        except Exception:
            pass
        if self.camou:
            await self.camou.__aexit__(None, None, None)
            self.camou = None
            self.browser = None
            self.context = None
            self.page = None


# ---------------------------------------------------------------------------
# Process a single method file
# ---------------------------------------------------------------------------

async def process_method_file(session, labeler, repo_url, repo_name, file_path, output_dir, dynamic_prompt, semaphore=None):
    if semaphore:
        async with semaphore:
            return await _do_process(session, labeler, repo_url, repo_name, file_path, output_dir, dynamic_prompt)
    else:
        return await _do_process(session, labeler, repo_url, repo_name, file_path, output_dir, dynamic_prompt)

async def _do_process(session, labeler, repo_url, repo_name, file_path, output_dir, dynamic_prompt):
    filename = os.path.basename(file_path)
    # Check if file already exists in any sub-directory to avoid re-processing
    exist_check = [
        os.path.join(output_dir, "smells", filename),
        os.path.join(output_dir, "no_smells", filename)
    ]
    if any(os.path.exists(p) for p in exist_check):
        return "skipped_exists"

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        ai_input = build_ai_input(data)
        if not ai_input:
            return "skipped_poverty"

        if session is not None:
            raw_response = await labeler.get_teacher_explanation(session, ai_input, dynamic_prompt)
        else:
            raw_response = await labeler.get_teacher_explanation(ai_input, dynamic_prompt)

        if not raw_response or getattr(labeler, 'rate_limit_hit', False):
            return "failed"

        # Clean markdown fences if present
        clean = raw_response.strip()
        if "```json" in clean:
            clean = clean.split("```json")[1].split("```")[0].strip()
        elif "```" in clean:
            clean = clean.split("```")[1].split("```")[0].strip()

        # Parse and validate basic structure
        parsed = json.loads(clean)

        # Determine sub-directory based on label
        label = parsed.get("final_decision", {}).get("label", "none")
        sub_dir = "smells" if label in ["shotgun_surgery", "divergent_change"] else "no_smells"
        final_repo_output = os.path.join(output_dir, sub_dir)
        os.makedirs(final_repo_output, exist_ok=True)
        
        out_path = os.path.join(final_repo_output, filename)
        abs_out_path = os.path.abspath(out_path)

        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(parsed, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
            
        logger.info(f"✨ [SUCCESS] File saved to: {abs_out_path}")
        return "written"

    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error from DeepSeek ({filename}): {e}")
        return "failed"
    except Exception as e:
        logger.error(f"AI error for {filename} (Repo {repo_name}): {e}")
        return "failed"


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

async def run_phase3_synthesis(input_dir="method_evolutions", output_dir="ground_truth", mode="api"):
    repos = state_manager.get_pending_repos(3)
    if not repos:
        logger.info("No repositories pending for Phase 3.")
        return

    logger.info(f"Phase 3: Labeling {len(repos)} repositories using mode: {mode.upper()}")

    if mode == "web":
        labeler = WebDeepSeekLabeler()
        api_semaphore = asyncio.Semaphore(1)
        session = None
    else:
        labeler = DeepSeekLabeler()
        api_semaphore = asyncio.Semaphore(10)
        session = aiohttp.ClientSession()

    try:
        for repo_url, repo_name in repos:
            repo_input = os.path.join(input_dir, repo_name)
            repo_output = os.path.join(output_dir, repo_name)

            if not os.path.exists(repo_input):
                state_manager.update_phase(repo_url, 3, 'FAILED', "Input directory missing")
                continue

            os.makedirs(repo_output, exist_ok=True)
            files = glob.glob(os.path.join(repo_input, "*.json"))
            if not files:
                logger.warning(f"[{repo_name}] Không tìm thấy file metrics để dán nhãn. Kiểm tra Phase 2.")
                continue
                
            dynamic_prompt = get_dynamic_prompt(repo_input)

            logger.info(f"[{repo_name}] Processing {len(files)} methods via {mode.upper()} with dynamic prompt...")

            if session:
                # API mode: parallel with semaphore
                tasks = [
                    asyncio.create_task(
                        process_method_file(session, labeler, repo_url, repo_name, f, repo_output, dynamic_prompt, api_semaphore)
                    ) for f in files
                ]
                results = await asyncio.gather(*tasks)
            else:
                # Web mode: Parallel browsers worker pool
                WEB_PARALLEL_BROWSERS = 1  # Giảm xuống 1 để đảm bảo máy không bị Lag/OOM và ghi file chuẩn xác
                total = len(files)
                results = []
                
                logger.info(f"[{repo_name}] Khởi tạo {WEB_PARALLEL_BROWSERS} trình duyệt Camoufox song song...")
                
                labelers = [WebDeepSeekLabeler() for _ in range(WEB_PARALLEL_BROWSERS)]
                for lbl in labelers:
                    await lbl.init_browser()
                
                queue = asyncio.Queue()
                for f in files:
                    queue.put_nowait(f)
                
                async def worker(worker_id, lbl):
                    worker_res = []
                    while not queue.empty():
                        f = await queue.get()
                        current_idx = total - queue.qsize()
                        logger.info(f"[{repo_name}] [Browser {worker_id}] [{current_idx}/{total}] Processing: {os.path.basename(f)}")
                        res = await process_method_file(None, lbl, repo_url, repo_name, f, repo_output, dynamic_prompt, None)
                        worker_res.append(res)
                        queue.task_done()
                        
                        # CHỈ NGHỈ NGẮN NẾU THỰC SỰ CÓ GỌI DEEPSEEK, TRÁNH LÃNG PHÍ THỜI GIAN VỚI CÁC FILE BỊ SKIP
                        if res not in ["skipped_poverty", "skipped_exists"]:
                            await asyncio.sleep(random.uniform(5, 10)) # Tăng delay một chút cho an toàn
                    return worker_res

                worker_tasks = [asyncio.create_task(worker(i+1, labelers[i])) for i in range(WEB_PARALLEL_BROWSERS)]
                worker_outputs = await asyncio.gather(*worker_tasks)
                
                # Gộp kết quả từ các worker
                for out in worker_outputs:
                    results.extend(out)

                for lbl in labelers:
                    await lbl.close()

            # Đếm số lượng files THỰC SỰ ĐƯỢC LƯU TRONG THƯ MỤC ground_truth/...
            smells_dir = os.path.join(repo_output, "smells")
            no_smells_dir = os.path.join(repo_output, "no_smells")
            smells_count = len(glob.glob(os.path.join(smells_dir, "*.json"))) if os.path.exists(smells_dir) else 0
            no_smells_count = len(glob.glob(os.path.join(no_smells_dir, "*.json"))) if os.path.exists(no_smells_dir) else 0
            actual_saved = smells_count + no_smells_count

            skipped_poverty = sum(1 for r in results if r == "skipped_poverty")
            fail = sum(1 for r in results if r == "failed")
            
            # Nếu repo này có những method đã thành công hoặc bị loại do cơ chế hợp lý, vẫn duyệt qua là DONE
            if actual_saved > 0 or skipped_poverty > 0:
                status_msg = f"Saved {actual_saved}/{len(files)} methods"
                if skipped_poverty > 0:
                    status_msg += f" (Skipped {skipped_poverty} <3 commits)"
                if fail > 0:
                    status_msg += f" (Failed {fail})"
                state_manager.update_phase(repo_url, 3, 'DONE', status_msg)
            else:
                state_manager.update_phase(repo_url, 3, 'FAILED', f"All {len(files)} methods failed (or saved 0)")

            logger.info(f"[{repo_name}] Phase 3 complete: Saved {actual_saved}, Skipped (<3 commits) {skipped_poverty}, Failed {fail}")

    finally:
        if session:
            await session.close()

    logger.info("Phase 3 (AI Synthesis) completed.")


async def save_auth_flow():
    """Standalone flow: open browser for manual login, save auth, exit."""
    labeler = WebDeepSeekLabeler()
    await labeler.init_browser(force_visible=True)
    await labeler.close()
    logger.info("Auth saved successfully. You can now run with --mode=web.")
