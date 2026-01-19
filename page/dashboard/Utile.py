import json
import threading
from collections import deque

from page.dashboard.LoggingDashboard import logger



# 核心配置：告警缓存（保留最近 1000 条）和线程锁（保证多线程安全）
ALERTS_CACHE = deque(maxlen=1000)
ALERTS_LOCK = threading.Lock()

CAMERA_CACHE = set()
CAMERA_CACHE_TIMESTAMP = 0
CAMERA_CACHE_LOCK = threading.Lock()
CAMERA_CACHE_TTL = 300  # 5分钟缓存


# 缺陷名称汉化映射
try:
    with open("./models/blade/classes.json", encoding='utf-8') as f:
        DEFECT_CHINESE_MAP = json.load(f)
except FileNotFoundError:
    logger.warning("未找到 classes.json，禁用缺陷名称汉化功能")
    DEFECT_CHINESE_MAP = {}


def translate_defect_name(english_name):
    """将英文缺陷名称转换为中文"""
    return DEFECT_CHINESE_MAP.get(english_name, english_name)