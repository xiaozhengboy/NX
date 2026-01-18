# 文件名：real_time_blade_monitoring.py
"""
风机叶片实时检测系统
支持多路RTSP流实时检测，异常告警推送
"""
import time
from pathlib import Path
import signal
import sys
import traceback
import atexit
import json

from page.caiji.loggermodel import logger
from page.caiji.AlertSystem import AlertSystem
from page.caiji.BladeDetector import BladeDetector
from page.caiji.CameraManager import CameraManager
from page.caiji.DetectionWorker import DetectionWorker
from page.caiji.HealthMonitor import HealthMonitor



def load_config():
    """加载配置文件"""
    config = {
        # 模型配置
        'seg_weights': './models/blade/blade_seg.onnx',
        'det_weights': './models/blade/best.onnx',
        'conf_threshold': 0.6,
        'device': '0',  # GPU设备ID

        # 相机配置
        'camera_config': 'factory.json',

        # 检测配置
        'detection_interval': 1.0,  # 检测间隔（秒）
        'batch_size': 1,

        # 告警配置
        'alert_api_endpoint': None,  # 设置为实际的API端点，如 'http://alert-system/api/alerts'
        'alert_save_dir': 'alerts',

        # Web API配置
        'enable_web_api': True,
        'api_port': 8080,

        # 性能配置
        'max_queue_size': 30,
        'frame_skip_ratio': 3,  # 每3帧处理1帧
    }

    # 尝试从配置文件加载
    config_file = Path('conf/config.json')
    if config_file.exists():
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                user_config = json.load(f)
                config.update(user_config)
            logger.info("从配置文件加载配置")
        except Exception as e:
            logger.error(f"加载配置文件失败: {e}")

    return config


class BladeMonitoringSystem:
    """风机叶片监控系统主类"""

    def __init__(self, config):
        """
        初始化监控系统
        Args:
            config: 配置字典
        """
        self.config = config
        self.camera_manager = None
        self.detector = None
        self.alert_system = None
        self.detection_worker = None
        self.health_monitor = None

        # 创建结果目录
        self.result_dir = Path('result')
        self.result_dir.mkdir(exist_ok=True)

        # 信号处理
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)

        # 注册退出处理
        atexit.register(self.cleanup)

    def initialize(self):
        """初始化系统组件"""
        logger.info("初始化风机叶片监控系统...")

        try:
            # 1. 初始化相机管理器
            self.camera_manager = CameraManager(
                config_file=self.config.get('camera_config', './factory.json')
            )

            # 2. 初始化叶片检测器
            self.detector = BladeDetector(
                seg_weights=self.config.get('seg_weights', './models/blade/blade_seg.onnx'),
                det_weights=self.config.get('det_weights', './models/blade/best.onnx'),
                conf_threshold=self.config.get('conf_threshold', 0.45),
                device=self.config.get('device', '0')
            )

            # 3. 初始化告警系统
            self.alert_system = AlertSystem(
                api_endpoint=self.config.get('alert_api_endpoint', 'http://localhost:8080/api/alerts'),
                save_dir=self.config.get('alert_save_dir', 'alerts')
            )

            # 4. 初始化检测工作线程
            self.detection_worker = DetectionWorker(
                camera_manager=self.camera_manager,
                blade_detector=self.detector,
                alert_system=self.alert_system,
                detection_interval=self.config.get('detection_interval', 1.0),  # 检测间隔
                batch_size=self.config.get('batch_size', 1)
            )

            # 5. 初始化健康监控
            self.health_monitor = HealthMonitor(
                camera_manager=self.camera_manager,
                detection_worker=self.detection_worker
            )

            logger.info("系统初始化完成")
            return True

        except Exception as e:
            logger.error(f"系统初始化失败: {e}")
            logger.error(traceback.format_exc())
            return False

    def start(self):
        """启动监控系统"""
        logger.info("启动风机叶片监控系统...")

        try:
            # 1. 启动相机管理器
            self.camera_manager.start_all_cameras()
            time.sleep(5)  # 等待相机连接

            # 2. 启动检测工作线程
            self.detection_worker.start()

            # 3. 启动健康监控
            self.health_monitor.start()

            logger.info("风机叶片监控系统启动完成")
            return True

        except Exception as e:
            logger.error(f"启动系统失败: {e}")
            logger.error(traceback.format_exc())
            return False

    def signal_handler(self, signum, frame):
        """信号处理"""
        logger.info(f"收到信号 {signum}，正在关闭系统...")
        self.cleanup()
        sys.exit(0)

    def cleanup(self):
        """清理资源"""
        logger.info("正在清理系统资源...")

        try:
            if self.health_monitor:
                self.health_monitor.stop()

            if self.detection_worker:
                self.detection_worker.stop()

            if self.camera_manager:
                self.camera_manager.stop_all_cameras()

            logger.info("系统资源清理完成")

        except Exception as e:
            logger.error(f"清理资源时出错: {e}")

    def run(self):
        """运行主循环"""
        logger.info("风机叶片实时检测系统开始运行")

        try:
            # 保持主线程运行
            while True:
                # 每60秒打印一次状态
                health_report = self.health_monitor.get_health_report() if self.health_monitor else {}

                logger.info(
                    f"系统运行中... 在线相机: {health_report.get('online_cameras', 0)}/"
                    f"{health_report.get('total_cameras', 0)}, "
                    f"运行时间: {health_report.get('system_uptime', 0):.0f}秒"
                )

                time.sleep(60)

        except KeyboardInterrupt:
            logger.info("收到键盘中断，正在关闭系统...")
        except Exception as e:
            logger.error(f"主循环出错: {e}")
        finally:
            self.cleanup()

def main():
    """主函数"""
    print("=" * 60)
    print("风机叶片实时检测系统")
    print("=" * 60)

    # 加载配置
    config = load_config()

    # 创建监控系统
    monitoring_system = BladeMonitoringSystem(config)

    # 初始化系统
    if not monitoring_system.initialize():
        logger.error("系统初始化失败，退出")
        return

    # 启动系统
    if not monitoring_system.start():
        logger.error("系统启动失败，退出")
        return

    # 运行主循环
    monitoring_system.run()


if __name__ == "__main__":
    main()