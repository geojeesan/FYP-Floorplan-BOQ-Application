import os
import json
import cv2
import numpy as np
from PySide6.QtCore import QThread, Signal

import constants

# CubiCasa5k Imports
try:
    import torch
    from floortrans.models.hg_furukawa_original import hg_furukawa_original
    from floortrans.post_prosessing import split_prediction, get_polygons
except ImportError as e:
    print(f"Error importing CubiCasa modules: {e}")
    torch = None

# EasyOCR Setup
import easyocr
import re
EASYOCR_READER = None
_HAS_EASYOCR = False

def init_easyocr():
    global EASYOCR_READER, _HAS_EASYOCR
    if _HAS_EASYOCR and EASYOCR_READER is not None:
        return

    try:
        use_gpu = False
        if torch and torch.cuda.is_available():
            print(f"CUDA Detected: {torch.cuda.get_device_name(0)}")
            use_gpu = True
        else:
            print("CUDA NOT detected. Using CPU.")
            
        EASYOCR_READER = easyocr.Reader(['en'], gpu=use_gpu)
        _HAS_EASYOCR = True
    except Exception as e:
        print(f"Failed to load EasyOCR: {e}")
        _HAS_EASYOCR = False


class CubiCasaWorker(QThread):
    """
    Standard CubiCasa analysis.
    Optimized for Data-Only Extraction (No heavy raster image generation).
    """
    finished = Signal(str, str, str)  # room_path, item_path, json_path
    error = Signal(str)

    def __init__(self, image_path, scale_ratio=1.0, model_path="model_best_val_loss_var.pkl"):
        super().__init__()
        self.image_path = image_path
        self.scale_ratio = scale_ratio
        self.model_path = model_path

    def run(self):
        if not torch:
            self.error.emit("PyTorch or CubiCasa modules not found.")
            return

        if not os.path.exists(self.model_path):
            self.error.emit(f"Model file not found: {self.model_path}")
            return

        try:
            fplan = cv2.imread(self.image_path)
            if fplan is None:
                self.error.emit("Could not read image file.")
                return
                
            fplan = cv2.cvtColor(fplan, cv2.COLOR_BGR2RGB)
            height, width = fplan.shape[:2]
            
            # Normalize
            img_norm = 2 * (fplan / 255.0) - 1
            img_norm = np.moveaxis(img_norm, -1, 0)
            input_tensor = torch.tensor(img_norm).float().unsqueeze(0)

            # Load Model
            model = hg_furukawa_original(44)
            checkpoint = torch.load(self.model_path, map_location='cpu')
            state_dict = checkpoint['model_state'] if 'model_state' in checkpoint else checkpoint
            model.load_state_dict(state_dict)
            
            device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            model.to(device)
            input_tensor = input_tensor.to(device)
            model.eval()

            with torch.no_grad():
                pred = model(input_tensor)

            boq_data = {"rooms": [], "icons": []}

            # Polygon Extraction
            try:
                split = [21, 12, 11]
                heatmaps, rooms, icons = split_prediction(pred, [height, width], split)
                polygons, types, room_polygons, room_types = get_polygons((heatmaps, rooms, icons), 0.4, [1, 2])
                
                # Process Rooms
                for i, poly in enumerate(room_polygons):
                    class_idx = room_types[i]['class']
                    label_name = constants.ROOM_CLASSES[class_idx] if 0 <= class_idx < len(constants.ROOM_CLASSES) else "Unknown"
                    try:
                        polys_to_process = poly.geoms if hasattr(poly, 'geoms') else [poly]
                        for subnet_poly in polys_to_process:
                            points = np.array(subnet_poly.exterior.coords if hasattr(subnet_poly, 'exterior') else subnet_poly)
                            area_px = subnet_poly.area if hasattr(subnet_poly, 'area') else 0.0
                            boq_data["rooms"].append({
                                "class_id": int(class_idx), "label": label_name, 
                                "area_pixels": float(area_px), "points": points.tolist() 
                            })
                    except Exception as e:
                        pass

                # Process Icons, Doors, Windows, and Walls
                for i, poly in enumerate(polygons):
                    type_info = types[i]
                    class_idx = type_info['class']
                    p_type = type_info.get('type', '')
                    
                    if p_type == 'wall':
                        label_name = constants.ROOM_CLASSES[class_idx] if 0 <= class_idx < len(constants.ROOM_CLASSES) else "Unknown"
                        boq_data["rooms"].append({"class_id": int(class_idx), "label": label_name, "points": poly.tolist()})
                    elif p_type != 'room': 
                        label_name = constants.ICON_CLASSES[class_idx] if 0 <= class_idx < len(constants.ICON_CLASSES) else "Unknown"
                        boq_data["icons"].append({"class_id": int(class_idx), "label": label_name, "points": poly.tolist()})
                    
            except Exception as e:
                print(f"Polygon extraction error: {e}")

            # Save Data
            base_name = os.path.splitext(os.path.basename(self.image_path))[0]
            room_path = f"temp_{base_name}_rooms.png"
            item_path = f"temp_{base_name}_items.png"
            json_path = f"temp_{base_name}_data.json"
            
            # Since the UI now uses vectors, we generate tiny 1x1 invisible pixels 
            # just to satisfy the main_window's file-loading pipeline.
            dummy_img = np.zeros((1, 1, 4), dtype=np.uint8)
            cv2.imwrite(room_path, dummy_img)
            cv2.imwrite(item_path, dummy_img)
            
            with open(json_path, 'w') as f:
                json.dump(boq_data, f, indent=4)
            
            self.finished.emit(room_path, item_path, json_path)

        except Exception as e:
            self.error.emit(str(e))


class OCRWorker(QThread):
    """
    Dedicated worker for Multi-directional OCR.
    Optimized for pure data extraction (No OpenCV text blending).
    """
    finished = Signal(str, list) # (layer_path, data_list)
    error = Signal(str)

    def __init__(self, image_path):
        super().__init__()
        self.image_path = image_path

    def calculate_iou(self, boxA, boxB):
        xA = max(boxA[0], boxB[0])
        yA = max(boxA[1], boxB[1])
        xB = min(boxA[2], boxB[2])
        yB = min(boxA[3], boxB[3])

        interArea = max(0, xB - xA + 1) * max(0, yB - yA + 1)
        boxAArea = (boxA[2] - boxA[0] + 1) * (boxA[3] - boxA[1] + 1)
        boxBArea = (boxB[2] - boxB[0] + 1) * (boxB[3] - boxB[1] + 1)

        iou = interArea / float(boxAArea + boxBArea - interArea)
        return iou

    def run(self):
        init_easyocr()
        if not _HAS_EASYOCR:
            self.error.emit("EasyOCR not available.")
            return

        try:
            print("--- Starting On-Demand OCR ---")
            img = cv2.imread(self.image_path)
            img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            height, width = img.shape[:2]
            
            candidates = []

            # 1. Multi-directional Scan
            rotations = [
                ("0", None, lambda x,y,w,h: (x, y)),
                ("90", cv2.ROTATE_90_CLOCKWISE, lambda x,y,w,h: (y, h-x)),
                ("180", cv2.ROTATE_180, lambda x,y,w,h: (w-x, h-y)),
                ("270", cv2.ROTATE_90_COUNTERCLOCKWISE, lambda x,y,w,h: (w-y, x))
            ]

            for angle_name, rot_code, trans_func in rotations:
                scan_img = cv2.rotate(img, rot_code) if rot_code is not None else img
                results = EASYOCR_READER.readtext(scan_img)
                
                for (bbox, text, prob) in results:
                    if prob < 0.50: continue 

                    # Transform back to global coords
                    clean_bbox = []
                    for p in bbox:
                        ox, oy = trans_func(p[0], p[1], width, height)
                        clean_bbox.append([int(ox), int(oy)])
                    
                    pts = np.array(clean_bbox)
                    x_min, y_min = np.min(pts, axis=0)
                    x_max, y_max = np.max(pts, axis=0)

                    candidates.append({
                        "text": text,
                        "conf": prob,
                        "poly": clean_bbox,
                        "rect": [x_min, y_min, x_max, y_max],
                        "angle": angle_name
                    })

            # 2. Non-Maximum Suppression (Deduplication)
            candidates.sort(key=lambda x: x["conf"], reverse=True)
            final_results = []
            
            while candidates:
                best = candidates.pop(0)
                
                # Rules for Text Post-Processing
                text_str = best["text"].strip()
                if re.match(r'^\d+(\.\d+)?$', text_str):
                    continue # Ignore if it's just a number
                
                if text_str == "JM":
                    text_str = "WC" # Common floorplan OCR mistake fix
                
                best["text"] = text_str
                final_results.append(best)
                
                # Compare best against all remaining to find duplicates
                remaining = []
                for other in candidates:
                    iou = self.calculate_iou(best["rect"], other["rect"])
                    if iou < 0.20:
                        remaining.append(other)
                candidates = remaining

            # 3. Create Dummy Layer (UI handles drawing natively now)
            ocr_layer = np.zeros((1, 1, 4), dtype=np.uint8)

            # 4. Save
            base_name = os.path.splitext(os.path.basename(self.image_path))[0]
            layer_path = f"temp_{base_name}_ocr_layer.png"
            cv2.imwrite(layer_path, ocr_layer)
            
            self.finished.emit(layer_path, final_results)

        except Exception as e:
            import traceback
            traceback.print_exc()
            self.error.emit(str(e))