# Redesign Phase 3: AI Synthesis for Knowledge Distillation

## Goal

Redesign Phase 2 output + Phase 3 input/output + Phase 4 validation so that the generated dataset is optimal for training a small language model via knowledge distillation. The teacher (DeepSeek) must produce **structured, quantitative, threshold-based** reasoning enriched with semantic analysis of method body and commit history.

## User Review Required

> [!IMPORTANT]
> **Re-running Phase 2 required**: The Joern query and PyDriller worker both change. After implementation, you must delete `method_evolutions/` contents and reset Phase 2 status in the database to regenerate data with the new format.

> [!IMPORTANT]
> **Auth workflow for web mode**: On first run (or with `--save-auth`), the browser launches in **visible** mode for manual DeepSeek login. Session is saved to `data/auth_state.json`. Subsequent runs reuse this session in headless mode. If the session expires, re-run with `--save-auth`.

---

## Proposed Changes

### 1. Phase 2: Enrich Extraction Data

#### [MODIFY] [phase2_engineering.py](file:///home/lambda/lambda/code/pbl5-queries/pipeline/phase2_engineering.py)

##### 1a. Joern Query — Extract Full Method Body (lines 52-89)

Change `method.code` (which only returns the signature) to `method.code` combined with reading the full source lines. The Joern Scala query will be updated:

**Current** (line 80):
```scala
"code" -> method.code
```

**New**:
```scala
"code" -> {
  val fullCode = method.code
  if (fullCode.length > 3000) fullCode.substring(0, 3000) + "\n// ... truncated"
  else fullCode
}
```

> [!NOTE]
> In Joern's CPG, `method.code` for Java/C++ actually returns the **full method body** including the signature. The current output only showing the signature suggests the methods might be abstract/interface methods. For concrete methods, `method.code` should return the full body. If it doesn't, we fall back to reading source file lines using `method.lineNumber` and `method.lineNumberEnd`. The query will handle both cases.

**Updated Joern query** (replaces lines 52-89 entirely):

```scala
{
  importCode("$abs_repo_path", "$repo_name")
  import ujson._
  
  val allMethods = cpg.method
    .filterNot(m => m.name.startsWith("<") || m.filename.contains("test") || m.filename.contains("mock"))
    .filter(m => m.lineNumber.isDefined && m.lineNumberEnd.isDefined)
    .l

  val nodesData = allMethods.flatMap { method =>
    val lineStart = method.lineNumber.get
    val lineEnd = method.lineNumberEnd.get
    val loc = lineEnd - lineStart + 1
    
    if (loc >= 5) {
      // Get full method body - truncate to 3000 chars max
      val rawCode = method.code
      val methodBody = if (rawCode.length > 3000) rawCode.substring(0, 3000) + "\n// ... truncated" else rawCode
      
      Some(Obj(
        "id" -> method.id.toString, 
        "name" -> method.name, 
        "file_path" -> method.filename, 
        "features" -> Obj(
          "loc" -> loc, 
          "cyclomatic_complexity" -> (method.controlStructure.size + 1),
          "fan_in" -> method.caller.size, 
          "fan_out" -> method.callee.size, 
          "code" -> methodBody
        )
      ))
    } else None
  }
  
  os.write.over(os.Path("$tmp_json"), ujson.write(Obj("nodes" -> nodesData)))
  "DONE"
}
```

##### 1b. PyDriller Worker — Add `nf` field (lines 124-165)

Add `commit.files` (total files changed in that commit) to each evolution entry.

**Current** (lines 149-156):
```python
change = {
    "h": commit.hash[:8],
    "d": str(commit.author_date),
    "msg": commit.msg.strip(),
    "nd": commit.deletions,
    "ni": commit.insertions,
    "cxc": method.complexity,
}
```

**New**:
```python
change = {
    "h": commit.hash[:8],
    "d": str(commit.author_date),
    "msg": commit.msg.strip(),
    "nd": commit.deletions,
    "ni": commit.insertions,
    "nf": commit.files,                # total files changed in this commit
    "cxc": method.complexity,
}
```

##### 1c. Output JSON Format (unchanged structure, enriched content)

Each file in `method_evolutions/<repo>/<mid>.json`:
```json
{
  "mid": "107374184804",
  "sa": {
    "id": "107374184804",
    "name": "hasOperateNamespacePermission",
    "file_path": "apollo-portal/.../PermissionValidator.java",
    "features": {
      "loc": 15,
      "cyclomatic_complexity": 3,
      "fan_in": 1,
      "fan_out": 9,
      "code": "boolean hasOperateNamespacePermission(String appId, String env, ...) {\n  return rolePermissionService.check(...) || ...\n}"
    }
  },
  "ev": [
    {
      "h": "cd55a0dd",
      "d": "2017-02-28 17:44:44+08:00",
      "msg": "app's admin can create private namespace",
      "nd": 82, "ni": 204, "nf": 12, "cxc": 2
    }
  ]
}
```

---

### 2. Phase 3: Complete Rewrite

#### [MODIFY] [phase3_synthesis.py](file:///home/lambda/lambda/code/pbl5-queries/pipeline/phase3_synthesis.py)

The entire file will be rewritten. Below is the exact specification for every component.

##### 2a. Constants and Imports (lines 1-22)

```python
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
METHOD_BODY_MAX_CHARS = 2000  # Truncate method body sent to AI
```

##### 2b. System Prompt (replaces lines 24-34)

**Exact prompt text** (all English, threshold-based, with full method body analysis):

```python
SYSTEM_PROMPT = """You are a static analysis engine for detecting code smells in Java/C++ methods.
Given a method's source code, static metrics, and git evolution history, determine if it exhibits:

1. SHOTGUN SURGERY: When this method changes, many other files must also change.
   Detection criteria (ALL must be true):
   - fan_out >= 7 (method calls many external methods)
   - avg_files_per_commit >= 4 (commits touching this method also touch many files)
   - commit_count >= 3 (sufficient history to establish pattern)

2. DIVERGENT CHANGE: This method is modified frequently for many unrelated reasons.
   Detection criteria (ALL must be true):
   - commit_count >= 5 (sufficient change history)
   - distinct_concerns >= 3 (commits address 3+ different feature areas)
   - complexity_delta > 0 (complexity has grown over time)

INSTRUCTIONS:
1. Read the method body to understand its responsibilities and coupling
2. Analyze commit messages to identify distinct concerns/feature areas
3. Compute ALL derived_metrics from the provided data
4. Compare each metric against its threshold
5. Assign a confidence score (0.0 to 1.0) for each smell type
6. If both smells are detected, choose the one with higher confidence

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
    "distinct_concerns": <int, number of distinct feature areas from commit messages>,
    "concern_keywords": [<string>, ...]
  },
  "shotgun_surgery": {
    "score": <float 0.0-1.0>,
    "threshold_checks": {
      "fan_out_check": {"value": <int>, "threshold": 7, "passed": <bool>},
      "avg_files_check": {"value": <float>, "threshold": 4, "passed": <bool>},
      "commit_count_check": {"value": <int>, "threshold": 3, "passed": <bool>}
    },
    "detected": <bool>
  },
  "divergent_change": {
    "score": <float 0.0-1.0>,
    "threshold_checks": {
      "commit_count_check": {"value": <int>, "threshold": 5, "passed": <bool>},
      "distinct_concerns_check": {"value": <int>, "threshold": 3, "passed": <bool>},
      "complexity_delta_check": {"value": <int>, "threshold": 0, "passed": <bool>}
    },
    "detected": <bool>
  },
  "label": "none" | "shotgun_surgery" | "divergent_change",
  "confidence": <float 0.0-1.0>,
  "reasoning": [
    "Step 1: <describe what the method does based on its body>",
    "Step 2: <list the distinct concerns from commit messages>",
    "Step 3: <evaluate shotgun surgery thresholds with values>",
    "Step 4: <evaluate divergent change thresholds with values>",
    "Step 5: <final determination and confidence justification>"
  ]
}"""
```

##### 2c. Helper: Pre-compute Derived Metrics

This function computes metrics **before** sending to DeepSeek, so the AI can verify and augment rather than compute from scratch:

```python
def precompute_metrics(data):
    """Pre-compute derived metrics from raw method evolution data.
    Returns a dict suitable for including in the AI prompt, or None if data is insufficient."""
    ev = data.get("ev", [])
    sa = data.get("sa", {})
    features = sa.get("features", {})
    
    if not ev:
        return None
    
    # Deduplicate by commit hash (same commit can appear multiple times)
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
            # Handle timezone-aware datetime strings
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
    }
```

##### 2d. Helper: Build AI Input

Constructs the structured input sent to DeepSeek:

```python
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
        },
        "pre_computed": pre_computed,
        "commit_messages": [e.get("msg", "")[:150] for e in unique_ev],
    }
```

##### 2e. Class: DeepSeekLabeler (API mode)

```python
class DeepSeekLabeler:
    """Calls DeepSeek API (api.deepseek.com) for labeling."""
    
    def __init__(self):
        if not DEEPSEEK_API_KEY:
            logger.error("DEEPSEEK_API key is missing in .env")

    @retry(stop=stop_after_attempt(5),
           wait=wait_exponential(multiplier=1, min=2, max=60),
           retry=retry_if_exception_type(Exception))
    async def get_teacher_explanation(self, session, ai_input):
        url = "https://api.deepseek.com/chat/completions"
        headers = {
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json"
        }
        
        input_str = json.dumps(ai_input, ensure_ascii=False, separators=(",", ":"))
        
        payload = {
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
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
```

##### 2f. Class: WebDeepSeekLabeler (Camoufox mode)

Key changes:
- Uses `AsyncCamoufox` as async context manager properly
- Persists auth state to `data/auth_state.json`
- First run: visible browser for manual login → saves state
- Subsequent runs: headless with restored state
- Proper cleanup via `__aexit__`

```python
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
                # Wait for redirect to chat page after login
                await self.page.wait_for_url("**/chat/**", timeout=120000)
                await asyncio.sleep(2)  # Let cookies settle
                await self._save_auth()
                logger.info(f"✅ Auth state saved to {AUTH_STATE_FILE}")
            except Exception as e:
                logger.error(f"Login timeout or error: {e}")
                raise

    async def _save_auth(self):
        """Save browser auth state (cookies, localStorage) to file."""
        if self.context:
            state = await self.context.storage_state()
            os.makedirs(os.path.dirname(AUTH_STATE_FILE), exist_ok=True)
            with open(AUTH_STATE_FILE, "w") as f:
                json.dump(state, f)

    async def get_teacher_explanation(self, ai_input):
        """Send prompt to DeepSeek via browser and collect response."""
        await self.init_browser()
        
        prompt = f"{SYSTEM_PROMPT}\n\nAnalyze this method:\n{json.dumps(ai_input, ensure_ascii=False)}"
        
        # Navigate to new chat to avoid context pollution
        await self.page.goto("https://chat.deepseek.com/")
        await self.page.wait_for_load_state("networkidle")
        await asyncio.sleep(1)
        
        # Find textarea
        textarea = self.page.locator("textarea#chat-input")
        if await textarea.count() == 0:
            textarea = self.page.locator("textarea").first
        if await textarea.count() == 0:
            textarea = self.page.locator("div[contenteditable='true']").first
        
        await textarea.wait_for(state="visible", timeout=15000)
        await textarea.click()
        await textarea.fill(prompt)
        
        # Submit
        await self.page.keyboard.press("Enter")
        
        # Wait for response
        markdown_divs = self.page.locator(".ds-markdown")
        await markdown_divs.first.wait_for(state="visible", timeout=60000)
        
        # Poll until response stabilizes
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
```

##### 2g. Function: process_method_file

Processes a single method JSON file through the AI:

```python
async def process_method_file(session, labeler, repo_url, r_name, method_json_path, gt_out_dir, semaphore):
    """Process one method evolution file through the AI labeler."""
    filename = os.path.basename(method_json_path)
    out_path = os.path.join(gt_out_dir, filename)
    
    # Skip if already processed
    if os.path.exists(out_path):
        return True
    
    with open(method_json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    # Build structured AI input
    ai_input = build_ai_input(data)
    if not ai_input:
        logger.debug(f"Skipping {filename}: insufficient evolution data")
        return True  # Not an error, just no data
    
    async with semaphore:
        try:
            # Call AI
            if isinstance(labeler, DeepSeekLabeler):
                raw_response = await labeler.get_teacher_explanation(session, ai_input)
            else:
                raw_response = await labeler.get_teacher_explanation(ai_input)
            
            # Clean markdown fences if present
            clean = raw_response.strip()
            if "```json" in clean:
                clean = clean.split("```json")[1].split("```")[0].strip()
            elif "```" in clean:
                clean = clean.split("```")[1].split("```")[0].strip()
            
            # Parse and validate basic structure
            parsed = json.loads(clean)
            
            # Ensure required top-level keys exist
            required_keys = ["label", "confidence", "reasoning", 
                           "shotgun_surgery", "divergent_change", "derived_metrics"]
            missing = [k for k in required_keys if k not in parsed]
            if missing:
                logger.warning(f"[{r_name}] {filename}: Missing keys {missing}, saving anyway")
            
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(parsed, f, ensure_ascii=False, indent=2)
            return True
            
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error from DeepSeek ({filename}): {e}")
            return False
        except Exception as e:
            logger.error(f"AI error for {filename} (Repo {r_name}): {e}")
            return False
```

##### 2h. Function: run_phase3_synthesis

Orchestrates the Phase 3 execution:

```python
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
                state_manager.update_phase(repo_url, 3, 'DONE')
                continue
            
            logger.info(f"[{repo_name}] Processing {len(files)} methods via {mode.upper()}...")
            
            if session:
                # API mode: parallel with semaphore
                tasks = [
                    asyncio.create_task(
                        process_method_file(session, labeler, repo_url, repo_name, f, repo_output, api_semaphore)
                    ) for f in files
                ]
                results = await asyncio.gather(*tasks)
            else:
                # Web mode: sequential
                results = []
                for f in files:
                    res = await process_method_file(None, labeler, repo_url, repo_name, f, repo_output, api_semaphore)
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
```

---

### 3. Phase 4: Updated Validation

#### [MODIFY] [phase4_validation.py](file:///home/lambda/lambda/code/pbl5-queries/pipeline/phase4_validation.py)

##### 3a. New Validation Schema (replaces lines 17-27)

```python
SMELL_SCHEMA = {
    "type": "object",
    "properties": {
        "derived_metrics": {
            "type": "object",
            "properties": {
                "commit_count": {"type": "integer"},
                "time_span_days": {"type": "integer"},
                "change_frequency_monthly": {"type": "number"},
                "total_insertions": {"type": "integer"},
                "total_deletions": {"type": "integer"},
                "avg_churn_per_commit": {"type": "number"},
                "complexity_start": {"type": "integer"},
                "complexity_end": {"type": "integer"},
                "complexity_delta": {"type": "integer"},
                "avg_files_per_commit": {"type": "number"},
                "max_files_single_commit": {"type": "integer"},
                "distinct_concerns": {"type": "integer"},
                "concern_keywords": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["commit_count", "distinct_concerns", "avg_files_per_commit"]
        },
        "shotgun_surgery": {
            "type": "object",
            "properties": {
                "score": {"type": "number", "minimum": 0, "maximum": 1},
                "detected": {"type": "boolean"},
                "threshold_checks": {"type": "object"}
            },
            "required": ["score", "detected"]
        },
        "divergent_change": {
            "type": "object",
            "properties": {
                "score": {"type": "number", "minimum": 0, "maximum": 1},
                "detected": {"type": "boolean"},
                "threshold_checks": {"type": "object"}
            },
            "required": ["score", "detected"]
        },
        "label": {
            "type": "string",
            "enum": ["none", "shotgun_surgery", "divergent_change"]
        },
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "reasoning": {"type": "array", "items": {"type": "string"}}
    },
    "required": ["label", "confidence", "shotgun_surgery", "divergent_change"]
}
```

##### 3b. Updated Logic Validation (replaces lines 29-48)

```python
def validate_dataset_schema(gt_file_path):
    with open(gt_file_path, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
            validate(instance=data, schema=SMELL_SCHEMA)
            
            # Logic checks
            label = data.get("label", "none")
            ss_detected = data.get("shotgun_surgery", {}).get("detected", False)
            dc_detected = data.get("divergent_change", {}).get("detected", False)
            confidence = data.get("confidence", 0)
            
            # Label must match detected flags
            if label == "shotgun_surgery" and not ss_detected:
                return False, "Logic: label is shotgun_surgery but detected=false"
            if label == "divergent_change" and not dc_detected:
                return False, "Logic: label is divergent_change but detected=false"
            if label == "none" and (ss_detected or dc_detected):
                return False, "Logic: label is none but a smell was detected"
            
            # Confidence sanity check
            if label != "none" and confidence < 0.3:
                return False, f"Logic: smell detected but confidence too low ({confidence})"
            
            return True, data
        except json.JSONDecodeError as e:
            return False, f"JSON decode error: {e}"
        except ValidationError as e:
            return False, f"Schema invalid: {e.message}"
```

---

### 4. Updated build_training_sample.py

#### [MODIFY] [build_training_sample.py](file:///home/lambda/lambda/code/pbl5-queries/build_training_sample.py)

The training sample format changes to support the new input/output schemas.

```python
def build_training_sample(input_json: dict, output_json: dict = None) -> dict:
    """Build a training sample for knowledge distillation.
    
    Input: raw method evolution data from method_evolutions/
    Output: AI-generated label from ground_truth/
    
    The sample format is: {system, instruction, output}
    - system: the system prompt (same as used during labeling)
    - instruction: the structured AI input (method body + metrics + commit messages)
    - output: the full AI response (label + scores + reasoning)
    """
    from pipeline.phase3_synthesis import SYSTEM_PROMPT, build_ai_input
    
    ai_input = build_ai_input(input_json)
    if not ai_input:
        return None
    
    input_str = json.dumps(ai_input, ensure_ascii=False, separators=(",", ":"))
    
    sample = {
        "system": SYSTEM_PROMPT,
        "instruction": f"Analyze this method:\n{input_str}",
        "output": "",
    }
    if output_json is not None:
        sample["output"] = json.dumps(
            output_json, ensure_ascii=False, separators=(",", ":")
        )
    return sample
```

---

### 5. main.py Updates

#### [MODIFY] [main.py](file:///home/lambda/lambda/code/pbl5-queries/main.py)

Add `--save-auth` argument:

```python
parser.add_argument("--save-auth", action="store_true",
                    help="Open browser for manual DeepSeek login, save auth state, then exit")
```

Add handler before pipeline phases:

```python
if args.save_auth:
    from pipeline.phase3_synthesis import save_auth_flow
    await save_auth_flow()
    return
```

---

## File Change Summary

| File | Action | Description |
|------|--------|-------------|
| `pipeline/phase2_engineering.py` | MODIFY | Add `nf` to PyDriller output, ensure full method body from Joern |
| `pipeline/phase3_synthesis.py` | REWRITE | New prompt, new I/O schema, auth persistence, pre-computed metrics |
| `pipeline/phase4_validation.py` | MODIFY | New schema validation, updated logic checks |
| `build_training_sample.py` | MODIFY | Use new `build_ai_input()` and `SYSTEM_PROMPT` from phase3 |
| `main.py` | MODIFY | Add `--save-auth` CLI flag |

## Decisions Already Made (No Questions Needed)

1. **Deduplication**: Evolution entries will be deduplicated by commit hash before computing metrics and before sending to AI.
2. **Method body limit**: 2000 chars sent to AI (Joern stores up to 3000 chars, we truncate further for token efficiency).
3. **Thresholds**: Shotgun Surgery (fan_out≥7, avg_files≥4, commits≥3), Divergent Change (commits≥5, concerns≥3, complexity_delta>0). These are starting points; the model will learn nuances.
4. **Auth file location**: `data/auth_state.json` (inside the existing `data/` directory).
5. **Cleanup**: `AsyncCamoufox.__aexit__` handles both browser close and Playwright cleanup.

## Verification Plan

### Automated Tests
```bash
# 1. Reset database and re-run Phase 2
rm -rf method_evolutions/apollo
sqlite3 data/state.db "UPDATE repo_state SET phase2_status='PENDING', phase3_status='PENDING', phase4_status='PENDING'"

# 2. Verify Phase 2 output has new fields
uv run main.py --mode=api
cat method_evolutions/apollo/*.json | python3 -c "import sys,json; d=json.load(sys.stdin); print('nf' in d['ev'][0])"

# 3. Verify Phase 3 output matches new schema
cat ground_truth/apollo/*.json | python3 -m json.tool

# 4. Verify final dataset
cat dataset_output/final_dataset.jsonl | head -1 | python3 -m json.tool
```

### Manual Verification
- Inspect 5 samples from `ground_truth/` to ensure:
  - `reasoning` steps reference actual metrics (not vague)
  - `threshold_checks` values match `derived_metrics`
  - `label` is consistent with detection flags
  - `confidence` correlates with how many thresholds were exceeded
