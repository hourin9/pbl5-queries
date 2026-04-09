import os
import asyncio
import argparse
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

from pipeline.phase1_acquisition import run_phase1_acquisition
from pipeline.phase2_engineering import run_phase2_engineering
from pipeline.phase3_synthesis import run_phase3_synthesis
from pipeline.phase4_validation import run_phase4_validation
from utils.logger import get_logger

logger = get_logger("main")

async def main():
    parser = argparse.ArgumentParser(description="PBL5 Code Smell Dataset Pipeline")
    parser.add_argument("--mode", type=str, choices=["api", "web"], default="api", 
                        help="Mode for AI labeling: 'api' (DeepSeek API) or 'web' (Camoufox browser)")
    args = parser.parse_args()
    
    logger.info("🔥 KHỞI CHẠY PIPELINE CODE SMELL (ASYNC & MULTIPROCESSING) 🔥")
    logger.info(f"🚀 Running in {args.mode.upper()} mode for AI Labeling")
    
    # Lấy thông số từ môi trường
    MAX_REPOS = int(os.getenv("MAX_REPOS", 10))
    
    # ----------------------------------------------------
    # PHASE 1: Thu thập GitHub
    # ----------------------------------------------------
    logger.info(">>> START PHASE 1: DATA ACQUISITION")
    await run_phase1_acquisition(max_repos=MAX_REPOS)
    
    # ----------------------------------------------------
    # PHASE 2: Trích xuất đặc trưng (Joern + PyDriller)
    # ----------------------------------------------------
    logger.info(">>> START PHASE 2: ENGINEERING")
    await run_phase2_engineering()
    
    # ----------------------------------------------------
    # PHASE 3: Gán nhãn AI (DeepSeek Teacher Model)
    # ----------------------------------------------------
    logger.info(">>> START PHASE 3: AI SYNTHESIS")
    await run_phase3_synthesis(mode=args.mode)
    
    # ----------------------------------------------------
    # PHASE 4: Kiểm thử và đóng gói Dataset
    # ----------------------------------------------------
    logger.info(">>> START PHASE 4: VALIDATION")
    await run_phase4_validation()
    
    logger.info("🎉 PIPELINE HOÀN TẤT! Dataset cuối cùng tại dataset_output/final_dataset.jsonl")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.warning("Pipeline bị dừng bởi người dùng.")
