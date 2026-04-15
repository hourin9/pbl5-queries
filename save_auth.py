import asyncio
import os
import sys
from pipeline.phase3_synthesis import WebDeepSeekLabeler

async def save_on_close():
    labeler = WebDeepSeekLabeler()
    print("🚀 Đang mở trình duyệt Camoufox (Visible Mode)...")
    await labeler.init_browser(force_visible=True)
    
    print("\n---------------------------------------------------------")
    print("🔑 HÃY ĐĂNG NHẬP VÀO TRANG CHỦ DEEPSEEK.")
    print("👉 SAU KHI ĐĂNG NHẬP XONG, HÃY TỰ TAY ĐÓNG (CLICK X) CỬA SỔ TRÌNH DUYỆT ĐỂ LƯU AUTH.")
    print("---------------------------------------------------------\n")
    
    try:
        # Chờ cho đến khi bạn đóng trang web (đóng tab hoặc trình duyệt)
        # Timeout trong vòng 20 phút cho thong thả
        await labeler.page.wait_for_event("close", timeout=120000)
    except Exception:
        print("⏳ Thời gian chờ đăng nhập đã hết. Đang kiểm tra lại...")
    
    # Ở đây, Context vẫn còn sống dù Page đã tắt
    print("💾 Đã nhận diện trình duyệt đóng! Đang chốt chặn và lưu file auth_state.json...")
    try:
        await labeler._save_auth()
        print("✅ Thành công! File hiện đã có tại data/auth_state.json")
    except Exception as e:
        print(f"❌ Có lỗi khi lưu: {e}")
    finally:
        # Dọn dẹp tài nguyên
        if labeler.browser:
            await labeler.close()

if __name__ == "__main__":
    os.makedirs("data", exist_ok=True)
    asyncio.run(save_on_close())
