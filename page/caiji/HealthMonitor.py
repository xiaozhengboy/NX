import time
import threading
from datetime import datetime
from page.caiji.loggermodel import logger

class HealthMonitor:
    """健康监控器"""

    def __init__(self, camera_manager, detection_worker):
        """
        初始化健康监控器
        Args:
            camera_manager: 相机管理器
            detection_worker: 检测工作线程
        """
        self.camera_manager = camera_manager
        self.detection_worker = detection_worker
        self.running = False
        self.monitor_thread = None

        # 统计信息
        self.start_time = datetime.now()
        self.performance_stats = {
            'total_frames_processed': 0,
            'average_processing_time': 0,
            'system_uptime': 0
        }

    def start(self):
        """启动健康监控"""
        self.running = True
        self.monitor_thread = threading.Thread(
            target=self._monitor_loop,
            name="HealthMonitor",
            daemon=True
        )
        self.monitor_thread.start()
        logger.info("健康监控启动")

    def stop(self):
        """停止健康监控"""
        self.running = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=3.0)
        logger.info("健康监控停止")

    def _monitor_loop(self):
        """监控循环"""
        check_interval = 30  # 每30秒检查一次

        while self.running:
            try:
                # 获取相机状态
                camera_status = self.camera_manager.get_camera_status()

                # 统计在线相机数量
                online_cameras = [s for s in camera_status if s['status'] == 'connected']
                offline_cameras = [s for s in camera_status if s['status'] != 'connected']

                # 获取检测统计
                detection_stats = self.detection_worker.get_stats() if self.detection_worker else {}

                # 更新性能统计
                self.performance_stats.update({
                    'online_cameras': len(online_cameras),
                    'offline_cameras': len(offline_cameras),
                    'total_cameras': len(camera_status),
                    'system_uptime': (datetime.now() - self.start_time).total_seconds(),
                    'detection_count': detection_stats.get('detection_count', 0),
                    'alert_count': detection_stats.get('alert_count', 0)
                })

                # 记录状态
                logger.info(
                    f"系统状态: 在线相机={len(online_cameras)}/{len(camera_status)}, "
                    f"检测次数={detection_stats.get('detection_count', 0)}, "
                    f"告警次数={detection_stats.get('alert_count', 0)}"
                )

                # 如果有离线相机，尝试重启
                for camera in offline_cameras:
                    if camera['status'] == 'error':
                        logger.warning(f"相机 {camera['camera_id']} 离线，尝试重启...")
                        cam_config = self.camera_manager.get_camera_by_id(camera['camera_id'])
                        if cam_config:
                            self.camera_manager.stop_camera(camera['camera_id'])
                            time.sleep(2)
                            self.camera_manager.start_camera(cam_config)

                time.sleep(check_interval)

            except Exception as e:
                logger.error(f"健康监控出错: {e}")
                time.sleep(check_interval)

    def get_health_report(self):
        """获取健康报告"""
        return self.performance_stats