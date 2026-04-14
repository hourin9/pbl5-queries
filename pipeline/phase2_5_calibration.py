import os
import json
import logging
import statistics
from utils.logger import get_logger
from utils.state_manager import state_manager

logger = get_logger(__name__)

def precompute_calibration_metrics(data):
    """
    Trích xuất các đặc trưng tĩnh và động để làm dữ liệu nền tảng tính Threshold.
    """
    sa = data.get("sa", {})
    ev = data.get("ev", [])
    features = sa.get("features", {})

    # Deduplicate by commit hash
    seen_hashes = set()
    unique_ev = []
    for e in ev:
        if e["h"] not in seen_hashes:
            seen_hashes.add(e["h"])
            unique_ev.append(e)
    
    commit_count = len(unique_ev)
    
    unique_co_classes = set()
    for e in unique_ev:
        if "co_classes" in e:
            unique_co_classes.update(e["co_classes"])

    return {
        "fan_out": features.get("fan_out", 0),
        "commit_count": commit_count,
        "co_classes": len(unique_co_classes)
    }

def calculate_percentile(data_list, percentile):
    """Tính toán bách phân vị. Dữ liệu đầu vào sẽ được sắp xếp."""
    if not data_list:
        return 0
    data_list.sort()
    index = (percentile / 100) * (len(data_list) - 1)
    if index.is_integer():
        return data_list[int(index)]
    else:
        lower = int(index)
        upper = lower + 1
        return data_list[lower] + (data_list[upper] - data_list[lower]) * (index - lower)

def run_phase_2_5_calibration(output_dir="method_evolutions", percentile=85):
    """
    Thực hiện quét toàn bộ methods của từng repo, tính toán ngưỡng (Thresholds)
    dựa trên phân phối thống kê và ghi ra file thresholds.json
    """
    logger.info(f"Phase 2.5: Bắt đầu hiệu chuẩn ngưỡng tự động (Percentile: {percentile}th).")
    
    for repo_name in os.listdir(output_dir):
        repo_dir = os.path.join(output_dir, repo_name)
        if not os.path.isdir(repo_dir):
            continue

        metrics = {"fan_out": [], "commit_count": [], "co_classes": []}
        
        methods_count = 0
        for file in os.listdir(repo_dir):
            if not file.endswith(".json") or file == "thresholds.json":
                continue
            
            with open(os.path.join(repo_dir, file), "r", encoding="utf-8") as f:
                try:
                    data = json.load(f)
                    calib_data = precompute_calibration_metrics(data)
                    
                    metrics["fan_out"].append(calib_data["fan_out"])
                    metrics["commit_count"].append(calib_data["commit_count"])
                    metrics["co_classes"].append(calib_data["co_classes"])
                    methods_count += 1
                except Exception as e:
                    logger.warning(f"Lỗi đọc {file}: {e}")
        
        if methods_count == 0:
            logger.warning(f"Repo {repo_name} trống, bỏ qua hiệu chuẩn.")
            continue
            
        # Áp dụng quy tắc P85 hoặc giá trị tối thiểu cơ bản (để tránh ngưỡng quá thấp với các repo micro)
        thresholds = {
            "percentile_used": percentile,
            "method_samples": methods_count,
            "fan_out": max(7, round(calculate_percentile(metrics["fan_out"], percentile))),
            "commit_count": max(4, round(calculate_percentile(metrics["commit_count"], percentile))),
            "co_classes": max(3, round(calculate_percentile(metrics["co_classes"], percentile)))
        }

        out_path = os.path.join(repo_dir, "thresholds.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(thresholds, f, indent=4)
            
        logger.info(f"[{repo_name}] Hoàn tất hiệu chuẩn ({methods_count} methods): {thresholds}")
    
    logger.info("Phase 2.5: Hiệu chuẩn ngưỡng hoàn thành.")

if __name__ == "__main__":
    run_phase_2_5_calibration()
