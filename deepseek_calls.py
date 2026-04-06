import json
import os
import time

import openai
from dotenv import load_dotenv

load_dotenv()

client = openai.OpenAI(
    api_key=os.getenv("DEEPSEEK_API"), base_url="https://api.deepseek.com"
)

SYSTEM_PROMPT = (
    "You are a senior expert in Static Analysis and Software Architecture. "
    "Your task is to analyze the evolution history of a function to identify Code Smell signs, "
    "specifically Divergent Change or Shotgun Surgery. "
    "Provide your reasoning step-by-step (Reasoning_Step_1, Reasoning_Step_2, Reasoning_Step_3) "
    "and return a JSON object containing the following fields: "
    "Reasoning_Step_1, Reasoning_Step_2, Reasoning_Step_3, and Conclusion."
)


def get_teacher_explanation(git_data):
    input_str = json.dumps(git_data, ensure_ascii=False, separators=(",", ":"))
    try:
        response = client.chat.completions.create(
            model="deepseek-reasoner",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Input Data: {input_str}"},
            ],
            response_format={"type": "json_object"},
            temperature=0.3,
            max_tokens=4048,
        )
        final_answer = response.choices[0].message.content
        return json.loads(final_answer)
    except Exception as e:
        print(f"Lỗi gọi API: {e}")
        return None


def process_all_methods_with_ai(input_dir, output_dir):
    """Quét toàn bộ thư mục và gọi DeepSeek API"""
    os.makedirs(output_dir, exist_ok=True)
    input_files = [f for f in os.listdir(input_dir) if f.endswith(".json")]

    print(f"Bắt đầu gọi AI cho {len(input_files)} file...")

    for filename in input_files:
        in_path = os.path.join(input_dir, filename)
        out_path = os.path.join(output_dir, filename)

        # Bỏ qua nếu file đã được xử lý (Resume capability)
        if os.path.exists(out_path):
            print(f"Bỏ qua {filename} (Đã có sẵn ground_truth).")
            continue

        with open(in_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        print(f"Đang suy luận cho: {filename}...")
        explanation = get_teacher_explanation(data)

        if explanation:
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(explanation, f, ensure_ascii=False, indent=4)
            print(f" => Đã lưu: {out_path}")

        # Tránh rate-limit của DeepSeek
        time.sleep(2)
