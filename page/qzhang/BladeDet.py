import time
import cv2
import numpy as np
import onnxruntime
import math
from page.qzhang.utils import xywh2xyxy, multiclass_nms,detections_dog,class_names

class YOLOv8OBB:
    def __init__(self, path, conf_thres=0.7, iou_thres=0.5,device_id=0):
        self.conf_threshold = conf_thres
        self.iou_threshold = iou_thres

        # Initialize model
        self.initialize_model(path,device_id)

    def __call__(self, image):
        return self.detect_objects(image)

    def initialize_model(self, path,device_id=0):
        # 指定GPU设备索引，例如使用第0块GPU
        print(onnxruntime.get_available_providers())

        session_options = onnxruntime.SessionOptions()
        # 设置线程数为 1
        session_options.intra_op_num_threads = 1
        gpu_device_id = device_id
        provider_options = [{'device_id': gpu_device_id}]
        if device_id == 'cpu':
            providers = ['CPUExecutionProvider']
            self.session = onnxruntime.InferenceSession(path,providers=providers)
        else:
            providers = ['CUDAExecutionProvider']
            self.session = onnxruntime.InferenceSession(path,session_options,providers=providers, provider_options=provider_options)
        # self.session = onnxruntime.InferenceSession(path,providers=["CUDAExecutionProvider",'CPUExecutionProvider'], provider_options=provider_options)
        # Get model info
        self.get_input_details()
        self.get_output_details()


    def detect_objects(self, image):
        input_tensor = self.prepare_input(image)

        # Perform inference on the image
        outputs = self.inference(input_tensor)

        self.boxes, self.scores, self.class_ids = self.process_output(outputs)
        return self.boxes, self.scores, self.class_ids
    
    def detect(self, image):
        input_tensor = self.prepare_input(image)

        # Perform inference on the image
        outputs = self.inference(input_tensor)
        results = self.filter_box(outputs)
        # print(results.shape)
        if results.size == 0:
            return []
        results = self.scale_boxes(results, image.shape)
        boxes = results[...,:4]
        scores = results[...,4]
        classes = results[...,5].astype(np.int32)
        angles = results[...,6]
        result = []
        for box, score, cls, angle in zip(boxes, scores, classes, angles):
            rotate_box = ((box[0], box[1]), (box[2], box[3]), angle)
            points = cv2.boxPoints(rotate_box)
            points = points.astype(np.int_)
            dit = {"bbox":rotate_box,"score":score,"class":cls,"name":class_names[cls]}
            result.append(dit)
        
        # for bbox,score,cls in zip(self.boxes, self.scores, self.class_ids):
        #     dit = {"bbox":bbox,"score":score,"class":cls}
        #     result.append(dit)
        # print(result)
        return result
    def letterbox(self,im, new_shape=(416, 416), color=(114, 114, 114)):
        # Resize and pad image while meeting stride-multiple constraints
        shape = im.shape[:2]  # current shape [height, width]

        # Scale ratio (new / old)
        r = min(new_shape[0] / shape[0], new_shape[1] / shape[1])
        
        # Compute padding
        new_unpad = int(round(shape[1] * r)), int(round(shape[0] * r))    
        dw, dh = (new_shape[1] - new_unpad[0])/2, (new_shape[0] - new_unpad[1])/2  # wh padding 
        top, bottom = int(round(dh - 0.1)), int(round(dh + 0.1))
        left, right = int(round(dw - 0.1)), int(round(dw + 0.1))
        
        if shape[::-1] != new_unpad:  # resize
            im = cv2.resize(im, new_unpad, interpolation=cv2.INTER_LINEAR)
        im = cv2.copyMakeBorder(im, top, bottom, left, right, cv2.BORDER_CONSTANT, value=color)  # add border
        return im

    def prepare_input(self, image):
        input_shape =[self.input_height, self.input_width]
        input = self.letterbox(image, input_shape)
        # input = input[:, :, ::-1].transpose(2, 0, 1).astype(dtype=np.float32)  #BGR2RGB和HWC2CHW
        input = input.transpose(2, 0, 1).astype(dtype=np.float32)  #HWC2CHW
        input = input / 255.0
        input_tensor = []
        input_tensor.append(input)
        # self.img_height, self.img_width = image.shape[:2]

        # input_img = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

        # # Resize input image
        # input_img = cv2.resize(input_img, (self.input_width, self.input_height))

        # # Scale input pixel values to 0 to 1
        # input_img = input_img / 255.0
        # input_img = input_img.transpose(2, 0, 1)
        # input_tensor = input_img[np.newaxis, :, :, :].astype(np.float32)

        return input_tensor


    def inference(self, input_tensor):
        start = time.perf_counter()

        inputs = {}
        for name in self.input_names:
            inputs[name] =  np.array(input_tensor)
    
        outputs = self.session.run(None, inputs)[0]
        # outputs = self.session.run(self.output_names, {self.input_names[0]: input_tensor})

        # print(f"Inference time: {(time.perf_counter() - start)*1000:.2f} ms")
        return outputs
    def filter_box(self,outputs): #过滤掉无用的框    
        outputs = np.squeeze(outputs)
        
        rotated_boxes = []
        scores = []
        class_ids = []
        classes_scores = outputs[4:(4+len(class_names)), ...]  
        angles = outputs[-1, ...]   
        
        for i in range(outputs.shape[1]):              
            class_id = np.argmax(classes_scores[...,i])
            score = classes_scores[class_id][i]
            angle = angles[i]
            if 0.5 * math.pi <= angle <= 0.75 * math.pi:
                angle -= math.pi
            if score > self.conf_threshold:
                rotated_boxes.append(np.concatenate([outputs[:4, i], np.array([score, class_id, angle * 180 / math.pi])]))
                scores.append(score)
                class_ids.append(class_id) 
        if len(scores)== 0:
            return np.array([])
        
        rotated_boxes = np.array(rotated_boxes)
        boxes = xywh2xyxy(rotated_boxes)
        scores = np.array(scores)
        indices = self.nms(boxes, scores, self.conf_threshold, self.iou_threshold) 
        output = rotated_boxes[indices]
        return output
    def process_output(self, output):
        predictions = np.squeeze(output[0]).T

        # Filter out object confidence scores below threshold
        scores = np.max(predictions[:, 4:], axis=1)
        predictions = predictions[scores > self.conf_threshold, :]
        scores = scores[scores > self.conf_threshold]

        if len(scores) == 0:
            return [], [], []

        # Get the class with the highest confidence
        class_ids = np.argmax(predictions[:, 4:], axis=1)

        # Get bounding boxes for each object
        boxes = self.extract_boxes(predictions)

        # Apply non-maxima suppression to suppress weak, overlapping bounding boxes
        # indices = nms(boxes, scores, self.iou_threshold)
        indices = multiclass_nms(boxes, scores, class_ids, self.iou_threshold)

        return boxes[indices], scores[indices], class_ids[indices]

    def extract_boxes(self, predictions):
        # Extract boxes from predictions
        boxes = predictions[:, :4]

        # Scale boxes to original image dimensions
        boxes = self.rescale_boxes(boxes)

        # Convert boxes to xyxy format
        boxes = xywh2xyxy(boxes)
        return boxes
    def nms(self,boxes, scores, score_threshold, nms_threshold):
        x1 = boxes[:, 0]
        y1 = boxes[:, 1]
        x2 = boxes[:, 2]
        y2 = boxes[:, 3]
        areas = (y2 - y1 + 1) * (x2 - x1 + 1)
        keep = []
        index = scores.argsort()[::-1] 

        while index.size > 0:
            i = index[0]
            keep.append(i)
            x11 = np.maximum(x1[i], x1[index[1:]]) 
            y11 = np.maximum(y1[i], y1[index[1:]])
            x22 = np.minimum(x2[i], x2[index[1:]])
            y22 = np.minimum(y2[i], y2[index[1:]])
            w = np.maximum(0, x22 - x11 + 1)                              
            h = np.maximum(0, y22 - y11 + 1) 
            overlaps = w * h
            ious = overlaps / (areas[i] + areas[index[1:]] - overlaps)
            idx = np.where(ious <= nms_threshold)[0]
            index = index[idx + 1]
        return keep
    def rescale_boxes(self, boxes):

        # Rescale boxes to original image dimensions
        input_shape = np.array([self.input_width, self.input_height, self.input_width, self.input_height])
        boxes = np.divide(boxes, input_shape, dtype=np.float32)
        boxes *= np.array([self.img_width, self.img_height, self.img_width, self.img_height])
        return boxes
    
    def scale_boxes(self,boxes, shape):
        # Rescale boxes (xyxy) from input_shape to shape
        input_shape =[self.input_height, self.input_width]
        gain = min(input_shape[0] / shape[0], input_shape[1] / shape[1])  # gain  = old / new
        pad = (input_shape[1] - shape[1] * gain) / 2, (input_shape[0] - shape[0] * gain) / 2  # wh padding
        boxes[..., [0, 1]] -= pad  # xy padding
        boxes[..., :4] /= gain
        return boxes

    def draw(self,image, box_data):
        box_data = self.scale_boxes(box_data, image.shape)
        boxes = box_data[...,:4]
        scores = box_data[...,4]
        classes = box_data[...,5].astype(np.int32)
        angles = box_data[...,6]
        for box, score, cl, angle in zip(boxes, scores, classes, angles):
            rotate_box = ((box[0], box[1]), (box[2], box[3]), angle)
            points = cv2.boxPoints(rotate_box)
            points = points.astype(np.int_)
            cv2.polylines(image, [points], isClosed=True, color=(255, 0, 0), thickness=1)
            cv2.putText(image, '{0} {1:.2f}'.format(class_names[cl], score), (points[0][0], points[0][1]), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)

    def get_input_details(self):
        model_inputs = self.session.get_inputs()
        self.input_names = [model_inputs[i].name for i in range(len(model_inputs))]
        self.input_shape = model_inputs[0].shape
        self.input_height = self.input_shape[2]
        self.input_width = self.input_shape[3]
    def get_output_details(self):
        model_outputs = self.session.get_outputs()
        self.output_names = [model_outputs[i].name for i in range(len(model_outputs))]
        print(self.output_names)

class YOLODet:

    def __init__(self, path, conf_thres=0.7, iou_thres=0.5,device_id=0):
        self.conf_threshold = conf_thres
        self.iou_threshold = iou_thres

        # Initialize model
        self.initialize_model(path,device_id)

    def __call__(self, image):
        return self.detect_objects(image)

    def initialize_model(self, path,device_id=0):
        # 指定GPU设备索引，例如使用第0块GPU
        print(onnxruntime.get_available_providers())
        gpu_device_id = device_id
        provider_options = [{'device_id': gpu_device_id}]
        if device_id == 'cpu':
            providers = ['CPUExecutionProvider']
            self.session = onnxruntime.InferenceSession(path,providers=providers)
        else:
            providers = ['CUDAExecutionProvider']
            self.session = onnxruntime.InferenceSession(path,providers=providers)
        # self.session = onnxruntime.InferenceSession(path,providers=["CUDAExecutionProvider",'CPUExecutionProvider'], provider_options=provider_options)
        # Get model info
        self.get_input_details()
        self.get_output_details()


    def detect_objects(self, image):
        input_tensor = self.prepare_input(image)

        # Perform inference on the image
        outputs = self.inference(input_tensor)

        self.boxes, self.scores, self.class_ids = self.process_output(outputs)
        return self.boxes, self.scores, self.class_ids
    
    def detect(self, image):
        input_tensor = self.prepare_input(image)

        # Perform inference on the image
        outputs = self.inference(input_tensor)
        self.boxes, self.scores, self.class_ids = self.process_output(outputs)
        # print(self.boxes, self.scores, self.class_ids)
        result = []
        for bbox,score,cls in zip(self.boxes, self.scores, self.class_ids):
            dit = {"bbox":bbox,"score":score,"class":cls}
            result.append(dit)
        # print(result)
        return result

    def prepare_input(self, image):
        self.img_height, self.img_width = image.shape[:2]

        input_img = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

        # Resize input image
        input_img = cv2.resize(input_img, (self.input_width, self.input_height))

        # Scale input pixel values to 0 to 1
        input_img = input_img / 255.0
        input_img = input_img.transpose(2, 0, 1)
        input_tensor = input_img[np.newaxis, :, :, :].astype(np.float32)

        return input_tensor


    def inference(self, input_tensor):
        start = time.perf_counter()
        outputs = self.session.run(self.output_names, {self.input_names[0]: input_tensor})

        # print(f"Inference time: {(time.perf_counter() - start)*1000:.2f} ms")
        return outputs

    def process_output(self, output):
        predictions = np.squeeze(output[0]).T

        # Filter out object confidence scores below threshold
        scores = np.max(predictions[:, 4:], axis=1)
        predictions = predictions[scores > self.conf_threshold, :]
        scores = scores[scores > self.conf_threshold]

        if len(scores) == 0:
            return [], [], []

        # Get the class with the highest confidence
        class_ids = np.argmax(predictions[:, 4:], axis=1)

        # Get bounding boxes for each object
        boxes = self.extract_boxes(predictions)

        # Apply non-maxima suppression to suppress weak, overlapping bounding boxes
        # indices = nms(boxes, scores, self.iou_threshold)
        indices = multiclass_nms(boxes, scores, class_ids, self.iou_threshold)

        return boxes[indices], scores[indices], class_ids[indices]

    def extract_boxes(self, predictions):
        # Extract boxes from predictions
        boxes = predictions[:, :4]

        # Scale boxes to original image dimensions
        boxes = self.rescale_boxes(boxes)

        # Convert boxes to xyxy format
        boxes = xywh2xyxy(boxes)
        return boxes

    def rescale_boxes(self, boxes):

        # Rescale boxes to original image dimensions
        input_shape = np.array([self.input_width, self.input_height, self.input_width, self.input_height])
        boxes = np.divide(boxes, input_shape, dtype=np.float32)
        boxes *= np.array([self.img_width, self.img_height, self.img_width, self.img_height])
        return boxes

    def draw_detections(self, image, draw_scores=True, mask_alpha=0.4):

        return detections_dog(image, self.boxes, self.scores,
                               self.class_ids, mask_alpha)

    def get_input_details(self):
        model_inputs = self.session.get_inputs()
        self.input_names = [model_inputs[i].name for i in range(len(model_inputs))]
        self.input_shape = model_inputs[0].shape
        self.input_height = self.input_shape[2]
        self.input_width = self.input_shape[3]
    def get_output_details(self):
        model_outputs = self.session.get_outputs()
        self.output_names = [model_outputs[i].name for i in range(len(model_outputs))]
        print(self.output_names)
