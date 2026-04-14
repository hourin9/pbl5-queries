import asyncio
import glob
import json
import os
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
METHOD_BODY_MAX_CHARS = 2000

# ---------------------------------------------------------------------------
# System Prompt — English, threshold-based, quantitative reasoning
# ---------------------------------------------------------------------------
SYSTEM_PROMPT_TEMPLATE = """You are a static analysis engine for detecting code smells in Java/C++ methods.
Given a method's source code, static metrics, and git evolution history, determine if it exhibits:

1. SHOTGUN SURGERY: When this method changes, many other files must also change.
   Detection criteria (ALL must be true):
   - fan_out >= [TH_FAN_OUT] (method calls many external methods)
   - total_unique_co_changed_classes >= [TH_CO_CLASSES] (method changes alongside distinct classes across its history)
   - commit_count >= [TH_COMMIT_MIN] (sufficient history to establish pattern)

2. DIVERGENT CHANGE: This method is modified frequently for many unrelated reasons.
   Detection criteria (ALL must be true):
   - commit_count >= [TH_COMMIT_COUNT] (sufficient change history)
   - distinct_concerns >= 3 (commits address 3+ different feature areas)
   - complexity_delta > 0 (complexity has grown over time)

INSTRUCTIONS:
1. Read the method body to understand its responsibilities and coupling.
2. To evaluate fan_out coupling, rely on the explicitly extracted 'external_calls' array rather than just reading the truncated method body.
3. Analyze commit messages to identify distinct concerns/feature areas
4. Compute ALL derived_metrics from the provided data
5. Compare each metric against its threshold
6.  - Assign a "final_smell_probability" per smell. Combine metrics fulfillment with semantic judgement.
    - If label is "none" but metrics are borderline or semantics are bad, confidence MUST be low (e.g. 0.4-0.6).
    - Analyze the 'file_path' and 'code' to determine the architectural context (Method role and Project type).
    - Provide a concise, imperative "suggested_refactor".
    - If label is "none" and NO thresholds are even close, suggested_refactor should be "No changes required". If it's a borderline case, suggest preventative refactoring.

Return ONLY a valid JSON object. NO markdown fences, NO extra text.
Schema:
{
  "derived_metrics": {
    "commit_count": <int>,
    "time_span_days": <int>,
    "change_frequency_monthly": <float, round to 2 decimals>,
    "total_insertions": <int>,
    "total_deletions": <int>,
    "avg_churn_per_commit": <float, round to 1 decimal>,
    "complexity_start": <int, first ev entry cxc>,
    "complexity_end": <int, last ev entry cxc>,
    "complexity_delta": <int, end - start>,
    "avg_files_per_commit": <float, round to 1 decimal>,
    "max_files_single_commit": <int>,
    "total_unique_co_changed_classes": <int, distinct classes changed alongside this method>,
    "distinct_concerns": <int, number of distinct feature areas from commit messages>,
    "concern_keywords": [<string>, ...]
  },
  "semantic_analysis": {
    "single_responsibility_violation": <bool>,
    "domain_coupling": "High" | "Medium" | "Low",
    "conflict_resolution": {
      "status": "Aligned" | "Metrics_Overstated" | "Metrics_Understated",
      "reason": <string, why metrics and semantics disagree or agree>
    },
    "architectural_context": {
      "method_role": "Controller" | "Service" | "Repository" | "Utility" | "Entity" | "Configuration" | "Other",
      "project_architecture": "Monolithic" | "Microservices" | "Multi-module Maven/Gradle" | "Other",
      "design_patterns_observed": [<string>, ...]
    }
  },
  "shotgun_surgery": {
    "metrics_score": <float 0.0-1.0>,
    "override_status": "No_Override" | "Semantic_Upgrade" | "Semantic_Downgrade",
    "final_smell_probability": <float 0.0-1.0>
  },
  "divergent_change": {
    "metrics_score": <float 0.0-1.0>,
    "override_status": "No_Override" | "Semantic_Upgrade" | "Semantic_Downgrade",
    "final_smell_probability": <float 0.0-1.0>
  },
  "final_decision": {
    "label": "none" | "shotgun_surgery" | "divergent_change",
    "confidence": <float 0.0-1.0>,
    "reasoning_chain": [
      "[Metrics Base]: <evaluate thresholds with values>",
      "[Semantic Deep-Dive]: <evaluate domain coupling, SRP, and architectural role>",
      "[Conflict Resolution]: <resolve mismatches between metrics and semantics>",
      "[Conclusion]: <final label and confidence justification>"
    ]
  },
  "suggested_refactor": <string, imperative structural guidance, NO code>
}"""


def get_dynamic_prompt(repo_dir):
    thresholds_path = os.path.join(repo_dir, "thresholds.json")
    if os.path.exists(thresholds_path):
        with open(thresholds_path, "r", encoding="utf-8") as f:
            th = json.load(f)
    else:
        th = {"fan_out": 7, "commit_count": 5, "co_classes": 5}
    
    prompt = SYSTEM_PROMPT_TEMPLATE
    prompt = prompt.replace("[TH_FAN_OUT]", str(th.get("fan_out", 7)))
    prompt = prompt.replace("[TH_CO_CLASSES]", str(th.get("co_classes", 5)))
    prompt = prompt.replace("[TH_COMMIT_COUNT]", str(th.get("commit_count", 5)))
    prompt = prompt.replace("[TH_COMMIT_MIN]", str(max(3, th.get("commit_count", 5) - 2)))
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
    if not pre_computed:
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
        "commit_messages": [e.get("msg", "")[:150] for e in unique_ev],
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
                await self.page.wait_for_url("**/chat/**", timeout=120000)
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

        await textarea.wait_for(state="visible", timeout=15000)
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
        return True

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        ai_input = build_ai_input(data)
        if not ai_input:
            return True

        if session is not None:
            raw_response = await labeler.get_teacher_explanation(session, ai_input, dynamic_prompt)
        else:
            raw_response = await labeler.get_teacher_explanation(ai_input, dynamic_prompt)

        if not raw_response or getattr(labeler, 'rate_limit_hit', False):
            return False

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

        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(parsed, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        return True

    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error from DeepSeek ({filename}): {e}")
        return False
    except Exception as e:
        logger.error(f"AI error for {filename} (Repo {repo_name}): {e}")
        return False


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
                # Web mode: sequential
                results = []
                total = len(files)
                for idx, f in enumerate(files, 1):
                    logger.info(f"[{repo_name}] [{idx}/{total}] Processing: {os.path.basename(f)}")
                    res = await process_method_file(None, labeler, repo_url, repo_name, f, repo_output, dynamic_prompt, None)
                    results.append(res)

            success = sum(1 for r in results if r)
            fail = len(results) - success

            if fail == 0:
                state_manager.update_phase(repo_url, 3, 'DONE', f"Labeled {success} methods")
            else:
                state_manager.update_phase(repo_url, 3, 'FAILED', f"{fail}/{len(results)} methods failed")

            logger.info(f"[{repo_name}] Phase 3 complete: {success} success, {fail} failed")
    finally:
        if session:
            await session.close()
        if mode == "web":
            await labeler.close()

    logger.info("Phase 3 (AI Synthesis) completed.")


async def save_auth_flow():
    """Standalone flow: open browser for manual login, save auth, exit."""
    labeler = WebDeepSeekLabeler()
    await labeler.init_browser(force_visible=True)
    await labeler.close()
    logger.info("Auth saved successfully. You can now run with --mode=web.")
