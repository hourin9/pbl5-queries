import os
import json
import glob
from jsonschema import validate, ValidationError
from utils.logger import get_logger
from utils.state_manager import state_manager
try:
    from build_training_sample import build_training_sample
except ImportError:
    # Nếu file build_training_sample.py bên ngoài thay đổi
    def build_training_sample(input_data, truth_data):
        return {"input": input_data, "ground_truth": truth_data}

logger = get_logger(__name__)

# Schema tham chiếu để kiểm tra
SMELL_SCHEMA = {
    "type": "object",
    "properties": {
        "Reasoning_Step_1": {"type": "string"},
        "Reasoning_Step_2": {"type": "string"},
        "Conclusion": {"type": "string"},
        "Code_Smell_Detected": {"type": "boolean"},
        "Smell_Type": {"type": "string"}
    },
    "required": ["Code_Smell_Detected", "Smell_Type"]
}

def validate_dataset_schema(gt_file_path):
    with open(gt_file_path, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
            validate(instance=data, schema=SMELL_SCHEMA)
            
            # Layer 3 (Logic): Code Smell Detected must be true if Smell type is not None.
            detected = data.get("Code_Smell_Detected")
            smell_type = data.get("Smell_Type", "")
            
            if detected and "None" in smell_type:
                 return False, "Logic inconsistency: Detected is logic TRUE but smell type is None."
            if not detected and smell_type not in ["None", "", "none"]:
                 return False, "Logic inconsistency: Detected is logic FALSE but smell type is present."
                 
            return True, data
        except json.JSONDecodeError as e:
            return False, f"JSON Decode lỗi: {e}"
        except ValidationError as e:
            return False, f"Schema không hợp lệ: {e.message}"

async def run_phase4_validation(evo_dir="method_evolutions", gt_dir="ground_truth", out_file="dataset_output/final_dataset.jsonl"):
    os.makedirs(os.path.dirname(out_file), exist_ok=True)
    repos = state_manager.get_pending_repos(4)
    if not repos:
        logger.info("Không có Repos nào chờ Phase 4.")
        return

    logger.info(f"Phase 4: Bắt đầu Validating logic cho {len(repos)} repository.")
    
    for rp in repos:
        repo_url, repo_name = rp
        repo_gt_dir = os.path.join(gt_dir, repo_name)
        repo_evo_dir = os.path.join(evo_dir, repo_name)
        
        if not os.path.exists(repo_gt_dir):
            state_manager.update_phase(repo_url, 4, 'FAILED', "Thư mục Ground truth không tồn tại")
            continue
            
        gt_files = glob.glob(os.path.join(repo_gt_dir, "*.json"))
        if not gt_files:
            state_manager.update_phase(repo_url, 4, 'DONE')
            continue
            
        valid_samples = []
        invalid_count = 0
        
        for f in gt_files:
            is_valid, validation_res = validate_dataset_schema(f)
            if is_valid:
                # Merge original inputs and GT based on file name
                base_f = os.path.basename(f)
                evo_f = os.path.join(repo_evo_dir, base_f)
                if os.path.exists(evo_f):
                    with open(evo_f, "r", encoding="utf-8") as in_f:
                        in_data = json.load(in_f)
                        merged = build_training_sample(in_data, validation_res)
                        valid_samples.append(merged)
            else:
                invalid_count += 1
                logger.debug(f"Invalid logic/schema: {validation_res} in file {f}")
                
        # Write to final jsonl
        if valid_samples:
           with open(out_file, "a", encoding="utf-8") as outf:
               for s in valid_samples:
                   outf.write(json.dumps(s, ensure_ascii=False) + "\n")
                   
        logger.info(f"[{repo_name}] - Tổng cộng {len(valid_samples)} mẫu hợp lệ, {invalid_count} mẫu bị loại.")
        state_manager.update_phase(repo_url, 4, 'DONE')
        
    logger.info("Hoàn thành Giai đoạn 4 (QA & Refinement).")
