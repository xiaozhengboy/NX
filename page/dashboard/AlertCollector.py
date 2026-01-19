import json
import threading

from page.dashboard.LoggingDashboard import logger
import time
from uuid import uuid4
from datetime import datetime
from pathlib import Path

from page.dashboard.Utile import ALERTS_CACHE, ALERTS_LOCK, translate_defect_name


class AlertCollector:
    """告警收集器：1. 扫描本地文件 2. 支持外部推送写入缓存"""

    def __init__(self, alert_dir='alerts'):
        # 目录配置
        self.stop_event = threading.Event()
        self.alert_dir = Path(alert_dir)

        # 运行状态控制
        self.running = True
        self.collector_thread = None

        # 确保目录存在
        self.alert_dir.mkdir(exist_ok=True, parents=True)
        self.max_cached_alerts = 1000  # 增加到5000条
        # 确保缓存清除标记
        self.last_cache_size = 0

        logger.info(f"告警收集器初始化完成，告警目录: {self.alert_dir.absolute()}")
        logger.info(f"缓存最大容量: {ALERTS_CACHE.maxlen}")


    def start(self):
        """启动告警收集器"""
        self.stop_event.clear()
        self.collector_thread = threading.Thread(
            target=self._scan_local_alerts,
            name="AlertFileScanner",
            daemon=True
        )
        self.collector_thread.start()
        logger.info("告警收集器（文件扫描）启动成功")

    def stop(self):
        """停止告警收集器"""
        self.stop_event.set()
        if self.collector_thread:
            self.collector_thread.join(timeout=5.0)
        logger.info("告警收集器（文件扫描）已停止")

    def _scan_local_alerts(self):
        """扫描本地 JSON 文件，加载历史告警"""
        while self.running:
            try:
                # 使用rglob扫描所有JSON文件（支持分层目录）
                json_files = list(self.alert_dir.rglob('**/*.json'))
                json_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)

                new_alerts = []
                for json_file in json_files:
                    try:
                        with open(json_file, 'r', encoding='utf-8') as f:
                            alert_data = json.load(f)

                        # 检查是否已在缓存中（避免重复加载）
                        with ALERTS_LOCK:
                            is_duplicate = any(
                                a.get('alert_id') == alert_data.get('alert_id')
                                for a in ALERTS_CACHE
                            )

                        if not is_duplicate:
                            # 确保图片路径正确
                            if 'relative_path' in alert_data:
                                alert_data['image_filename'] = (
                                    f"{alert_data['relative_path']}/images/"
                                    f"{alert_data.get('alert_id', 'unknown')}.jpg"
                                )
                            elif 'image_filename' not in alert_data:
                                alert_data['image_filename'] = (
                                    f"{alert_data.get('alert_id', 'unknown')}.jpg"
                                )

                            # 汉化缺陷名称
                            for detection in alert_data.get('detections', []):
                                detection['name_chinese'] = translate_defect_name(
                                    detection.get('name', '')
                                )

                            new_alerts.append(alert_data)

                    except Exception as e:
                        logger.error(f"读取告警文件失败 {json_file}: {e}")

                # 将新发现的历史告警添加到缓存（线程安全）
                if new_alerts:
                    with ALERTS_LOCK:
                        # 按时间倒序添加（最新的在前）
                        new_alerts.sort(
                            key=lambda x: x.get('detection_time', ''),
                            reverse=False
                        )
                        for alert in new_alerts:
                            ALERTS_CACHE.appendleft(alert)

                    logger.info(
                        f"从本地扫描到 {len(new_alerts)} 条新历史告警，"
                        f"当前缓存大小: {len(ALERTS_CACHE)}"
                    )

                # 检查缓存是否有变化
                current_size = len(ALERTS_CACHE)
                if current_size != self.last_cache_size:
                    logger.info(f"缓存大小变化: {self.last_cache_size} -> {current_size}")
                    self.last_cache_size = current_size

                time.sleep(5)

            except Exception as e:
                logger.error(f"本地告警扫描线程出错: {e}")
                time.sleep(10)

    def save_alert_to_local(self, alert_info, image_file=None):
        """
        将 API 接收的告警持久化到本地（按分层目录结构）
        """
        # 补全必要字段
        alert_id = alert_info.get('alert_id', str(uuid4()))
        alert_info['alert_id'] = alert_id
        alert_info['received_time'] = alert_info.get('received_time', datetime.now().isoformat())

        # 确保有检测时间
        if 'detection_time' not in alert_info:
            alert_info['detection_time'] = datetime.now().isoformat()

        # 构建分层目录
        detection_time = datetime.fromisoformat(alert_info['detection_time'].replace('Z', '+00:00'))
        camera_id = alert_info.get('camera_id', 'unknown')

        date_path = f"{camera_id}/{detection_time.year}/{detection_time.month:02d}/{detection_time.day:02d}"

        # 创建目录
        image_dir = self.alert_dir / date_path / 'images'
        json_dir = self.alert_dir / date_path / 'jsons'
        image_dir.mkdir(parents=True, exist_ok=True)
        json_dir.mkdir(parents=True, exist_ok=True)

        # 保存图片文件
        if image_file:
            image_path = image_dir / f"{alert_id}.jpg"
            image_file.save(str(image_path))
            alert_info['image_filename'] = f"{date_path}/images/{alert_id}.jpg"
        else:
            alert_info['image_filename'] = f"{date_path}/images/{alert_id}.jpg"

        # 保存JSON文件
        json_path = json_dir / f"{alert_id}.json"
        with open(json_path, 'w', encoding='utf-8') as f:
            # 添加相对路径信息
            alert_info['relative_path'] = date_path
            json.dump(alert_info, f, ensure_ascii=False, indent=2)

        return alert_info

    def get_alerts(self, page=1, per_page=100):
        """获取格式化后的告警列表（支持分页）"""
        with ALERTS_LOCK:
            total_alerts = len(ALERTS_CACHE)
            start_idx = (page - 1) * per_page
            end_idx = start_idx + per_page

            if start_idx >= total_alerts:
                alerts = []
            else:
                alerts = list(ALERTS_CACHE)[start_idx:end_idx]

            # 补全字段 + 汉化缺陷名称
            for alert in alerts:
                # 缺陷名称汉化
                for detection in alert.get('detections', []):
                    detection['name_chinese'] = translate_defect_name(detection['name'])

            return {
                'alerts': alerts,
                'pagination': {
                    'page': page,
                    'per_page': per_page,
                    'total': total_alerts,
                    'total_pages': (total_alerts + per_page - 1) // per_page if total_alerts > 0 else 1
                }
            }

    def get_stats(self):
        """获取告警统计信息"""
        with ALERTS_LOCK:
            return {
                'total_alerts': len(ALERTS_CACHE),
                'cached_alerts_limit': ALERTS_CACHE.maxlen
            }
