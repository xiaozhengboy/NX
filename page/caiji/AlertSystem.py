from datetime import datetime

import cv2
import json
import requests
from pathlib import Path
from page.caiji.loggermodel import logger

class AlertSystem:
    """告警系统"""

    def __init__(self, api_endpoint=None, save_dir='alerts'):
        """
        初始化告警系统
        Args:
            api_endpoint: 告警API端点（如果为None则只保存到本地）
            save_dir: 告警信息保存目录
        """
        self.api_endpoint = api_endpoint
        self.save_dir = Path(save_dir)
        self.save_dir.mkdir(exist_ok=True, parents=True)


        self.log_file = self.save_dir / 'alerts.log'

        logger.info(f"告警系统初始化完成，告警保存到: {self.save_dir}")

    def send_alert(self, camera_info, frame, detections, detection_time):
        """
        发送告警
        Args:
            camera_info: 相机信息
            frame: 原始帧
            detections: 检测结果列表
            detection_time: 检测时间
        """
        alert_id = f"{camera_info['camera_id']}_{detection_time.strftime('%Y%m%d_%H%M%S_%f')[:-3]}"

        # 构建告警信息
        alert_info = {
            'alert_id': alert_id,
            'camera_id': camera_info['camera_id'],
            'camera_name': camera_info['camera_name'],
            'detection_time': detection_time.isoformat(),
            'detections': detections,
            'detection_count': len(detections)
        }

        # 保存告警图片（返回路径信息）
        paths = self._save_alert_image(alert_id, frame, camera_info['camera_id'], detection_time)
        alert_info['image_path'] = str(paths['image_path'])
        alert_info['relative_path'] = paths['relative_path']

        # 保存JSON告警信息
        json_paths = self._save_alert_json(alert_id, alert_info, camera_info['camera_id'], detection_time)
        alert_info['json_path'] = str(json_paths['json_path'])

        # 保存告警信息到日志文件
        self._log_alert(alert_info)

        # 发送到API
        if self.api_endpoint:
            self._send_to_api(alert_info)

        # 打印告警信息
        logger.warning(
            f"检测到告警！相机: {camera_info['camera_name']} "
            f"({camera_info['camera_id']}), "
            f"缺陷数量: {len(detections)}, "
            f"存储路径: {paths['relative_path']}"
        )

        return alert_info

    def _save_alert_image(self, alert_id, frame, camera_id, detection_time):
        """保存告警图片到分层目录"""
        paths = self._get_alert_paths(alert_id, camera_id, detection_time)
        image_path = paths['image_path']

        # 保存图像
        cv2.imwrite(str(image_path), frame)

        return paths

    def _save_alert_json(self, alert_id, alert_info, camera_id, detection_time):
        """保存JSON告警信息到分层目录"""
        paths = self._get_alert_paths(alert_id, camera_id, detection_time)
        json_path = paths['json_path']

        # 在alert_info中添加路径信息
        alert_info_for_json = {
            'alert_id': alert_info['alert_id'],
            'camera_id': alert_info['camera_id'],
            'camera_name': alert_info['camera_name'],
            'detection_time': alert_info['detection_time'],
            'detections': alert_info['detections'],
            'detection_count': alert_info['detection_count'],
            'image_filename': f"{alert_id}.jpg",
            'relative_path': paths['relative_path']  # 添加相对路径
        }

        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(alert_info_for_json, f, ensure_ascii=False, indent=2)

        return paths

    def _log_alert(self, alert_info):
        """记录告警到日志文件"""
        try:
            with open(self.log_file, 'a', encoding='utf-8') as f:
                json.dump(alert_info, f, ensure_ascii=False)
                f.write('\n')
        except Exception as e:
            logger.error(f"记录告警日志失败: {e}")

    def _send_to_api(self, alert_info):
        """发送告警到API"""
        try:
            # 从alert_info中获取图片路径
            image_path = alert_info.get('image_path')
            if not image_path or not Path(image_path).exists():
                logger.warning(f"图片文件不存在: {image_path}")
                return

            # 读取图片数据
            with open(image_path, 'rb') as f:
                image_data = f.read()

            # 构建请求数据
            files = {
                'image': (f"{alert_info['alert_id']}.jpg", image_data, 'image/jpeg')
            }

            data = {
                'alert_info': json.dumps(alert_info, ensure_ascii=False)
            }

            # 发送请求
            response = requests.post(
                self.api_endpoint,
                files=files,
                data=data,
                timeout=10
            )

            if response.status_code == 200:
                logger.info(f"告警发送成功: {alert_info['alert_id']}")
            else:
                logger.error(f"告警发送失败: {response.status_code} - {response.text}")

        except Exception as e:
            logger.error(f"发送告警到API失败: {e}")

    def _get_alert_paths(self, alert_id, camera_id, detection_time):
        """
        根据告警ID、风机号和检测时间生成分层目录结构
        格式: alerts/风机号/年/月/日/
        """
        # 解析时间
        if isinstance(detection_time, str):
            dt = datetime.fromisoformat(detection_time.replace('Z', '+00:00'))
        else:
            dt = detection_time

        # 构建目录路径
        date_path = f"{camera_id}/{dt.year}/{dt.month:02d}/{dt.day:02d}"

        # 图片和JSON文件路径
        image_dir = self.save_dir / date_path / 'images'
        json_dir = self.save_dir / date_path / 'jsons'

        # 确保目录存在
        image_dir.mkdir(parents=True, exist_ok=True)
        json_dir.mkdir(parents=True, exist_ok=True)

        return {
            'image_dir': image_dir,
            'json_dir': json_dir,
            'image_path': image_dir / f"{alert_id}.jpg",
            'json_path': json_dir / f"{alert_id}.json",
            'relative_path': date_path  # 相对路径，用于前端构建URL
        }


