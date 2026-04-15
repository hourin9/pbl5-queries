import os
import torch
from transformers import EarlyStoppingCallback
from trl import SFTTrainer, SFTConfig
from unsloth import FastLanguageModel
import wandb

from config import TrainingConfig
from dataset_utils import load_and_prepare_data

def main():
    config = TrainingConfig()
    
    # 1. Khởi tạo Weights & Biases
    print("🚀 Đang thiết lập Weights & Biases...")
    os.environ["WANDB_PROJECT"] = config.wandb_project
    wandb.init(project=config.wandb_project, name=config.wandb_run_name)
    
    # 2. Xây dựng model và tokenizer bằng Unsloth (Tối ưu Memory x2 lần)
    print(f"📦 Đang nạp model: {config.model_name}")
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name = config.model_name,
        max_seq_length = config.max_seq_length,
        dtype = config.dtype,
        load_in_4bit = config.load_in_4bit,
    )
    
    # 3. Kích hoạt tối ưu Target Modules cho LoRA
    model = FastLanguageModel.get_peft_model(
        model,
        r = config.r,
        target_modules = ["q_proj", "k_proj", "v_proj", "o_proj",
                          "gate_proj", "up_proj", "down_proj"],
        lora_alpha = config.lora_alpha,
        lora_dropout = config.lora_dropout,
        bias = config.bias,
        use_gradient_checkpointing = config.use_gradient_checkpointing,
        random_state = config.seed,
    )
    
    # 4. Load & Formatting Dataset
    print("⚙️ Chuẩn bị tập dữ liệu và tiền xử lý ChatML...")
    if not os.path.exists(config.data_path):
        raise FileNotFoundError(f"Không tìm thấy tập dữ liệu tại {config.data_path}!")
    
    train_dataset, val_dataset = load_and_prepare_data(
        config.data_path, tokenizer, 
        val_split_size=config.val_split_size,
        positive_weight=config.positive_sample_weight
    )
    print(f"✅ Samples: {len(train_dataset)} Train | {len(val_dataset)} Validation")
    
    # 5. Cấu hình SFTTrainer cho Fine-tuning thông qua SFTConfig (TRL mới)
    completion_only = config.train_on_responses_only
    if completion_only:
        print("🛡️ Sử dụng tính năng completion_only_loss=True (Hugging Face TRL) để ẩn Prompt.")

    training_args = SFTConfig(
        output_dir=config.output_dir,
        per_device_train_batch_size=config.per_device_train_batch_size,
        per_device_eval_batch_size=config.per_device_eval_batch_size,
        gradient_accumulation_steps=config.gradient_accumulation_steps,
        warmup_steps=config.warmup_steps,
        num_train_epochs=config.num_train_epochs,
        learning_rate=config.learning_rate,
        
        # Native TRL Regularizations
        neftune_noise_alpha=config.neftune_noise_alpha,
        label_smoothing_factor=config.label_smoothing_factor,
        
        # [CRITICAL FIX]: Giao quyền tự định nghĩa vùng sinh văn bản cho TRL qua chat_template
        completion_only_loss=completion_only,
        
        # Di chuyển tham số SFTTrainer cũ vào form SFTConfig theo chuẩn mới
        dataset_text_field="text",
        max_seq_length=config.max_seq_length,
        dataset_num_proc=2,
        
        # Tự động chọn Float16 hoặc BFloat16 do tương thích của máy
        fp16=not torch.cuda.is_bf16_supported(),
        bf16=torch.cuda.is_bf16_supported(),
        # Cơ chế theo dõi và lưu (Save model thường xuyên hơn)
        logging_steps=config.logging_steps,
        eval_strategy=config.eval_strategy,
        eval_steps=config.eval_steps,
        save_strategy=config.save_strategy,
        save_steps=config.save_steps,
        # Tham số Tối ưu Optimizer
        optim=config.optim,
        weight_decay=config.weight_decay,
        lr_scheduler_type=config.lr_scheduler_type,
        seed=config.seed,
        report_to=config.report_to,
        load_best_model_at_end=True # Yêu cầu restore model best checkpoint sau khi end
    )
    
    trainer = SFTTrainer(
        model = model,
        tokenizer = tokenizer,
        train_dataset = train_dataset,
        eval_dataset = val_dataset,
        args = training_args,
        # Tính năng EarlyStopping: Huỷ Train nếu Validation loss không suy giảm sau 3 vòng liên tiếp
        callbacks=[EarlyStoppingCallback(early_stopping_patience=3)] 
    )
    
    # 6. Kickoff
    print("🔥 Bắt đầu quá trình truyền dữ liệu Distillation...")
    trainer_stats = trainer.train()
    print(f"📊 Training Complete! Runtime: {trainer_stats.metrics.get('train_runtime')}s")
    
    # 7. Lưu bản gốc LoRA (Dùng ghép nối động nếu cần chia sẻ)
    model.save_pretrained(f"{config.output_dir}/lora_model")
    tokenizer.save_pretrained(f"{config.output_dir}/lora_model")
    print(f"💾 Checkpoint tạm thời lưu tại {config.output_dir}/lora_model")
    
    wandb.finish()
    print("✨ Quá trình hoàn tất! Hãy chạy script export.py để chuẩn bị model cho Server deployment.")

if __name__ == "__main__":
    main()
