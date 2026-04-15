import json
from datasets import Dataset

def load_and_prepare_data(data_path, tokenizer, val_split_size=0.1, positive_weight=1):
    """
    Đọc dữ liệu từ định dạng JSONL, chuyển thành Dataset Huggingface.
    Hỗ trợ Oversampling cho các case có Code Smell (Dữ liệu mất cân bằng).
    """
    balanced_data = []
    with open(data_path, 'r', encoding='utf-8') as f:
        for line in f:
            item = json.loads(line)
            balanced_data.append(item)
            
            # Kiểm tra xem đây có phải mẫu Negative không (nhãn none) bằng cách decode cục bộ
            try:
                out_js = json.loads(item.get('output', '{}'))
                is_none_class = out_js.get('final_decision', {}).get('label') == 'none'
            except Exception:
                is_none_class = False # Mặc định coi là positive nếu parser lỗi
            
            # Oversampling: Nếu là mẫu Positive (có smell), lặp lại mẫu đó vào dataset
            if not is_none_class and positive_weight > 1:
                # Trừ 1 vì đã append ở trên rồi
                for _ in range(positive_weight - 1):
                    balanced_data.append(item)
            
    dataset = Dataset.from_list(balanced_data)
    
    def formatting_prompts_func(examples):
        instructions = examples.get("instruction", [])
        inputs = examples.get("input", [])
        outputs = examples.get("output", [])
        
        texts = []
        for instr, user_input, out in zip(instructions, inputs, outputs):
            # Qwen-Coder rất phù hợp với role 'system' để giữ hướng dẫn
            messages = [
                {"role": "system", "content": instr},
                {"role": "user", "content": user_input},
                {"role": "assistant", "content": out}
            ]
            text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=False)
            texts.append(text)
            
        return {"text": texts}
        
    # Xoá các cột nguyên bản, đưa ra duy nhất cột 'text'
    dataset = dataset.map(formatting_prompts_func, batched=True, remove_columns=dataset.column_names)
    
    # Shuffle & Split
    split_dataset = dataset.train_test_split(test_size=val_split_size, seed=42)
    return split_dataset["train"], split_dataset["test"]
