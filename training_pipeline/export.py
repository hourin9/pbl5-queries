import os
import argparse
import wandb
import torch
from unsloth import FastLanguageModel

def export_and_upload():
    parser = argparse.ArgumentParser(description="Export and Upload Model to WandB")
    parser.add_argument("--lora_path", type=str, default="outputs_qwen_coder/lora_model", help="Path to trained LoRA adapter")
    parser.add_argument("--export_dir", type=str, default="merged_model_16bit", help="Local path to save merged model")
    parser.add_argument("--wandb_project", type=str, default="PBL5-Code-Smell-Distillation", help="WandB project name")
    parser.add_argument("--method", type=str, default="merged_16bit", choices=["merged_16bit", "merged_4bit", "gguf"], help="Export method")
    args = parser.parse_args()

    # 1. Load LoRA model
    print(f"📦 Đang nạp LoRA từ {args.lora_path}...")
    # Lưu ý: max_seq_length không quá quan trọng khi export, nhưng cần khớp với lúc train để tránh lỗi nạp
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name = args.lora_path,
        max_seq_length = 4096,
        load_in_4bit = True,
    )

    # 2. Thực hiện Export
    print(f"🔄 Đang thực hiện export định dạng: {args.method}...")
    
    if args.method == "merged_16bit":
        model.save_pretrained_merged(args.export_dir, tokenizer, save_method = "merged_16bit")
    elif args.method == "merged_4bit":
        model.save_pretrained_merged(args.export_dir, tokenizer, save_method = "merged_4bit")
    elif args.method == "gguf":
        # Xuất sang GGUF (dùng cho Ollama/Llama.cpp) - mặc định là q8_0
        model.save_pretrained_gguf(args.export_dir, tokenizer, quantization_method = "q8_0")
    
    tokenizer.save_pretrained(args.export_dir)
    print(f"✅ Đã lưu model tại {args.export_dir}")

    # 3. Upload lên WandB Artifacts (Phương án ổn định nhất cho Cloud)
    print(f"🚀 Đang kết nối WandB để upload...")
    # Khởi tạo một run mới cho tác vụ export
    run = wandb.init(project=args.wandb_project, name=f"export-{args.method}", job_type="model-export")
    
    artifact_name = f"qwen-coder-distilled-{args.method}"
    artifact = wandb.Artifact(name=artifact_name, type="model")
    
    print(f"📤 Đang tải các tệp tin lên WandB Artifact: {artifact_name}...")
    artifact.add_dir(args.export_dir)
    run.log_artifact(artifact)
    
    run.finish()
    print(f"\n✨ XONG! Model của bạn đã được bảo vệ trên WandB.")
    print(f"🔗 Bạn có thể vào link dự án trên WandB, chọn mục 'Artifacts' để thấy model và tải về máy local.")

if __name__ == "__main__":
    export_and_upload()
