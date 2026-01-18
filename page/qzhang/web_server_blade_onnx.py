# Copyright (c) 2020 PaddlePaddle Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import argparse
import sys
import cv2
import numpy as np
from PIL import Image
import io
from page.qzhang.BladeDet import YOLOv8OBB
from page.qzhang.BladeSeg import DeeplabV3Seg

import flask
from flask_cors import CORS
from pathlib import Path
import os
import json
import gc
from urllib.parse import quote
import urllib.request

app = flask.Flask(__name__)
FILE = Path(__file__).resolve()
ROOT = FILE.parents[0]  # YOLOv5 root directory
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))  # add ROOT to PATH
seg_model = None
yolov8_model = None
yolo_opt = None
CORS(app, resources=r'/*')
id = 0


@app.route("/yolo-predict", methods=["GET", "POST"])
def predict_post():
    global yolov8_model, yolo_opt, seg_model, id

    # if flask.request.method != "POST":
    #     return
    try:
        # if flask.request.method != "POST":
        #     # print('request image Failed!')
        #     return
        if flask.request.method == "POST" and flask.request.files.get("image"):
            # 记录分割预测前的内存使用情况
            imagefile = flask.request.files["image"]
            # print(type(image))
            imagebts = imagefile.read()
            image = Image.open(io.BytesIO(imagebts))
            # image = cv2.cvtColor((np.asarray(image)), cv2.COLOR_RGB2BGR)
            image = np.asarray(image)
        if flask.request.method == "GET" and flask.request.args.get("path"):
            path = flask.request.args.get("path")
            print(path)
            path = quote(path, '/:?_.')
            res = urllib.request.urlopen(path)
            image = np.asarray(bytearray(res.read()), dtype="uint8")
            image = cv2.imdecode(image, cv2.IMREAD_COLOR)
            image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
            image = np.asarray(image)
        orig_height, orig_width = image.shape[:2]
        rimg = image.copy()
        try:
            # 叶片分割提取
            seg_img = seg_model.predict(image)
            segname = os.path.join('../../result', str(id) + '_seg.jpg')
            # rimg = cv2.cvtColor(rimg, cv2.COLOR_RGB2BGR)
            cv2.imwrite(segname, seg_img)
            # 叶片缺陷检测
            results = yolov8_model.detect(seg_img)
            rets = []
            if len(results) > 0:
                for i, res in enumerate(results):
                    ((x_center, y_center), (width, height), r) = res['bbox']

                    # 缺陷位置缩放到原图位置
                    scale_x = orig_width / 1024.0
                    scale_y = orig_height / 1024.0

                    x_center = float(x_center) * scale_x
                    y_center = float(y_center) * scale_y
                    width = float(width) * scale_x
                    height = float(height) * scale_y
                    # 绘制矩形框
                    re = {
                        "clsId": int(res['class']),
                        "name": res['name'],
                        "conf": float(res['score']),
                        "x": float(x_center),
                        "y": float(y_center),
                        "w": float(width),
                        "h": float(height),
                        "r": float(r)}
                    rets.append(re)
                    bbox = ((x_center, y_center), (width, height), r)
                    points = cv2.boxPoints(bbox)
                    points = points.astype(np.int_)
                    cv2.polylines(rimg, [points], isClosed=True, color=(255, 0, 0), thickness=1)
                    cv2.putText(rimg, '{0} {1:.2f}'.format(res['name'], res['score']), (points[0][0], points[0][1]),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)

                filename = os.path.join('../../result', str(id) + '.jpg')
                rimg = cv2.cvtColor(rimg, cv2.COLOR_RGB2BGR)
                cv2.imwrite(filename, rimg)
                id += 1
            del image
            del seg_img
            del results
            gc.collect()

            return json.dumps(rets)
        except Exception as e1:
            print("error")
            print(e1)
            return json.dumps([])


    except Exception as e:
        print(e)
        return json.dumps([])

        # return json.dumps(results)


def parse_args():
    parser = argparse.ArgumentParser(description='Model prediction')

    # params of prediction

    parser.add_argument('--seg_weights', type=str, default='./models/blade/blade_seg.onnx',
                        help='The path of model for blade seg')

    parser.add_argument('--det_weights', type=str, default='./models/blade/best.onnx',
                        help='The path of model for blade det')
    parser.add_argument('--imgsz', '--img', '--img-size', nargs='+', type=int, default=1280,
                        help='inference size (height,width)')
    parser.add_argument('--conf', type=float, default=0.45, help='predict confidence')
    parser.add_argument('--device', default='0', help='cuda device, i.e. 0 or 0,1 or cpu')
    # set port
    parser.add_argument('--port', default='8190', help='port')

    return parser.parse_args()


def main(args):
    global seg_model

    global yolov8_model
    global yolo_opt
    yolo_opt = args
    yolov8_model = YOLOv8OBB(path=str(yolo_opt.det_weights), conf_thres=yolo_opt.conf, device_id=yolo_opt.device)  #
    seg_model = DeeplabV3Seg(path=str(yolo_opt.seg_weights), device_id=yolo_opt.device)
    # image = torch.rand((1, 3, 640, 640))
    # yolov8_model.predict(image,  device=yolo_opt.device, save=False, stream=True, conf=0.5)
    print("load model OK!")


if __name__ == '__main__':
    args = parse_args()
    main(args)
    # print(args.port)
    app.run('0.0.0.0', args.port)
