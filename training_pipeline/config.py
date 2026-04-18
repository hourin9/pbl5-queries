import os
from dataclasses import dataclass

@dataclass
class TrainingConfig:
    # Model Config
    model_name: str = "unsloth/Qwen2.5-Coder-0.5B-Instruct"
    max_seq_length: int = 8192  # Tùy chỉnh theo mức độ dài của method source
    load_in_4bit: bool = True
    dtype = None # Auto
    
    # LoRA Config
    r: int = 64
    lora_alpha: int = 128
    lora_dropout: float = 0.0
    bias: str = "none"
    use_gradient_checkpointing: str = "unsloth"
    
    # Dataset Config
    data_path: str = "./final_dataset.jsonl"
    val_split_size: float = 0.1 # 10% dành cho đánh giá
    positive_sample_weight: int = 5 # Hệ số oversample/tăng trọng số các mẫu positive (có code smell)
    train_on_responses_only: bool = True # Chỉ tính loss phần generate JSON, chống học vẹt prompt
    
    # Training Arguments
    per_device_train_batch_size: int = 2
    per_device_eval_batch_size: int = 2
    gradient_accumulation_steps: int = 4
    warmup_steps: int = 10
    num_train_epochs: int = 3
    learning_rate: float = 2e-4
    
    # Kỹ thuật regularization chống thuộc lòng nội suy (Native HF)
    neftune_noise_alpha: float = 5.0 # Kích nhiễu vector không gian 5% chặn học vẹt
    label_smoothing_factor: float = 0.05 # Tránh model tự tin 100% gây sập loss
    
    optim: str = "adamw_8bit"
    weight_decay: float = 0.01
    lr_scheduler_type: str = "linear"
    seed: int = 3407
    
    # Eval & Logging
    eval_strategy: str = "steps"
    eval_steps: int = 50
    logging_steps: int = 1
    save_strategy: str = "steps"
    save_steps: int = 50
    output_dir: str = "outputs_qwen_coder"
    
    # Môi trường Weights & Biases
    report_to: str = "wandb"
    wandb_project: str = "PBL5-Code-Smell-Distillation"
    wandb_run_name: str = "qwen2.5-coder-0.5b-run1"
