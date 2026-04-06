import json
import os
from glob import glob


def build_training_sample(input_json: dict, output_json: dict = None) -> dict:
    input_str = json.dumps(input_json, ensure_ascii=False, separators=(",", ":"))
    system_prompt = (
        "You are a senior expert in Static Analysis and Software Architecture. "
        "Your task is to analyze the evolution history of a function to identify Code Smell signs, "
        "specifically Divergent Change or Shotgun Surgery. "
        "Provide your reasoning step-by-step (Reasoning_Step_1, Reasoning_Step_2, Reasoning_Step_3) "
        "and return a JSON object containing the following fields: "
        "Reasoning_Step_1, Reasoning_Step_2, Reasoning_Step_3, and Conclusion."
    )
    sample = {
        "system": system_prompt,
        "instruction": f"Input Data: {input_str}",
        "output": "",
    }
    if output_json is not None:
        sample["output"] = json.dumps(
            output_json, ensure_ascii=False, separators=(",", ":")
        )
    return sample


def build_jsonl_dataset(input_dir: str, output_dir: str, ground_truth_dir: str = None):
    """Hàm tiện ích gom dataset thô lại với label AI"""
    input_files = glob(os.path.join(input_dir, "*.json"))
    samples = []

    for in_path in input_files:
        with open(in_path, "r", encoding="utf-8") as f:
            try:
                input_data = json.load(f)
            except Exception:
                continue

        out_data = None
        if ground_truth_dir:
            base_name = os.path.basename(in_path)
            out_path = os.path.join(ground_truth_dir, base_name)
            if os.path.exists(out_path):
                with open(out_path, "r", encoding="utf-8") as f:
                    out_data = json.load(f)

        if out_data:  # Chỉ đưa vào tập train những file đã có output
            sample = build_training_sample(input_data, out_data)
            samples.append(sample)

    os.makedirs(output_dir, exist_ok=True)
    out_file = os.path.join(output_dir, "train_dataset_english.jsonl")
    with open(out_file, "w", encoding="utf-8") as f:
        for sample in samples:
            f.write(json.dumps(sample, ensure_ascii=False) + "\n")

    print(f"Pipeline Hoàn Tất! Đã tạo {len(samples)} mẫu huấn luyện tại {out_file}")
