import io
from flask import Flask, render_template, jsonify, send_from_directory, request
from flask_cors import CORS
import json
import threading

from page.dashboard.AlertCollector import AlertCollector
from page.dashboard.LoggingDashboard import logger
from collections import deque
import time
from uuid import uuid4
import zipfile
from datetime import datetime
from pathlib import Path
import urllib.parse

from page.dashboard.Utile import CAMERA_CACHE_LOCK, CAMERA_CACHE_TTL, ALERTS_LOCK, ALERTS_CACHE
from page.dashboard.WordReportGenerator import WordReportGenerator
from page.dashboard import Utile

# 初始化
app = Flask(__name__)
CORS(app)



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
                        detection['name_chinese'] = Utile.translate_defect_name(detection['name'])

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


@app.route('/api/report/generate-word', methods=['POST'])
def generate_word_report_api():
    """生成Word报告（支持多选选项）"""
    try:
        # 获取请求数据
        data = request.json
        if not data:
            return jsonify({'status': 'error', 'message': '请求数据为空'}), 400

        # 获取搜索参数
        search_params = {
            'start_time': data.get('start_time'),
            'end_time': data.get('end_time'),
            'camera_id': data.get('camera_id'),
            'defect_name': data.get('defect_name'),
            'min_confidence': data.get('min_confidence')
        }

        # 获取选项
        download_data = data.get('download_data', False)
        download_images = data.get('download_images', False)

        # 验证必要参数
        if not search_params['start_time'] or not search_params['end_time']:
            return jsonify({'status': 'error', 'message': '必须提供开始时间和结束时间'}), 400

        # 获取告警收集器
        collector = app.config.get('alert_collector')
        if not collector:
            return jsonify({'status': 'error', 'message': '告警收集器未初始化'}), 503

        # 搜索告警数据（复用文件搜索API的逻辑）
        try:
            # 解析时间参数
            start_dt = datetime.fromisoformat(search_params['start_time'].replace('Z', '+00:00'))
            end_dt = datetime.fromisoformat(search_params['end_time'].replace('Z', '+00:00'))

            matched_alerts = []

            # 根据camera_id和日期范围确定搜索目录
            if search_params['camera_id']:
                camera_id = search_params['camera_id']
                search_dirs = []
                current_dt = start_dt.replace(day=1)
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
                search_dirs = [collector.alert_dir]

            # 搜索文件
            for search_dir in search_dirs:
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

                        # 风机筛选
                        if search_params['camera_id'] and alert.get('camera_id') != search_params['camera_id']:
                            continue

                        # 缺陷筛选
                        if search_params['defect_name']:
                            detections = alert.get('detections', [])
                            has_defect = any(det.get('name') == search_params['defect_name'] for det in detections)
                            if not has_defect:
                                continue

                        # 置信度筛选
                        if search_params['min_confidence']:
                            detections = alert.get('detections', [])
                            if detections:
                                max_conf = max(det.get('conf', 0) for det in detections)
                                if max_conf < float(search_params['min_confidence']):
                                    continue

                        # 汉化缺陷名称
                        for detection in alert.get('detections', []):
                            detection['name_chinese'] = Utile.translate_defect_name(detection['name'])

                        matched_alerts.append(alert)

                    except Exception as e:
                        logger.error(f"读取告警文件失败 {json_file}: {e}")

            # 按时间倒序排序
            matched_alerts.sort(key=lambda x: x.get('detection_time', ''), reverse=True)

            if not matched_alerts:
                return jsonify({'status': 'error', 'message': '未找到符合条件的告警数据'}), 404

            # 修复：Word报告中始终包含图片，include_images参数固定为True
            report_generator = WordReportGenerator(str(collector.alert_dir))
            word_buffer, excel_buffer, image_infos = report_generator.generate_word_report(
                matched_alerts,
                search_params,
                include_data=download_data,
                include_images=True  # 修复：Word报告中始终包含图片
            )

            try:
                # 获取当前时间戳用于文件名
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

                # 判断返回类型
                if download_data or download_images:
                    # 创建ZIP包
                    zip_buffer = io.BytesIO()
                    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zipf:
                        # 添加Word报告
                        word_filename = f"风机检测报告_{timestamp}.docx"
                        zipf.writestr(word_filename, word_buffer.getvalue())

                        # 添加Excel数据
                        if download_data and excel_buffer:
                            excel_filename = f"源数据_{timestamp}.xlsx"
                            zipf.writestr(excel_filename, excel_buffer.getvalue())

                        # 添加图片（直接使用原始文件，不复制）
                        if download_images and image_infos:
                            for img_info in image_infos:
                                source_path = img_info['source_path']
                                arcname = img_info['filename_in_zip']
                                if source_path.exists():
                                    zipf.write(source_path, arcname)

                    zip_buffer.seek(0)

                    # 创建中文文件名
                    chinese_filename = f"风机叶片检测报告_{timestamp}.zip"

                    # 同时提供两种编码方式以提高兼容性
                    encoded_filename = urllib.parse.quote(chinese_filename, encoding='utf-8')
                    ascii_filename = f"wt_blade_inspection_report_{timestamp}.zip"

                    # 设置响应头
                    response = app.response_class(
                        zip_buffer.getvalue(),
                        mimetype='application/zip',
                        headers={
                            'Content-Disposition': f"attachment; filename=\"{ascii_filename}\"; filename*=UTF-8''{encoded_filename}"
                        }
                    )
                    return response
                else:
                    # 只返回Word文档（始终包含图片）
                    chinese_filename = f"风机叶片检测报告_{timestamp}.docx"

                    # 同时提供两种编码方式以提高兼容性
                    encoded_filename = urllib.parse.quote(chinese_filename, encoding='utf-8')
                    ascii_filename = f"wt_blade_inspection_report_{timestamp}.docx"

                    response = app.response_class(
                        word_buffer.getvalue(),
                        mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                        headers={
                            'Content-Disposition': f"attachment; filename=\"{ascii_filename}\"; filename*=UTF-8''{encoded_filename}"
                        }
                    )
                    return response

            except Exception as e:
                logger.error(f"打包报告失败: {e}")
                return jsonify({'status': 'error', 'message': f'打包报告失败: {str(e)}'}), 500

        except Exception as e:
            logger.error(f"搜索告警数据失败: {e}")
            return jsonify({'status': 'error', 'message': f'搜索数据失败: {str(e)}'}), 500

    except Exception as e:
        logger.error(f"生成报告失败: {e}")
        return jsonify({'status': 'error', 'message': f'生成报告失败: {str(e)}'}), 500


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