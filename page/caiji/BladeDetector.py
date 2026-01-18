import gc

import cv2
import numpy as np
from page.caiji.loggermodel import logger

class BladeDetector:
    """叶片检测器"""

    def __init__(self, seg_weights, det_weights, conf_threshold=0.45, device='0'):
        """
        初始化检测器
        Args:
            seg_weights: 分割模型路径
            det_weights: 检测模型路径
            conf_threshold: 置信度阈值
            device: 设备ID
        """
        # 导入检测模块
        try:
            from page.qzhang.BladeDet import YOLOv8OBB
            from page.qzhang.BladeSeg import DeeplabV3Seg

            self.seg_model = DeeplabV3Seg(
                path=str(seg_weights),
                device_id=device
            )

            self.det_model = YOLOv8OBB(
                path=str(det_weights),
                conf_thres=conf_threshold,
                device_id=device
            )

            logger.info("检测模型加载成功")

        except ImportError as e:
            logger.error(f"导入检测模块失败: {e}")
            raise
        except Exception as e:
            logger.error(f"加载检测模型失败: {e}")
            raise

    def detect(self, image):
        """
        执行叶片检测
        Args:
            image: 输入图像
        Returns:
            detection_results: 检测结果列表
            seg_image: 分割后的图像
            annotated_image: 标注后的图像
        """
        try:
            # 记录原始尺寸
            orig_height, orig_width = image.shape[:2]
            rimg = image.copy()

            # 叶片分割提取
            seg_img = self.seg_model.predict(image)

            # 叶片缺陷检测
            results = self.det_model.detect(seg_img)

            detections = []

            if len(results) > 0:
                for res in results:
                    ((x_center, y_center), (width, height), r) = res['bbox']

                    # 缺陷位置缩放到原图位置
                    scale_x = orig_width / 1024.0
                    scale_y = orig_height / 1024.0

                    x_center = float(x_center) * scale_x
                    y_center = float(y_center) * scale_y
                    width = float(width) * scale_x
                    height = float(height) * scale_y

                    # 构建检测结果
                    detection = {
                        "clsId": int(res['class']),
                        "name": res['name'],
                        "conf": float(res['score']),
                        "x": float(x_center),
                        "y": float(y_center),
                        "w": float(width),
                        "h": float(height),
                        "r": float(r)
                    }
                    detections.append(detection)

                    # 在原图上绘制
                    bbox = ((x_center, y_center), (width, height), r)
                    points = cv2.boxPoints(bbox)
                    points = points.astype(np.int_)

                    # 绘制旋转矩形框
                    cv2.polylines(rimg, [points], isClosed=True, color=(255, 0, 0), thickness=2)

                    # 添加标签
                    cv2.putText(rimg, '{0} {1:.2f}'.format(res['name'], res['score']), (points[0][0], points[0][1]),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)

            return detections, seg_img, rimg
        except Exception as e:
            logger.error(f"检测过程中出错: {e}")
            return [], None, image
        finally:
            del image
            del seg_img
            del results
            gc.collect()