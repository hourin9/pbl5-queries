import os
import shutil
import datetime

def archive():
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_dir = f"archive/run_{timestamp}"
    
    folders_to_archive = ["data", "method_evolutions", "ground_truth", "dataset_output", "temp_data"]
    
    # Check if there is anything to archive
    if not any(os.path.exists(f) for f in folders_to_archive):
        print("Không có dữ liệu cũ nào cần archive.")
        return

    os.makedirs(archive_dir, exist_ok=True)
    
    for folder in folders_to_archive:
        if os.path.exists(folder):
            dest = os.path.join(archive_dir, folder)
            shutil.move(folder, dest)
            print(f"Đã di chuyển '{folder}' vào '{dest}'")
            
    print(f"\n✅ Đã dọn dẹp toàn bộ dữ liệu cũ. Sẵn sàng cho lượt chạy mới!")

if __name__ == "__main__":
    archive()
