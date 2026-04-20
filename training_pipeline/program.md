# Antigravity Autoresearch (Cloud GPU Edition)

This is an autonomous research program designed for the Antigravity AI Agent (bạn) to experiment and continuously improve the LLM training pipeline.
**Lưu ý quan trọng:** Thiết bị local đang chạy Antigravity HOÀN TOÀN KHÔNG CÓ GPU. Toàn bộ quá trình huấn luyện (training) sẽ được thực thi trên một máy chủ Cloud GPU (Ubuntu, không có giao diện GUI) thông qua giao thức SSH.

## Setup

To set up a new experiment, follow these steps:

1. **Agree on a run tag**: Propose a tag based on the experiment objective (e.g., `semantic-loss-exp1`). Create the branch locally: `git checkout -b autoresearch/<tag>`.
2. **Read the in-scope files**: Read these files for full context:
   - `README.md` — repository context.
   - `deep-research-report.md` — theoretical background (Semantic Loss, Logic Tensor Networks, CSR).
   - `config.py` — hyperparameters, model paths, dataset paths.
   - `dataset_utils.py` — dataset loading, preprocessing.
   - `train.py` — the core training script.
3. **Initialize results.tsv**: Create `results.tsv` locally with just the header row.
4. **Confirm and go**: Begin the autonomous experimentation loop.

## Experimentation

**What you CAN do:**
- Modify `train.py` — Implement custom loss functions (e.g., Semantic Loss for code smell rules), override `compute_loss`, change optimizer.
- Modify `dataset_utils.py` — Implement data augmentation (e.g., for Counterfactual Sensitivity Regularization - CSR), threshold functions, or preprocess static metrics.
- Modify `config.py` — Adjust batch size, learning rate, and other hyperparameters.

**What you CANNOT do:**
- Do not modify or delete `final_dataset.jsonl`.
- **Tuyệt đối không chạy lệnh `python train.py` hoặc huấn luyện model tại thiết bị local này!**

**The goal is simple: achieve the best validation metric (e.g., lowest val_loss, highest accuracy/F1-score) and ensure logical consistency.**

## Output format & Logging

When an experiment is done, log it to `results.tsv` (tab-separated) at the local machine.
Header row:
```
commit	val_metric	status	description
```

1. `commit`: short git commit hash (7 chars).
2. `val_metric`: The key metric achieved (e.g., `eval_loss` or `f1`).
3. `status`: `keep`, `discard`, or `crash`.
4. `description`: short text description of what this experiment tried.

## The experiment loop

LOOP FOREVER:

1. **Local Editing**: Tune the codebase (`train.py`, `dataset_utils.py`, `config.py`) with an experimental idea by hacking the code locally.
2. **Syntax Validation**: Run basic syntax checks locally (e.g., `python -m py_compile train.py`) to ensure no compilation errors before pushing.
3. **Local Commit & Push**:
   - `git add .`
   - `git commit -m "Experiment description"`
   - `git push origin HEAD` (Đẩy code lên remote repository).
4. **Cloud GPU Execution (via SSH)**:
   - Sử dụng lệnh SSH để kết nối vào Cloud GPU.
   - Yêu cầu Cloud GPU pull code mới nhất: `ssh <user>@<cloud-ip> "cd <project_path> && git pull origin HEAD"`
   - Kích hoạt tiến trình huấn luyện trên Cloud: `ssh <user>@<cloud-ip> "cd <project_path> && bash run_cloud.sh > run.log 2>&1"`
   - Chờ quá trình huấn luyện hoàn tất và trích xuất kết quả: `ssh <user>@<cloud-ip> "grep 'eval_' <project_path>/run.log"`
5. **Evaluate & Branching**:
   - Nếu lỗi (crash), đọc stack trace từ cloud (`ssh ... "tail -n 50 run.log"`), sửa lỗi tại local và làm lại.
   - Nếu metric cải thiện, ghi log `status: keep` vào `results.tsv` tại local. Tiếp tục phát triển.
   - Nếu metric kém hơn, ghi log `status: discard`, quay lui code tại local (`git reset --hard HEAD~1`), push ép (`git push -f origin HEAD`), và thử hướng khác.

**Autonomous Execution**: Once the experiment loop has begun, do NOT pause to ask the human if you should continue. You are autonomous. If you run out of ideas, read `deep-research-report.md` again. The loop runs indefinitely until the user manually interrupts you.
