import cv2
import time
import json
import threading
import queue
from datetime import datetime
from page.caiji.loggermodel import logger

class CameraManager:
    """相机管理器"""

    def __init__(self, config_file='factory.json'):
        """
        初始化相机管理器
        Args:
            config_file: 相机配置文件路径
        """
        self.cameras = self.load_camera_config(config_file)
        self.camera_threads = {}
        self.camera_status = {}
        self.frame_queues = {}
        self.lock = threading.Lock()

    def load_camera_config(self, config_file):
        """加载相机配置"""
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                cameras = json.load(f)

            logger.info(f"成功加载 {len(cameras)} 个相机配置")

            # 验证配置
            valid_cameras = []
            for cam in cameras:
                required_fields = ['camera_id', 'rtsp_url', 'camera_name']
                if all(field in cam for field in required_fields):
                    cam['reconnect_attempts'] = 0
                    cam['max_reconnect_attempts'] = 5
                    cam['reconnect_delay'] = 5  # 重连延迟秒数
                    valid_cameras.append(cam)
                else:
                    logger.warning(f"相机配置缺少必要字段: {cam.get('camera_id', 'unknown')}")

            return valid_cameras
        except Exception as e:
            logger.error(f"加载相机配置失败: {e}")
            return []

    def get_camera_by_id(self, camera_id):
        """根据ID获取相机配置"""
        for cam in self.cameras:
            if cam['camera_id'] == camera_id:
                return cam
        return None

    def start_all_cameras(self):
        """启动所有相机"""
        for camera in self.cameras:
            self.start_camera(camera)

    def start_camera(self, camera):
        """启动单个相机"""
        camera_id = camera['camera_id']

        if camera_id in self.camera_threads:
            logger.warning(f"相机 {camera_id} 已经在运行")
            return False

        # 创建帧队列
        self.frame_queues[camera_id] = queue.Queue(maxsize=30)

        # 创建并启动线程
        thread = threading.Thread(
            target=self._camera_worker,
            args=(camera,),
            name=f"Camera-{camera_id}",
            daemon=True
        )

        self.camera_threads[camera_id] = thread
        self.camera_status[camera_id] = 'starting'
        thread.start()

        logger.info(f"启动相机 {camera['camera_name']} ({camera_id})")
        return True

    def _camera_worker(self, camera):
        """相机工作线程"""
        camera_id = camera['camera_id']
        rtsp_url = camera['rtsp_url']
        cap = None

        while True:
            try:
                # 尝试连接RTSP流
                logger.info(f"相机 {camera_id} 正在连接...")

                # 设置OpenCV RTSP参数
                cap = cv2.VideoCapture(rtsp_url)
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                cap.set(cv2.CAP_PROP_FPS, 10)

                if not cap.isOpened():
                    raise ConnectionError(f"无法打开RTSP流: {rtsp_url}")

                self.camera_status[camera_id] = 'connected'
                camera['reconnect_attempts'] = 0
                logger.info(f"相机 {camera_id} 连接成功")

                # 主循环：读取帧
                while True:
                    ret, frame = cap.read()

                    if not ret:
                        logger.warning(f"相机 {camera_id} 读取帧失败")
                        break

                    # 将帧放入队列
                    try:
                        # 如果队列满了，丢弃旧帧
                        if self.frame_queues[camera_id].full():
                            try:
                                self.frame_queues[camera_id].get_nowait()
                            except queue.Empty:
                                pass

                        # 添加时间戳
                        frame_info = {
                            'camera_id': camera_id,
                            'frame': frame.copy(),
                            'timestamp': datetime.now(),
                            'camera_info': camera
                        }

                        self.frame_queues[camera_id].put(frame_info, timeout=0.1)

                    except queue.Full:
                        pass
                    except Exception as e:
                        logger.error(f"处理帧队列时出错: {e}")

            except Exception as e:
                logger.error(f"相机 {camera_id} 错误: {e}")

                # 更新状态
                self.camera_status[camera_id] = 'error'

                # 清理资源
                if cap:
                    cap.release()

                # 检查重连次数
                if camera['reconnect_attempts'] < camera['max_reconnect_attempts']:
                    camera['reconnect_attempts'] += 1
                    delay = camera['reconnect_delay'] * camera['reconnect_attempts']
                    logger.info(f"相机 {camera_id} {delay}秒后尝试重连 (尝试 {camera['reconnect_attempts']}/{camera['max_reconnect_attempts']})")
                    time.sleep(delay)
                else:
                    logger.error(f"相机 {camera_id} 达到最大重连次数，停止尝试")
                    break
            finally:
                if cap:
                    cap.release()

    def stop_camera(self, camera_id):
        """停止相机"""
        if camera_id in self.camera_threads:
            # 标记为停止
            self.camera_status[camera_id] = 'stopped'

            # 清空队列
            if camera_id in self.frame_queues:
                while not self.frame_queues[camera_id].empty():
                    try:
                        self.frame_queues[camera_id].get_nowait()
                    except:
                        break

            logger.info(f"停止相机 {camera_id}")

    def stop_all_cameras(self):
        """停止所有相机"""
        for camera_id in list(self.camera_threads.keys()):
            self.stop_camera(camera_id)

    def get_frame(self, camera_id, timeout=1.0):
        """从相机获取一帧"""
        try:
            if camera_id not in self.frame_queues:
                return None

            return self.frame_queues[camera_id].get(timeout=timeout)
        except queue.Empty:
            return None
        except Exception as e:
            logger.error(f"获取帧失败: {e}")
            return None

    def get_camera_status(self):
        """获取所有相机状态"""
        status_report = []
        for camera in self.cameras:
            camera_id = camera['camera_id']
            status = {
                'camera_id': camera_id,
                'camera_name': camera['camera_name'],
                'status': self.camera_status.get(camera_id, 'unknown'),
                'reconnect_attempts': camera['reconnect_attempts'],
                'queue_size': self.frame_queues.get(camera_id, queue.Queue()).qsize() if camera_id in self.frame_queues else 0
            }
            status_report.append(status)
        return status_report