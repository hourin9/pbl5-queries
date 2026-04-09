import sys
import os
from loguru import logger

# Đảm bảo có thư mục lưu log
os.makedirs("logs", exist_ok=True)

# Tùy chỉnh loguru
logger.remove()
logger.add(
    sys.stderr,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    level="INFO",
)
logger.add(
    "logs/pipeline.log",
    rotation="10 MB",
    retention="7 days",
    level="DEBUG",
)

def get_logger(name=None):
    if name:
        return logger.bind(name=name)
    return logger
