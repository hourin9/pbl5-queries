from unsloth import FastLanguageModel
import os
import torch
import argparse
import urllib.request
import gdown
from transformers import EarlyStoppingCallback
from trl import SFTTrainer, SFTConfig
import wandb
import numpy as np
from sklearn.metrics import precision_recall_fscore_support

from config import TrainingConfig
from dataset_utils import load_and_prepare_data


def download_dataset(url, dest_path):
    print(f"📥 Đang tải dataset từ: {url}")
    if "drive.google.com" in url:
        gdown.download(url, dest_path, quiet=False, fuzzy=True)
    else:
        urllib.request.urlretrieve(url, dest_path)
    print(f"✅ Đã tải dataset thành công vào: {dest_path}")


def get_model_name(size):
    mapping = {
        "0.5B": "unsloth/Qwen2.5-Coder-0.5B-Instruct",
        "1.5B": "unsloth/Qwen2.5-Coder-1.5B-Instruct",
        "3B": "unsloth/Qwen2.5-Coder-3B-Instruct",
        "7B": "unsloth/Qwen2.5-Coder-7B-Instruct",
    }
    return mapping.get(size.upper(), "unsloth/Qwen2.5-Coder-0.5B-Instruct")


def parse_args():
    parser = argparse.ArgumentParser(description="PBL5 Code Smell Distillation Training Pipeline")
    # Để default=None để không ghi đè giá trị trong TrainingConfig trừ khi người dùng chỉ định
    parser.add_argument("--model_size", type=str, default=None, choices=["0.5B", "1.5B", "3B", "7B", "0.5b", "1.5b", "3b", "7b"], help="Size of Qwen2.5-Coder model to use")
    parser.add_argument("--dataset_url", type=str, default=None, help="Public URL (Google Drive or direct) to download the .jsonl dataset")
    parser.add_argument("--data_path", type=str, default=None, help="Local path to the dataset file")
    parser.add_argument("--output_dir", type=str, default=None, help="Directory to save the output model")
    parser.add_argument("--batch_size", type=int, default=None, help="Per device batch size")
    parser.add_argument("--epochs", type=int, default=None, help="Number of training epochs")
    parser.add_argument("--learning_rate", type=float, default=None, help="Learning rate")
    parser.add_argument("--wandb_project", type=str, default=None, help="WandB project name")
    parser.add_argument("--wandb_run_name", type=str, default=None, help="WandB run name")
    return parser.parse_args()


def main():
    args = parse_args()
    config = TrainingConfig()
    
    # Chỉ ghi đè cấu hình từ argparse nếu người dùng có truyền tham số (khác None)
    if args.model_size:
        config.model_name = get_model_name(args.model_size)
    if args.data_path:
        config.data_path = args.data_path
    if args.output_dir:
        config.output_dir = args.output_dir
    if args.batch_size:
        config.per_device_train_batch_size = args.batch_size
        config.per_device_eval_batch_size = args.batch_size
    if args.epochs:
        config.num_train_epochs = args.epochs
    if args.learning_rate:
        config.learning_rate = args.learning_rate
    if args.wandb_project:
        config.wandb_project = args.wandb_project
    
    config.wandb_run_name = args.wandb_run_name or f"{config.model_name.split('/')[-1].lower()}-run"
    
    # 0. Download dataset if URL is provided
    if args.dataset_url:
        download_dataset(args.dataset_url, config.data_path)
    
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
        use_rslora = config.use_rslora,
    )
    
    # 3.5 Áp dụng Dropout (Anti-overfitting)
    model.config.attention_dropout = config.attention_dropout
    model.config.hidden_dropout = config.hidden_dropout
    
    # 4. Load & Formatting Dataset
    print("⚙️ Chuẩn bị tập dữ liệu và tiền xử lý ChatML...")
    if not os.path.exists(config.data_path):
        raise FileNotFoundError(f"Không tìm thấy tập dữ liệu tại {config.data_path}! Bạn đã dùng --dataset_url chưa?")
    
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
        max_length=config.max_seq_length,
        dataset_num_proc=2,
        packing=config.packing,
        
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
        load_best_model_at_end=True, # Yêu cầu restore model best checkpoint sau khi end
        metric_for_best_model="f1",
        greater_is_better=True
    )
    
    def preprocess_logits_for_metrics(logits, labels):
        if isinstance(logits, tuple):
            logits = logits[0]
        return logits.argmax(dim=-1)

    def compute_metrics(eval_preds):
        preds, labels = eval_preds
        # Replace -100 with pad token id
        preds = np.where(labels != -100, preds, tokenizer.pad_token_id)
        labels = np.where(labels != -100, labels, tokenizer.pad_token_id)
        
        decoded_preds = tokenizer.batch_decode(preds, skip_special_tokens=True)
        decoded_labels = tokenizer.batch_decode(labels, skip_special_tokens=True)
        
        y_true = []
        y_pred = []
        import re
        
        for p, l in zip(decoded_preds, decoded_labels):
            # Parse label
            true_match = re.search(r'"label"\s*:\s*"([^"]+)"', l)
            pred_match = re.search(r'"label"\s*:\s*"([^"]+)"', p)
            
            y_true.append(true_match.group(1).lower() if true_match else "none")
            y_pred.append(pred_match.group(1).lower() if pred_match else "none")
            
        precision, recall, f1, _ = precision_recall_fscore_support(
            y_true, y_pred, average='macro', zero_division=0
        )
        return {"precision": precision, "recall": recall, "f1": f1}

    class SemanticLossTrainer(SFTTrainer):
        def compute_loss(self, model, inputs, return_outputs=False, **kwargs):
            # Tính toán chuẩn Cross Entropy Loss của Causal LM
            loss, outputs = super().compute_loss(model, inputs, return_outputs=True, **kwargs)
            
            # --- SEMANTIC LOSS (Cải tiến đa điều kiện) ---
            try:
                tokenizer = self.processing_class if hasattr(self, 'processing_class') else self.model.config.tokenizer
                batch_size = inputs["input_ids"].size(0)
                logits = outputs.logits
                semantic_penalty = 0.0
                
                none_ids = set(tokenizer.encode('none', add_special_tokens=False) + 
                               tokenizer.encode('"none"', add_special_tokens=False))
                
                for b in range(batch_size):
                    text = tokenizer.decode(inputs["input_ids"][b], skip_special_tokens=True)
                    import re
                    
                    # Trích xuất các metrics từ text
                    c_match = re.search(r'"commit_count":\s*(\d+)', text)
                    f_match = re.search(r'"fan_out":\s*(\d+)', text)
                    d_match = re.search(r'"distinct_concerns":\s*(\d+)', text)
                    
                    c = int(c_match.group(1)) if c_match else 0
                    f = int(f_match.group(1)) if f_match else 0
                    d = int(d_match.group(1)) if d_match else 0
                    
                    # Kích hoạt phạt nếu là Code Smell rõ ràng theo các ngưỡng
                    is_smell = (c >= 3 and f >= 14) or (c >= 4 and d >= 3)
                    
                    if is_smell:
                        valid_indices = (inputs["labels"][b] != -100).nonzero(as_tuple=True)[0]
                        for idx in valid_indices:
                            prev_tokens = inputs["input_ids"][b, max(0, idx-10):idx]
                            prev_text = tokenizer.decode(prev_tokens).replace(" ", "")
                            
                            if '"label":"' in prev_text:
                                step_logits = logits[b, idx - 1, :]
                                step_probs = torch.nn.functional.softmax(step_logits, dim=-1)
                                
                                p_none = sum([step_probs[nid] for nid in none_ids if nid < step_probs.size(0)])
                                
                                # Margin Penalty: Phạt cực mạnh nếu model có p_none > 0.4
                                # Ép model phải giảm độ tự tin vào "none" nếu metrics hiển nhiên xấu
                                penalty_term = max(0.0, float(p_none) - 0.4)
                                semantic_penalty += 10.0 * penalty_term
                                break
                
                total_loss = loss + (semantic_penalty / batch_size)
            except Exception as e:
                print("Lỗi tính Semantic Loss:", e)
                total_loss = loss
            
            return (total_loss, outputs) if return_outputs else total_loss

    trainer = SemanticLossTrainer(
        model = model,
        tokenizer = tokenizer,
        train_dataset = train_dataset,
        eval_dataset = val_dataset,
        args = training_args,
        preprocess_logits_for_metrics=preprocess_logits_for_metrics,
        compute_metrics=compute_metrics,
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
