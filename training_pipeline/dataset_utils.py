import json
import random
import copy
import re
from datasets import Dataset

ALT_INSTRUCTIONS = [
    # 1. Phong cách Chuyên gia Kiến trúc (Architecture Expert)
    """Act as a Senior Software Architect. Your goal is to perform a structural audit on the provided Java/C++ method.
Analyze the source code, static metrics, and evolution history to identify two specific architectural smells:
- SHOTGUN SURGERY: Occurs when a change in this method forces ripples across many external classes (Requires: fan_out >= [TH_FAN_OUT], co_changed_classes >= [TH_CO_CLASSES], commit_count >= [TH_COMMIT_MIN]).
- DIVERGENT CHANGE: Occurs when the method is a 'God Method' modified for too many unrelated reasons (Requires: commit_count >= [TH_COMMIT_COUNT], distinct_concerns >= 3, complexity_delta > 0).

Evaluate the 'external_calls' for coupling and commit logs for concern scattering. Provide derived metrics, a semantic deep-dive, and a refactoring plan.
Output format: Strictly a single JSON object following the established schema.""",

    # 2. Phong cách Máy phân tích dữ liệu (Data-Driven Analyzer)
    """You are an AI-powered static analysis tool. Process the following method data to detect design violations.
Criteria for SHOTGUN SURGERY: (fan_out >= [TH_FAN_OUT]) AND (total_unique_co_changed_classes >= [TH_CO_CLASSES]) AND (commit_count >= [TH_COMMIT_MIN]).
Criteria for DIVERGENT CHANGE: (commit_count >= [TH_COMMIT_COUNT]) AND (distinct_concerns >= 3) AND (complexity_delta > 0).

Instructions:
1. Parse the method body and external_calls.
2. Cross-reference metrics against thresholds.
3. Identify distinct feature areas in commit messages.
4. Resolve conflicts where metrics might be overstated due to global refactors.
Return ONLY a valid JSON object. No prose, no markdown.""",

    # 3. Phong cách Hướng dẫn quy trình (Process-Oriented)
    """Follow this protocol to evaluate code smells in the given Java/C++ snippet:
Step 1: Extract metrics from 'pre_computed' and 'static_analysis'.
Step 2: Calculate all derived_metrics (churn, frequency, complexity delta).
Step 3: Check SHOTGUN SURGERY: Does the method have high coupling and frequent co-changes?
Step 4: Check DIVERGENT CHANGE: Is the method growing in complexity due to unrelated feature requests?
Step 5: Synthesize a reasoning chain to justify the final label and confidence score.

Output Requirement: A raw JSON object containing derived_metrics, semantic_analysis, shotgun_surgery, divergent_change, final_decision, and suggested_refactor.""",

    # 4. Phong cách Thẩm định Code (Code Auditor)
    """Perform a technical audit on the method below. Focus on coupling and cohesion.
Target Smells:
- Shotgun Surgery (High fan-out + High co-change count).
- Divergent Change (High change frequency + Multiple concerns).

Compare the extracted data against thresholds [TH_FAN_OUT, TH_CO_CLASSES, TH_COMMIT_MIN, TH_COMMIT_COUNT]. Use 'external_calls' to verify coupling intensity.
If the metrics meet thresholds but the semantics show a stable configuration or a global version upgrade, downgrade the smell probability.
Return a JSON object only.""",

    # 5. Phong cách Kiểm thử Tự động (Automated Testing Agent)
    """Execute code smell detection on the input method using git history and static metrics.
Metrics to compute: avg_churn_per_commit, change_frequency_monthly, and complexity_delta.
Threshold validation:
- Label as 'shotgun_surgery' if metrics for fan_out and co-changes are satisfied.
- Label as 'divergent_change' if metrics for commit count and concern keywords are satisfied.

Provide a concise refactoring suggestion if a smell is detected, otherwise suggest 'No changes required'.
Strictly return a JSON object.""",

    # 6. Phong cách Chuyên gia Bảo trì (Maintainability Specialist)
    """Evaluate the maintainability of this method. We are looking for Shotgun Surgery and Divergent Change.
Method Analysis: Use 'method_body' and 'external_calls'.
History Analysis: Use 'pre_computed' and 'commit_messages'.
Logic: A method is smells only if ALL metrics in its category meet or exceed thresholds. Use semantic judgement to resolve borderline cases.
Response: JSON format. Include architectural_context (method_role and project_architecture).""",

    # 7. Phong cách Ngắn gọn (Minimalist / Direct)
    """Analyze the provided code and metrics for Shotgun Surgery and Divergent Change.
Input: JSON with method details, metrics, and commits.
Output: JSON with derived_metrics, semantic_analysis, and final_decision.
Rules: Check thresholds strictly. Use semantic deep-dive to verify if the co-changes are truly related to the method. Return ONLY JSON.""",

    # 8. Phong cách Tư duy logic (Logic-Heavy)
    """Determine the presence of architectural debt.
Equation for Shotgun Surgery: (fan_out >= threshold) & (co_changes >= threshold) & (history >= threshold).
Equation for Divergent Change: (history >= threshold) & (concerns >= 3) & (complexity_delta > 0).

Validate the 'file_path' to understand the method's role (e.g., Controller vs Utility). Provide a reasoning chain that explains the mismatch between raw data and semantic purpose if it exists.
Output: Valid JSON schema only.""",

    # 9. Phong cách Giám sát Git (Git Evolution Analyst)
    """Analyze how this method has evolved over time to find smells.
1. Does it change with too many other files (Shotgun Surgery)?
2. Does it change for too many different reasons (Divergent Change)?
Examine 'commit_messages' for keywords and 'total_unique_co_changed_classes' for coupling.
Provide derived metrics including change_frequency_monthly and avg_files_per_commit.
Return ONLY JSON.""",

    # 10. Phong cách Tổng quát (General Instruction)
    """You are a specialized engine for code smell analysis.
Identify if the given method exhibits SHOTGUN SURGERY or DIVERGENT CHANGE based on the provided static analysis and git pre-computed data.
Follow the provided schema for derived_metrics and semantic_analysis.
Ensure the reasoning_chain explicitly addresses the thresholds and architectural context.
Final output must be a valid JSON object without any additional text."""
]

def augment_code_variable_renaming(code_snippet):
    """
    Thay đổi tên các biến trong đoạn code một cách ngẫu nhiên.
    Sử dụng Regex để nhận diện các biến phổ biến trong Java/C++.
    """
    keywords = {
        'public', 'private', 'protected', 'static', 'final', 'int', 'double', 'float',
        'String', 'boolean', 'if', 'else', 'for', 'while', 'return', 'class', 'void',
        'new', 'import', 'package', 'Optional', 'override', 'this', 'true', 'false'
    }

    identifiers = set(re.findall(r'\b[a-zA-Z_][a-zA-Z0-9_]*\b', code_snippet))
    potential_vars = [word for word in identifiers if word not in keywords and len(word) > 2]

    mapping = {}
    random.shuffle(potential_vars)
    for i, var in enumerate(potential_vars):
        if random.random() > 0.4:
            mapping[var] = f"var_{i}_{random.randint(100, 999)}"

    new_code = code_snippet
    for old_name, new_name in mapping.items():
        new_code = re.sub(r'\b' + old_name + r'\b', new_name, new_code)

    return new_code

def shuffle_json_keys(obj):
    """
    Hàm đệ quy để xáo trộn ngẫu nhiên thứ tự các key trong một đối tượng JSON.
    """
    if isinstance(obj, dict):
        keys = list(obj.keys())
        random.shuffle(keys)
        return {k: shuffle_json_keys(obj[k]) for k in keys}
    elif isinstance(obj, list):
        return [shuffle_json_keys(item) for item in obj]
    else:
        return obj

def augment_output_json(json_string):
    """
    Nhận vào chuỗi JSON đầu ra, xáo trộn thứ tự và trả về chuỗi JSON mới hợp lệ.
    """
    try:
        data = json.loads(json_string)
        shuffled_data = shuffle_json_keys(data)
        return json.dumps(shuffled_data, ensure_ascii=False, separators=(',', ':'))
    except Exception as e:
        return json_string

def get_random_instruction():
    return random.choice(ALT_INSTRUCTIONS)

def augment_item(item):
    aug_item = copy.deepcopy(item)
    
    # --- Semantic Logic Enforcement (Counterfactual Sensitivity Regularization) ---
    # Luật Logic: Nếu commit_count >= 4 và distinct_concerns >= 3 -> KHÔNG ĐƯỢC LÀ 'none'.
    # Ta sẽ tạo ra dữ liệu đối nghịch (adversarial) để ép model học ranh giới logic này.
    try:
        input_data = json.loads(aug_item.get("input", "{}"))
        out_data = json.loads(aug_item.get("output", "{}"))
        
        label = out_data.get("final_decision", {}).get("label", "none")
        
        # Với xác suất 30%, biến đổi một mẫu 'none' thành 'divergent_change' bằng cách vi phạm ngưỡng
        if label == "none" and random.random() < 0.3:
            # Tăng các features vượt ngưỡng
            input_data["pre_computed"]["commit_count"] = random.randint(4, 10)
            input_data["pre_computed"]["distinct_concerns"] = random.randint(3, 5)
            input_data["pre_computed"]["complexity_delta"] = random.randint(1, 4)
            
            # Đổi nhãn đầu ra để phản ánh đúng logic
            out_data["final_decision"]["label"] = "divergent_change"
            out_data["final_decision"]["confidence"] = 0.85
            out_data["final_decision"]["reasoning_chain"] = [
                "[Metrics Base]: commit_count >= 4, distinct_concerns >= 3, complexity_delta > 0. All thresholds met.",
                "[Semantic Deep-Dive]: CSR Augmented Sample to enforce logic boundaries.",
                "[Conclusion]: divergent_change detected due to metrics violation."
            ]
            out_data["divergent_change"]["metrics_score"] = 1.0
            out_data["divergent_change"]["final_smell_probability"] = 0.9
            
            aug_item["input"] = json.dumps(input_data, ensure_ascii=False)
            aug_item["output"] = json.dumps(out_data, ensure_ascii=False)
    except Exception:
        pass
    # -----------------------------------------------------------------------------

    aug_item["output"] = augment_output_json(aug_item.get("output", "{}"))
    aug_item["instruction"] = get_random_instruction()

    try:
        input_data = json.loads(aug_item.get("input", "{}"))
        if "method_body" in input_data:
            input_data["method_body"] = augment_code_variable_renaming(input_data["method_body"])
        aug_item["input"] = json.dumps(input_data, ensure_ascii=False)
    except:
        pass

    return aug_item

def load_and_prepare_data(data_path, tokenizer, val_split_size=0.1, positive_weight=1):
    """
    Đọc dữ liệu từ định dạng JSONL, chuyển thành Dataset Huggingface.
    Áp dụng các kỹ thuật augmentation:
    - Randomize instruction.
    - Code variable renaming.
    - Output JSON key shuffling.
    - Oversampling cho class positive.
    """
    balanced_data = []
    
    pos_count = 0
    neg_count = 0
    
    with open(data_path, 'r', encoding='utf-8') as f:
        for line in f:
            item = json.loads(line)
            
            # Kiểm tra xem đây có phải mẫu Negative không
            try:
                out_js = json.loads(item.get('output', '{}'))
                is_none_class = out_js.get('final_decision', {}).get('label') == 'none'
            except Exception:
                is_none_class = False
            
            if is_none_class:
                neg_count += 1
                # Augment instruction nhẹ nhàng cho Negative
                aug_item = copy.deepcopy(item)
                aug_item["instruction"] = get_random_instruction()
                balanced_data.append(aug_item)
            else:
                pos_count += 1
                # Oversampling: Nếu là mẫu Positive, copy + augment n lần
                for _ in range(positive_weight):
                    aug_item = augment_item(item)
                    balanced_data.append(aug_item)
                    
    print(f"Data Loaded: {pos_count * positive_weight} Positives | {neg_count} Negatives")
            
    dataset = Dataset.from_list(balanced_data)
    
    def formatting_prompts_func(examples):
        instructions = examples.get("instruction", [])
        inputs = examples.get("input", [])
        outputs = examples.get("output", [])
        
        texts = []
        for instr, user_input, out in zip(instructions, inputs, outputs):
            # Cấu trúc nhắc nhở của Qwen-Coder tốt hơn nếu cho instruction + input vào role user
            messages = [
                {"role": "user", "content": f"{instr}\n\n{user_input}"},
                {"role": "assistant", "content": out}
            ]
            text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=False)
            texts.append(text)
            
        return {"text": texts}
        
    dataset = dataset.map(formatting_prompts_func, batched=True, remove_columns=dataset.column_names)
    
    split_dataset = dataset.train_test_split(test_size=val_split_size, seed=42)
    return split_dataset["train"], split_dataset["test"]
