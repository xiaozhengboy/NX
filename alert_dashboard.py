from flask import Flask, render_template, jsonify, send_from_directory, request
from flask_cors import CORS
import json
from pathlib import Path
from datetime import datetime
import threading
import logging
from collections import deque
import time
from uuid import uuid4

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 初始化
app = Flask(__name__)
CORS(app)

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
    """将英文缺陷名称转换为中文（保持原代码 2 的功能）"""
    return DEFECT_CHINESE_MAP.get(english_name, english_name)


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

@app.route('/')
def index():
    """主页 - 告警展示仪表板（保留原代码 2 功能）"""
    return render_template("alter_dashboard.html")


@app.route('/api/alerts', methods=['GET'])
def get_alerts_api():
    """GET - 获取告警列表（支持分页）"""
    try:
        collector = app.config.get('alert_collector')
        if not collector:
            return jsonify({
                'status': 'error',
                'message': '告警收集器未初始化',
                'alerts': [],
                'stats': {'total_alerts': 0}
            })

        # 获取分页参数
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 100, type=int)

        # 确保参数合法
        page = max(1, page)
        per_page = max(1, min(100, per_page))  # 限制每页最多100条

        # 获取分页后的告警数据
        result = collector.get_alerts(page=page, per_page=per_page)
        alerts = result['alerts']
        pagination = result['pagination']
        stats = collector.get_stats()

        return jsonify({
            'status': 'success',
            'alerts': alerts,
            'pagination': pagination,
            'stats': stats
        })

    except Exception as e:
        logger.error(f"获取告警列表 API 出错: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/alerts', methods=['POST'])
def receive_alert_api():
    """POST - 接收外部系统推送的告警"""
    try:
        collector = app.config.get('alert_collector')
        if not collector:
            return jsonify({'status': 'error', 'message': '告警收集器未初始化'}), 503

        # 1. 解析请求数据
        alert_info = json.loads(request.form.get('alert_info', '{}'))
        image_file = request.files.get('image')

        # 2. 补全字段并持久化到本地
        alert_info = collector.save_alert_to_local(alert_info, image_file)

        # 3. 线程安全地添加到缓存（实时展示）
        with ALERTS_LOCK:
            # 直接添加到缓存头部（最新告警优先展示）
            ALERTS_CACHE.appendleft(alert_info)


        # 4. 更新风机号缓存
        camera_id = alert_info.get('camera_id')
        if camera_id:
            with CAMERA_CACHE_LOCK:
                CAMERA_CACHE.add(camera_id)

        logger.info(f"成功接收并缓存外部推送告警: {alert_info['alert_id']}")
        return jsonify({
            'status': 'success',
            'message': '告警接收成功并已展示',
            'alert_id': alert_info['alert_id']
        })

    except Exception as e:
        logger.error(f"接收外部推送告警出错: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/alerts/images/<path:filename>')
def serve_alert_image(filename):
    """提供告警图片访问（支持分层目录）"""
    try:
        collector = app.config.get('alert_collector')
        if not collector:
            return "告警收集器未初始化", 500

        # 使用安全的路径拼接
        image_path = collector.alert_dir / filename

        # 安全检查：确保路径在alert_dir内
        try:
            image_path.relative_to(collector.alert_dir)
        except ValueError:
            return "非法路径", 403

        return send_from_directory(collector.alert_dir, filename)

    except Exception as e:
        logger.error(f"提供告警图片失败: {e}")
        return str(e), 404


@app.route('/api/health')
def health_check():
    collector = app.config.get('alert_collector')
    stats = collector.get_stats() if collector else {'total_alerts': 0}
    # 加锁读取缓存长度
    with ALERTS_LOCK:
        cached_count = len(ALERTS_CACHE)
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'cached_alerts_count': cached_count,
        'total_alerts_persisted': stats.get('total_alerts', 0)
    })



# 新增文件搜索API和智能切换逻辑
@app.route('/api/alerts/search', methods=['GET'])
def search_alerts_by_time():
    """按时间范围从文件系统搜索历史告警（优化版）"""
    try:
        # 获取查询参数
        start_time = request.args.get('start_time')
        end_time = request.args.get('end_time')
        camera_id = request.args.get('camera_id')
        defect_name = request.args.get('defect_name')
        min_confidence = request.args.get('min_confidence')
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 100, type=int)

        # 必须提供时间范围
        if not start_time or not end_time:
            return jsonify({
                'status': 'error',
                'message': '历史搜索必须提供开始时间和结束时间',
                'alerts': [],
                'pagination': {
                    'page': page,
                    'per_page': per_page,
                    'total': 0,
                    'total_pages': 0
                }
            })

        # 解析时间参数
        try:
            start_dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
            end_dt = datetime.fromisoformat(end_time.replace('Z', '+00:00'))
        except ValueError:
            return jsonify({'status': 'error', 'message': '时间格式不正确'}), 400

        # 计算要搜索的目录范围
        collector = app.config.get('alert_collector')
        if not collector:
            return jsonify({'status': 'error', 'message': '告警收集器未初始化'}), 503

        matched_alerts = []

        # 根据camera_id和日期范围确定搜索目录
        if camera_id:
            # 搜索特定风机
            search_dirs = []
            current_dt = start_dt.replace(day=1)  # 从开始时间的月份开始
            while current_dt <= end_dt:
                search_dir = collector.alert_dir / f"{camera_id}/{current_dt.year}/{current_dt.month:02d}"
                if search_dir.exists():
                    search_dirs.append(search_dir)
                # 移动到下个月
                if current_dt.month == 12:
                    current_dt = current_dt.replace(year=current_dt.year + 1, month=1)
                else:
                    current_dt = current_dt.replace(month=current_dt.month + 1)
        else:
            # 搜索所有风机
            search_dirs = [collector.alert_dir]

        # 遍历搜索目录
        for search_dir in search_dirs:
            # 查找该目录下的所有JSON文件
            for json_file in search_dir.rglob('**/*.json'):
                try:
                    with open(json_file, 'r', encoding='utf-8') as f:
                        alert = json.load(f)

                    # 时间筛选
                    detection_time = alert.get('detection_time', '')
                    if not detection_time:
                        continue

                    try:
                        alert_dt = datetime.fromisoformat(detection_time.replace('Z', '+00:00'))
                    except ValueError:
                        continue

                    if alert_dt < start_dt or alert_dt > end_dt:
                        continue

                    # 风机筛选（如果指定了camera_id）
                    if camera_id and alert.get('camera_id') != camera_id:
                        continue

                    # 缺陷筛选
                    if defect_name:
                        detections = alert.get('detections', [])
                        has_defect = any(det.get('name') == defect_name for det in detections)
                        if not has_defect:
                            continue

                    # 置信度筛选
                    if min_confidence:
                        detections = alert.get('detections', [])
                        if detections:
                            max_conf = max(det.get('conf', 0) for det in detections)
                            if max_conf < float(min_confidence):
                                continue

                    # 补全图片路径
                    if 'relative_path' in alert:
                        alert['image_filename'] = f"{alert['relative_path']}/images/{alert['alert_id']}.jpg"
                    elif 'image_filename' not in alert:
                        alert['image_filename'] = f"{alert['alert_id']}.jpg"

                    # 汉化缺陷名称
                    for detection in alert.get('detections', []):
                        detection['name_chinese'] = translate_defect_name(detection['name'])

                    matched_alerts.append(alert)

                except Exception as e:
                    logger.error(f"读取告警文件失败 {json_file}: {e}")

        # 按时间倒序排序
        matched_alerts.sort(key=lambda x: x.get('detection_time', ''), reverse=True)

        # 分页
        total = len(matched_alerts)
        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        paginated_alerts = matched_alerts[start_idx:end_idx]

        return jsonify({
            'status': 'success',
            'alerts': paginated_alerts,
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total': total,
                'total_pages': (total + per_page - 1) // per_page if total > 0 else 1
            },
            'search_mode': 'file'
        })

    except Exception as e:
        logger.error(f"文件搜索失败: {e}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


@app.route('/api/cameras', methods=['GET'])
def get_all_cameras():
    """获取所有风机号列表 - 使用缓存"""
    try:
        global CAMERA_CACHE, CAMERA_CACHE_TIMESTAMP

        collector = app.config.get('alert_collector')
        if not collector:
            return jsonify({'status': 'error', 'message': '告警收集器未初始化', 'cameras': []}), 503

        current_time = time.time()

        # 检查缓存是否过期
        with CAMERA_CACHE_LOCK:
            if (current_time - CAMERA_CACHE_TIMESTAMP < CAMERA_CACHE_TTL and
                    len(CAMERA_CACHE) > 0):
                # 使用缓存
                camera_list = sorted(list(CAMERA_CACHE))
                return jsonify({
                    'status': 'success',
                    'cameras': camera_list,
                    'count': len(camera_list),
                    'source': 'cache',
                    'cached': True
                })

        # 缓存过期或为空，重新扫描
        cameras = set()
        alert_dir = collector.alert_dir

        # 方法1：扫描风机号文件夹
        if alert_dir.exists():
            try:
                # 获取所有第一级子目录
                for item in alert_dir.iterdir():
                    if item.is_dir():
                        camera_id = item.name

                        # 排除已知的非风机目录
                        exclude_dirs = {'images', 'jsons', 'temp', 'backup', 'log', 'logs', '.git'}
                        if camera_id in exclude_dirs:
                            continue

                        # 检查目录是否有内容（有JSON文件或子目录）
                        has_content = False

                        # 快速检查：看是否有JSON文件
                        json_files = list(item.rglob('*.json'))
                        if json_files:
                            has_content = True
                        else:
                            # 或者有年份子目录
                            for sub_item in item.iterdir():
                                if sub_item.is_dir() and sub_item.name.isdigit() and len(sub_item.name) == 4:
                                    has_content = True
                                    break

                        if has_content:
                            cameras.add(camera_id)
            except Exception as e:
                logger.warning(f"扫描风机目录时出错: {e}")

        # 方法2：从缓存中补充当前告警的风机号
        with ALERTS_LOCK:
            for alert in ALERTS_CACHE:
                if alert.get('camera_id'):
                    cameras.add(alert['camera_id'])

        # 更新缓存
        with CAMERA_CACHE_LOCK:
            CAMERA_CACHE = cameras
            CAMERA_CACHE_TIMESTAMP = current_time

        # 排序风机号（自然排序）
        camera_list = natural_sort(list(cameras))

        return jsonify({
            'status': 'success',
            'cameras': camera_list,
            'count': len(camera_list),
            'source': 'directory_scan',
            'cached': False
        })

    except Exception as e:
        logger.error(f"获取风机列表失败: {e}")
        return jsonify({'status': 'error', 'message': str(e), 'cameras': []}), 500


def cleanup():
    """系统关闭时的清理函数"""
    collector = app.config.get('alert_collector')
    if collector:
        collector.stop()
    logger.info("系统清理完成，已停止所有后台线程")


def start_combined_server(host='0.0.0.0', api_port=8080, alert_dir='alerts'):
    """启动告警系统"""
    # 初始化告警收集器
    alert_collector = AlertCollector(alert_dir)
    alert_collector.start()

    # 将收集器存入 App 配置
    app.config['alert_collector'] = alert_collector

    # 打印启动信息
    print("=" * 80)
    print("风机叶片检测告警系统（整合版）已启动")
    print(f"Web 仪表板访问地址: http://{host}:{api_port}")
    print(f"告警接收 API 地址: http://{host}:{api_port}/api/alerts")
    print(f"告警持久化目录: {alert_collector.alert_dir.absolute()}")
    print("=" * 80)

    try:
        app.run(host=host, port=api_port, debug=False, use_reloader=False)
    except KeyboardInterrupt:
        logger.info("接收到关闭信号，正在停止系统...")
    finally:
        cleanup()


def natural_sort(items):
    """自然排序函数"""
    import re

    def convert(text):
        return int(text) if text.isdigit() else text.lower()

    def alphanum_key(key):
        return [convert(c) for c in re.split(r'(\d+)', key)]

    return sorted(items, key=alphanum_key)


if __name__ == '__main__':
    start_combined_server(api_port=8080)