import os
import json
import glob
from jsonschema import validate, ValidationError
from utils.logger import get_logger
from utils.state_manager import state_manager

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Schema for the new Phase 3 output format
# ---------------------------------------------------------------------------
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
                "total_unique_co_changed_classes": {"type": "integer"},
                "distinct_concerns": {"type": "integer"},
                "concern_keywords": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["commit_count", "distinct_concerns", "total_unique_co_changed_classes"]
        },
        "semantic_analysis": {
            "type": "object",
            "properties": {
                "single_responsibility_violation": {"type": "boolean"},
                "domain_coupling": {"type": "string", "enum": ["High", "Medium", "Low"]},
                "conflict_resolution": {
                    "type": "object",
                    "properties": {
                        "status": {"type": "string", "enum": ["Aligned", "Metrics_Overstated", "Metrics_Understated"]},
                        "reason": {"type": "string"}
                    },
                    "required": ["status", "reason"]
                },
                "architectural_context": {
                    "type": "object",
                    "properties": {
                        "method_role": {"type": "string"},
                        "project_architecture": {"type": "string"},
                        "design_patterns_observed": {"type": "array", "items": {"type": "string"}}
                    },
                    "required": ["method_role", "project_architecture"]
                }
            },
            "required": ["single_responsibility_violation", "domain_coupling", "semantic_conflict_with_metrics", "architectural_context"]
        },
        "shotgun_surgery": {
            "type": "object",
            "properties": {
                "metrics_score": {"type": "number"},
                "override_status": {"type": "string", "enum": ["No_Override", "Semantic_Upgrade", "Semantic_Downgrade"]},
                "final_smell_probability": {"type": "number"}
            },
            "required": ["metrics_score", "override_status", "final_smell_probability"]
        },
        "divergent_change": {
            "type": "object",
            "properties": {
                "metrics_score": {"type": "number"},
                "override_status": {"type": "string", "enum": ["No_Override", "Semantic_Upgrade", "Semantic_Downgrade"]},
                "final_smell_probability": {"type": "number"}
            },
            "required": ["metrics_score", "override_status", "final_smell_probability"]
        },
        "final_decision": {
            "type": "object",
            "properties": {
                "label": {"type": "string", "enum": ["none", "shotgun_surgery", "divergent_change"]},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "reasoning_chain": {"type": "array", "items": {"type": "string"}}
            },
            "required": ["label", "confidence", "reasoning_chain"]
        },
        "suggested_refactor": {"type": "string"}
    },
    "required": ["derived_metrics", "semantic_analysis", "shotgun_surgery", "divergent_change", "final_decision", "suggested_refactor"]
}


def validate_dataset_schema(file_path, expected_thresholds=None):
    """Validate a ground truth JSON file against the schema and check logical consistency."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            validate(instance=data, schema=SMELL_SCHEMA)

            # Logic checks
            final_decision = data.get("final_decision", {})
            label = final_decision.get("label", "none")
            confidence = final_decision.get("confidence", 0)

            ss_prob = data.get("shotgun_surgery", {}).get("final_smell_probability", 0)
            dc_prob = data.get("divergent_change", {}).get("final_smell_probability", 0)

            # Label must match probabilities (roughly)
            if label == "shotgun_surgery" and ss_prob < 0.5:
                return False, "Logic: label is shotgun_surgery but final_smell_probability < 0.5"
            if label == "divergent_change" and dc_prob < 0.5:
                return False, "Logic: label is divergent_change but final_smell_probability < 0.5"

            # Confidence sanity check
            if label != "none" and confidence < 0.4:
                return False, f"Logic: smell detected but confidence too low ({confidence})"

            return True, data
    except json.JSONDecodeError as e:
        return False, f"JSON decode error: {e}"
    except ValidationError as e:
        return False, f"Schema invalid: {e.message}"


def build_training_sample(input_data, truth_data):
    """Build a training sample by merging method evolution input with AI ground truth output."""
    try:
        from pipeline.phase3_synthesis import SYSTEM_PROMPT_TEMPLATE, build_ai_input
        ai_input = build_ai_input(input_data)
        if not ai_input:
            return None

        input_str = json.dumps(ai_input, ensure_ascii=False, separators=(",", ":"))
        return {
            "instruction": SYSTEM_PROMPT_TEMPLATE,
            "input": f"Analyze this method:\n{input_str}",
            "output": json.dumps(truth_data, ensure_ascii=False, separators=(",", ":")),
        }
    except ImportError:
        # Fallback if phase3 cannot be imported
        return {
            "input": input_data,
            "ground_truth": truth_data,
        }


async def run_phase4_validation(evo_dir="method_evolutions", gt_dir="ground_truth", out_file="dataset_output/final_dataset.jsonl"):
    os.makedirs(os.path.dirname(out_file), exist_ok=True)
    repos = state_manager.get_pending_repos(4)
    if not repos:
        logger.info("No repositories pending for Phase 4.")
        return

    logger.info(f"Phase 4: Validating {len(repos)} repositories.")

    for rp in repos:
        repo_url, repo_name = rp
        repo_gt_dir = os.path.join(gt_dir, repo_name)
        repo_evo_dir = os.path.join(evo_dir, repo_name)

        if not os.path.exists(repo_gt_dir):
            state_manager.update_phase(repo_url, 4, 'FAILED', "Ground truth directory missing")
            continue

        # Use recursive glob to find files in smells/ and no_smells/ subdirectories
        gt_files = glob.glob(os.path.join(repo_gt_dir, "**/*.json"), recursive=True)
        if not gt_files:
            state_manager.update_phase(repo_url, 4, 'DONE')
            continue

        valid_samples = []
        invalid_count = 0

        thresholds_path = os.path.join(repo_evo_dir, "thresholds.json")
        repo_thresholds = {"fan_out": 7, "commit_count": 5, "co_classes": 5}
        if os.path.exists(thresholds_path):
            with open(thresholds_path, "r", encoding="utf-8") as f:
                repo_thresholds = json.load(f)

        for f in gt_files:
            is_valid, validation_res = validate_dataset_schema(f, repo_thresholds)
            if is_valid:
                base_f = os.path.basename(f)
                evo_f = os.path.join(repo_evo_dir, base_f)
                if os.path.exists(evo_f):
                    with open(evo_f, "r", encoding="utf-8") as in_f:
                        in_data = json.load(in_f)
                        merged = build_training_sample(in_data, validation_res)
                        if merged:
                            valid_samples.append(merged)
            else:
                invalid_count += 1
                logger.debug(f"Invalid: {validation_res} in file {f}")

        # Cân bằng Class (Downsampling) chống Data Imbalance
        if valid_samples:
            positives = []
            negatives = []
            for s in valid_samples:
                # Trích xuất label từ output JSON string
                try:
                    out_json = json.loads(s.get("output", "{}"))
                    lbl = out_json.get("label", "none")
                except:
                    lbl = "none"
                if lbl == "none":
                    negatives.append(s)
                else:
                    positives.append(s)

            # Giữ tỷ lệ negative:positive = 3:1
            import random
            max_negatives = max(10, len(positives) * 3) # Ít nhất 10 mẫu để tránh empty nếu không có code smell
            
            if len(negatives) > max_negatives:
                # Lọc lấy các mẫu negative có độ tin cậy tự chấm cao nhất (tin rằng đây thực sự là code sạch)
                negatives.sort(key=lambda x: json.loads(x.get("output", "{}")).get("confidence", 0), reverse=True)
                negatives = negatives[:max_negatives]

            balanced_samples = positives + negatives
            random.shuffle(balanced_samples)

            with open(out_file, "a", encoding="utf-8") as outf:
                for s in balanced_samples:
                    outf.write(json.dumps(s, ensure_ascii=False) + "\n")
            
            logger.info(f"[{repo_name}] Downsampling: Giữ lại {len(positives)} Positive và {len(negatives)} Negative (từ {len(valid_samples)}).")
        else:
            logger.info(f"[{repo_name}] 0 valid samples.")

        logger.info(f"[{repo_name}] {invalid_count} rejected due to logic/schema.")
        state_manager.update_phase(repo_url, 4, 'DONE')

    logger.info("Phase 4 (Validation) completed.")
