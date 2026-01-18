import cv2
import numpy as np
import onnxruntime as ort
# import torch.nn.functional as F
from page.qzhang.utils  import get_pseudo_color_map,get_color_map_list
# import torch
# from PIL import Image
CLASSES = ('background', "blade")

model_input_w = 1024
model_input_h = 1024

color_list = [[0, 0, 0], [128, 0, 0],[ 0, 128, 0]]

class DeeplabV3Seg:

    def __init__(self, path,device_id=0):
        # self.conf_threshold = conf_thres
        # self.iou_threshold = iou_thres

        # Initialize model
        self.initialize_model(path,device_id)

    # def __call__(self, image):
    #     return self.detect_objects(image)

    def initialize_model(self, path,device_id=0):
        print(ort.get_available_providers())
        session_options = ort.SessionOptions()
        # 设置线程数为 1
        session_options.intra_op_num_threads = 1
        gpu_device_id = device_id
        provider_options = [{'device_id': gpu_device_id}]
        if device_id == 'cpu':
            providers = ['CPUExecutionProvider']
            self.session = ort.InferenceSession(path,providers=providers)
        else:
            providers = ['CUDAExecutionProvider']
            self.session = ort.InferenceSession(path,session_options,providers=providers, provider_options=provider_options)
        # Get model info
        # self.get_input_details()
        # self.get_output_details()


    # def detect_objects(self, image):
    #     input_tensor = self.prepare_input(image)

    #     # Perform inference on the image
    #     outputs = self.inference(input_tensor)

    #     self.boxes, self.scores, self.class_ids = self.process_output(outputs)

    #     return self.boxes, self.scores, self.class_ids
    
    def prepare_input(self,img):

        # img = cv2.cvtColor(src_img, cv2.COLOR_BGR2RGB)
        self.rimg = cv2.resize(img, (model_input_w, model_input_h))

        img = self.rimg.astype(np.float32)
        img = img * 0.003921568
        img = img.transpose(2, 0, 1)
        img = np.ascontiguousarray(img, dtype=np.float32)
        img_data = np.expand_dims(img, axis=0)
        return img_data
    def softmax(self,x):
        e_x = np.exp(x - np.max(x))      # 避免指数爆炸
        return e_x / e_x.sum()
    def cnt_area(self,cnt):
        rect = cv2.minAreaRect(cnt)
        box = cv2.boxPoints(rect)
        box = np.int0(box)
        area = cv2.contourArea(cnt)
        return area

    def predict(self,img):
        # img = cv2.imread(img_path)
        img_h, img_w = img.shape[:2]
        img_data = self.prepare_input(img)
        # img_data = np.expand_dims(img_data, axis=0)
        outputs = self.session.run(None, {'x': img_data})
        pred = np.squeeze(outputs)
        pred = pred.astype('uint8')
        # 应用掩码提取多边形目标
        result = cv2.bitwise_and(self.rimg, self.rimg, mask=pred*255)
        # result = cv2.cvtColor(result, cv2.COLOR_RGB2BGR)
        return result
    def seg_image(self,img):
        # img = cv2.imread(img_path)
        img_h, img_w = img.shape[:2]
        img_data = self.prepare_input(img)
        # img_data = np.expand_dims(img_data, axis=0)
        result_list = []
        outputs = self.session.run(None, {'x': img_data})
        pred = np.squeeze(outputs)
        pred = pred.astype('uint8')
        
        # save added image
        color_map = get_color_map_list(256)
        # save pseudo color prediction
        pred_mask = get_pseudo_color_map(pred, color_map)
        # 应用掩码提取多边形目标
        
        img = cv2.cvtColor(np.asarray(pred_mask), cv2.COLOR_RGB2BGR)
        
        b,g,r = cv2.split(img)
        
        #_, thres = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY)
        thres = g*255
        contours,_ = cv2.findContours(thres, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
        ll = len(contours)
        if(ll == 0):
            return [None, None]

        contours = list(contours)
        contours.sort(key = self.cnt_area, reverse=False)
        c_contour = contours[-1]
        if len(c_contour) < 3:
            return [None, None]
        approx = cv2.approxPolyDP(c_contour,0.002*cv2.arcLength(c_contour,True),True)
        result_list.append(approx.tolist())
        return result_list,approx


if __name__ == "__main__":
    print('This is main ...')
    img_path = '/data2/qzhang/dataset/blade/testimg/241971521744917-20250312145137662.jpg'
    onnx_path = '../../models/blade/blade_seg.onnx'
    segmodel = DeeplabV3Seg(onnx_path,device_id=1)
    results,counter = segmodel.seg_image(img_path)
    img2 = cv2.imread(img_path)
    if len(results) > 0:
        # 根据分割结果，利用原始图像和mask进行运算抠图
        mask = np.zeros((1024, 1024, 1), np.uint8)
        mask = cv2.drawContours(mask, [counter], 0, 255, cv2.FILLED)
        # img = cv2.imread(img_path)
        img = cv2.resize(img2, (1024, 1024))
        img_fg = cv2.bitwise_and(img, img, mask=mask)
        cv2.imwrite("/root/qzhang/seg/paddleseg/result/seg_result.jpg",img_fg)