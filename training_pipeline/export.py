import os
from unsloth import FastLanguageModel
from config import TrainingConfig

def main():
    config = TrainingConfig()
    lora_path = f"{config.output_dir}/lora_model"
    
    if not os.path.exists(lora_path):
        raise FileNotFoundError(f"❌ Chưa tìm thấy checkpoint chuẩn tại {lora_path}. Vui lòng kiểm tra lại log train.")
        
    print(f"🔄 Nạp mô hình đã train từ {lora_path} ...")
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name = lora_path,
        max_seq_length = config.max_seq_length,
        dtype = config.dtype,
        load_in_4bit = config.load_in_4bit,
    )
    
    print("🚀 Bắt đầu quá trình xuất khẩu model (Export)...")
    
    # Output 1: Model sáp nhập đủ 16 bit
    # Dùng cho các cơ sở hạ tầng cung cấp GPU Server mạnh (vLLM, HuggingFace Inference Endpoint)
    merged_path = f"{config.output_dir}/merged_16bit"
    print(f"VLLM-Ready: Đang trích xuất toàn vẹn Model Base + Lora tại: {merged_path}...")
    model.save_pretrained_merged(merged_path, tokenizer, save_method="merged_16bit")
    
    # Output 2: GGUF Model (Q4)
    # Rất thích hợp để triển khai Ollama tại hệ thống local / edge devices không có card màn hình khủng
    gguf_path = f"{config.output_dir}/gguf_q4"
    print(f"Ollama-Ready: Đang nén lượng tử học xuống file hệ GGUF lượng tử siêu nhẹ tại: {gguf_path}...")
    try:
        model.save_pretrained_gguf(gguf_path, tokenizer, quantization_method="q4_k_m")
    except Exception as e:
        print(f"⚠️ Quá trình GGUF có lỗi do chưa cài Llama.cpp, hãy cài bộ framework trước nếu muốn chạy bằng Ollama:\n {str(e)}")

    print("✅ Model xuất bản thành công!")

if __name__ == "__main__":
    main()
