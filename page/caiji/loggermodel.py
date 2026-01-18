import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

# 配置日志
"""配置日志系统"""
logger = logging.getLogger('blade_monitoring')
logger.setLevel(logging.INFO)

# 创建日志目录
log_dir = Path('logs')
log_dir.mkdir(exist_ok=True)

# 文件处理器
file_handler = RotatingFileHandler(
    log_dir / 'blade_monitoring.log',
    maxBytes=10 * 1024 * 1024,  # 10MB
    backupCount=5,
    encoding='utf-8'
)
file_handler.setLevel(logging.INFO)

# 控制台处理器
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)

# 格式化
formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
file_handler.setFormatter(formatter)
console_handler.setFormatter(formatter)

logger.addHandler(file_handler)
logger.addHandler(console_handler)

logger = logging.getLogger(__name__)  # 创建 logger 对象