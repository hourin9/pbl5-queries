import json
import os
import pickle
import subprocess
from concurrent.futures import ProcessPoolExecutor
from functools import partial

from pydriller import Repository
from tqdm import tqdm  # có thể cài đặt nếu chưa có: pip install tqdm


def _get_commit_hashes(repo_path):
    """Lấy danh sách commit hash (không phải merge) theo thứ tự thời gian tăng dần."""
    cmd = [
        "git",
        "-C",
        repo_path,
        "log",
        "--no-merges",
        "--pretty=format:%H",
        "--reverse",
    ]
    output = subprocess.check_output(cmd, text=True)
    hashes = [h.strip() for h in output.splitlines() if h.strip()]
    return hashes


def _process_commit_range(repo_path, commit_hashes, method_map, extensions_set):
    """Xử lý một đoạn commit trong một tiến trình riêng."""
    from pydriller import Repository

    changes_by_method = {}  # mid -> list of change dicts

    if not commit_hashes:
        return changes_by_method

    from_commit = commit_hashes[0]
    to_commit = commit_hashes[-1]

    for commit in Repository(
        repo_path,
        from_commit=from_commit,
        to_commit=to_commit,
        only_no_merge=True,
        only_modifications_with_file_types=list(extensions_set),
    ).traverse_commits():
        for m_file in commit.modified_files:
            # Kiểm tra nhanh extension (dù đã lọc, nhưng để an toàn)
            if not any(m_file.filename.endswith(ext) for ext in extensions_set):
                continue
            for method in m_file.changed_methods:
                key = (m_file.filename, method.name)
                if key not in method_map:
                    continue
                mid = method_map[key]
                dmm = (
                    m_file.diff_parsed.get("dmm_unit_size")
                    if hasattr(m_file, "diff_parsed")
                    else None
                )
                change = {
                    "h": commit.hash[:8],
                    "d": str(commit.author_date),
                    "msg": commit.msg.strip(),
                    "dmm": {
                        "sz": round(dmm, 4) if dmm is not None else None,
                        "cx": (
                            round(commit.dmm_unit_complexity, 4)
                            if commit.dmm_unit_complexity
                            else None
                        ),
                        "if": (
                            round(commit.dmm_unit_interfacing, 4)
                            if commit.dmm_unit_interfacing
                            else None
                        ),
                    },
                    "nd": commit.deletions,
                    "ni": commit.insertions,
                    "cxc": method.complexity,
                    "diff": m_file.diff,
                }
                changes_by_method.setdefault(mid, []).append(change)
    return changes_by_method


def build_method_evolution(joern_json_path, repo_path, output_dir):
    # 1. Đọc dữ liệu từ Joern
    with open(joern_json_path, "r", encoding="utf-8") as f:
        joern_data = json.load(f)

    method_map = {}  # (file, method_name) -> method_id
    method_histories = {}  # method_id -> {mid, sa, ev: []}
    extensions = set()  # tập các đuôi file cần quan tâm

    for node in joern_data.get("nodes", []):
        method_name = node["name"]
        method_id = node["id"]
        file_path = node["file_path"]
        key = (file_path, method_name)
        method_map[key] = method_id

        # Lấy đuôi file
        ext = os.path.splitext(file_path)[1]
        if ext:
            extensions.add(ext)

        f = node.get("features", {})
        static = {
            "id": method_id,
            "name": method_name,
            "file": file_path,
            "f": {
                "loc": f.get("loc"),
                "cc": f.get("cyclomatic_complexity"),
                "fi": f.get("fan_in"),
                "fo": f.get("fan_out"),
                "c": f.get("code", ""),
            },
        }
        method_histories[method_id] = {"mid": method_id, "sa": static, "ev": []}

    if not method_map:
        print("Không tìm thấy method nào trong file Joern. Thoát.")
        return

    # 2. Cache – kiểm tra xem đã có kết quả thô chưa
    cache_path = os.path.join(output_dir, ".method_evolution_cache.pkl")
    cache_valid = False
    all_changes_by_method = None

    if os.path.exists(cache_path):
        with open(cache_path, "rb") as cf:
            cached = pickle.load(cf)
            # Kiểm tra tính hợp lệ: repo_path, joern_json_path, extensions, method_map keys
            if (
                cached.get("repo_path") == repo_path
                and cached.get("joern_json_path") == joern_json_path
                and cached.get("extensions") == extensions
                and cached.get("method_map_keys") == set(method_map.keys())
            ):
                all_changes_by_method = cached["changes_by_method"]
                cache_valid = True
                print("Sử dụng cache có sẵn. Bỏ qua quét commit.")

    if not cache_valid:
        print("Đang lấy danh sách commit (không merge) từ git...")
        commit_hashes = _get_commit_hashes(repo_path)
        if not commit_hashes:
            print("Không tìm thấy commit nào.")
            return

        # Chia commit thành các đoạn để xử lý song song
        num_workers = min(os.cpu_count(), 8)  # tối đa 8 tiến trình
        chunk_size = max(1, len(commit_hashes) // num_workers)
        chunks = [
            commit_hashes[i : i + chunk_size]
            for i in range(0, len(commit_hashes), chunk_size)
        ]

        print(
            f"Chia {len(commit_hashes)} commit thành {len(chunks)} đoạn, dùng {num_workers} tiến trình."
        )
        process_func = partial(
            _process_commit_range,
            repo_path,
            extensions_set=extensions,
            method_map=method_map,
        )

        all_changes_by_method = {}
        with ProcessPoolExecutor(max_workers=num_workers) as executor:
            futures = [executor.submit(process_func, chunk) for chunk in chunks]
            for future in tqdm(futures, desc="Đang xử lý commit"):
                result = future.result()
                for mid, changes in result.items():
                    all_changes_by_method.setdefault(mid, []).extend(changes)

        # Lưu cache
        os.makedirs(output_dir, exist_ok=True)
        cache_data = {
            "repo_path": repo_path,
            "joern_json_path": joern_json_path,
            "extensions": extensions,
            "method_map_keys": set(method_map.keys()),
            "changes_by_method": all_changes_by_method,
        }
        with open(cache_path, "wb") as cf:
            pickle.dump(cache_data, cf)
        print("Đã lưu cache.")

    # 3. Gắn các thay đổi vào method_histories và ghi file JSON
    os.makedirs(output_dir, exist_ok=True)
    count = 0
    for mid, changes in all_changes_by_method.items():
        if changes:
            # Sắp xếp theo thời gian (dựa trên trường "d")
            changes.sort(key=lambda x: x["d"])
            method_histories[mid]["ev"] = changes
            out_path = os.path.join(output_dir, f"{mid}.json")
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(
                    method_histories[mid], f, separators=(",", ":"), ensure_ascii=False
                )
            count += 1

    print(f"Hoàn thành trích xuất! Lưu {count} file JSON tại: {output_dir}")
