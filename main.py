import os
import asyncio
import argparse
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

from pipeline.phase1_acquisition import run_phase1_acquisition
from pipeline.phase2_engineering import run_phase2_engineering
from pipeline.phase2_5_calibration import run_phase_2_5_calibration
from pipeline.phase3_synthesis import run_phase3_synthesis, save_auth_flow
from pipeline.phase4_validation import run_phase4_validation
from utils.logger import get_logger
from utils.state_manager import state_manager

logger = get_logger("main")

async def main():
    parser = argparse.ArgumentParser(description="PBL5 Code Smell Dataset Pipeline")
    parser.add_argument("--mode", type=str, choices=["api", "web"], default="web", 
                        help="Mode for AI labeling: 'api' (DeepSeek API) or 'web' (Camoufox browser)")
    parser.add_argument("--save-auth", action="store_true",
                        help="Open browser for manual DeepSeek login, save auth state, then exit")
    args = parser.parse_args()
    
    # Handle --save-auth separately
    if args.save_auth:
        logger.info("🔐 Opening browser for DeepSeek login...")
        await save_auth_flow()
        return
    
    logger.info("🔥 PIPELINE CODE SMELL (ASYNC & MULTIPROCESSING) 🔥")
    logger.info(f"🚀 Running in {args.mode.upper()} mode for AI Labeling")
    
    MAX_REPOS = int(os.getenv("MAX_REPOS", 10))
    
    # PHASE 1: Data Acquisition
    logger.info(">>> START PHASE 1: DATA ACQUISITION")
    await run_phase1_acquisition(max_repos=MAX_REPOS)
    
    # PHASE 2: Feature Engineering (Joern + PyDriller)
    logger.info(">>> START PHASE 2: ENGINEERING")
    await run_phase2_engineering()
    
    # PHASE 2.5: Dynamic Threshold Calibration
    logger.info(">>> START PHASE 2.5: CALIBRATION")
    run_phase_2_5_calibration()
    
    # PHASE 3: AI Synthesis (DeepSeek Distillation)
    logger.info(">>> START PHASE 3: AI SYNTHESIS")
    await run_phase3_synthesis(mode=args.mode)
    
    # PHASE 4: Validation & Dataset Compilation
    logger.info(">>> START PHASE 4: DATASET VALIDATION")
    await run_phase4_validation()
    
    logger.info("✅ All phases completed!")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.warning("\nPipeline stopped by user.")
    except Exception as e:
        logger.error(f"Fatal error in pipeline: {e}")
