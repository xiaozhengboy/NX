import time
import threading
from page.caiji.loggermodel import logger


class DetectionWorker:
    """检测工作线程"""

    def __init__(self, camera_manager, blade_detector, alert_system,
                 detection_interval=1.0, batch_size=1):
        """
        初始化检测工作线程
        Args:
            camera_manager: 相机管理器
            blade_detector: 叶片检测器
            alert_system: 告警系统
            detection_interval: 检测间隔（秒）
            batch_size: 批处理大小
        """
        self.camera_manager = camera_manager
        self.detector = blade_detector
        self.alert_system = alert_system
        self.detection_interval = detection_interval
        self.batch_size = batch_size

        self.running = False
        self.worker_thread = None
        self.detection_count = 0
        self.alert_count = 0
        self.frame_skip_counter = 0

    def start(self):
        """启动检测工作线程"""
        if self.running:
            logger.warning("检测工作线程已经在运行")
            return

        self.running = True
        self.worker_thread = threading.Thread(
            target=self._worker_loop,
            name="DetectionWorker",
            daemon=True
        )
        self.worker_thread.start()
        logger.info("检测工作线程启动")

    def stop(self):
        """停止检测工作线程"""
        self.running = False
        if self.worker_thread:
            self.worker_thread.join(timeout=5.0)
        logger.info("检测工作线程停止")

    def _worker_loop(self):
        """工作线程主循环"""
        last_detection_time = time.time()

        while self.running:
            try:
                current_time = time.time()

                # 控制检测频率
                if current_time - last_detection_time < self.detection_interval:
                    time.sleep(0.01)
                    continue

                # 遍历所有相机
                for camera in self.camera_manager.cameras:
                    camera_id = camera['camera_id']

                    # 跳过未连接的相机
                    if self.camera_manager.camera_status.get(camera_id) != 'connected':
                        continue

                    # 获取帧
                    frame_info = self.camera_manager.get_frame(camera_id, timeout=0.1)
                    if not frame_info:
                        continue

                    # 跳过一些帧以降低负载
                    self.frame_skip_counter += 1
                    if self.frame_skip_counter % 3 != 0:  # 每3帧处理1帧
                        continue

                    # 执行检测
                    detections, seg_img, annotated_img = self.detector.detect(
                        frame_info['frame']
                    )

                    self.detection_count += 1

                    # 如果有检测结果，发送告警
                    if detections:
                        self.alert_count += 1

                        # 发送告警
                        self.alert_system.send_alert(
                            camera_info=frame_info['camera_info'],
                            frame=annotated_img,
                            detections=detections,
                            detection_time=frame_info['timestamp']
                        )

                    # 记录检测统计
                    if self.detection_count % 100 == 0:
                        logger.info(
                            f"检测统计: 总检测次数={self.detection_count}, "
                            f"告警次数={self.alert_count}"
                        )

                last_detection_time = current_time

            except Exception as e:
                logger.error(f"检测工作线程出错: {e}")
                time.sleep(1)

    def get_stats(self):
        """获取统计信息"""
        return {
            'detection_count': self.detection_count,
            'alert_count': self.alert_count,
            'frame_skip_counter': self.frame_skip_counter
        }