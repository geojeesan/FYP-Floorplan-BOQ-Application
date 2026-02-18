import os
import json
import cv2
import numpy as np
from PySide6.QtCore import QThread, Signal

import constants

# --- CubiCasa5k Imports ---
try:
    import torch
    import torch.nn as nn
    from floortrans.models.hg_furukawa_original import hg_furukawa_original
    from floortrans.post_prosessing import split_prediction, get_polygons
    from floortrans.plotting import polygons_to_image
except ImportError as e:
    print(f"Error importing CubiCasa modules: {e}")
    torch = None

# --- EasyOCR Setup ---
import easyocr
EASYOCR_READER = None
_HAS_EASYOCR = False

def init_easyocr():
    global EASYOCR_READER, _HAS_EASYOCR
    if _HAS_EASYOCR and EASYOCR_READER is not None:
        return

    try:
        print("--- Initializing EasyOCR ---")
        use_gpu = False
        if torch and torch.cuda.is_available():
            print(f"CUDA Detected: {torch.cuda.get_device_name(0)}")
            use_gpu = True
        else:
            print("CUDA NOT detected. Using CPU.")
            
        EASYOCR_READER = easyocr.Reader(['en'], gpu=use_gpu)
        _HAS_EASYOCR = True
        print("EasyOCR loaded successfully.")
    except Exception as e:
        print(f"Failed to load EasyOCR: {e}")
        _HAS_EASYOCR = False

class CubiCasaWorker(QThread):
    """
    Standard CubiCasa analysis (Rooms/Items/Polygons).
    OCR has been removed from here.
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
            print("--- Starting CubiCasa Analysis ---")
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

            pred_np = pred.cpu().numpy()[0]
            
            # Helper: Create Overlay
            def create_overlay(segmentation_map, colors, start_idx=1, smoothing=True):
                overlay = np.zeros((height, width, 4), dtype=np.uint8)
                for i in range(start_idx, len(colors)):
                    if i >= len(colors): break
                    mask = (segmentation_map == i).astype(np.uint8) * 255
                    mask = cv2.resize(mask, (width, height), interpolation=cv2.INTER_NEAREST)
                    if smoothing:
                        mask = cv2.GaussianBlur(mask, (7, 7), 0)
                        _, mask = cv2.threshold(mask, 127, 255, cv2.THRESH_BINARY)
                    if np.any(mask):
                        overlay[mask > 0, 0:3] = colors[i]
                        overlay[mask > 0, 3] = 140 
                return overlay

            room_colors, icon_colors = constants.get_class_colors()

            # Initial Visual Layers (Rough)
            room_pred = pred_np[21:33]
            room_seg = np.argmax(room_pred, axis=0)
            room_layer = create_overlay(room_seg, room_colors, start_idx=1)

            icon_pred = pred_np[33:44]
            icon_seg = np.argmax(icon_pred, axis=0)
            item_layer = create_overlay(icon_seg, icon_colors, start_idx=1)

            boq_data = {"rooms": [], "icons": []}

            # Polygon Extraction
            try:
                split = [21, 12, 11]
                heatmaps, rooms, icons = split_prediction(pred, [height, width], split)
                polygons, types, room_polygons, room_types = get_polygons((heatmaps, rooms, icons), 0.4, [1, 2])
                
                # Rasterize Vectors for clean layers
                pol_room_seg, pol_icon_seg = polygons_to_image(polygons, types, room_polygons, room_types, height, width)
                room_layer = create_overlay(pol_room_seg, room_colors, start_idx=1, smoothing=False)
                item_layer = create_overlay(pol_icon_seg, icon_colors, start_idx=1, smoothing=False)

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
                    except: pass

                # Process Icons
                for i, poly in enumerate(polygons):
                    type_info = types[i]
                    class_idx = type_info['class']
                    if type_info.get('type', '') == 'icon':
                        label_name = constants.ICON_CLASSES[class_idx] if 0 <= class_idx < len(constants.ICON_CLASSES) else "Unknown"
                        boq_data["icons"].append({"class_id": int(class_idx), "label": label_name, "points": poly.tolist()})
                    
            except Exception as e:
                print(f"Polygon extraction error: {e}")

            # Save
            base_name = os.path.splitext(os.path.basename(self.image_path))[0]
            room_path = f"temp_{base_name}_rooms.png"
            item_path = f"temp_{base_name}_items.png"
            json_path = f"temp_{base_name}_data.json"
            
            cv2.imwrite(room_path, cv2.cvtColor(room_layer, cv2.COLOR_RGBA2BGRA))
            cv2.imwrite(item_path, cv2.cvtColor(item_layer, cv2.COLOR_RGBA2BGRA))
            
            with open(json_path, 'w') as f:
                json.dump(boq_data, f, indent=4)
            
            self.finished.emit(room_path, item_path, json_path)

        except Exception as e:
            self.error.emit(str(e))


class OCRWorker(QThread):
    """
    Dedicated worker for Multi-directional OCR.
    Includes Non-Maximum Suppression to remove duplicates.
    Generates a dedicated transparent layer.
    """
    finished = Signal(str, list) # (layer_path, data_list)
    error = Signal(str)

    def __init__(self, image_path):
        super().__init__()
        self.image_path = image_path

    def calculate_iou(self, boxA, boxB):
        # determine the (x, y)-coordinates of the intersection rectangle
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
                    if prob < 0.50: continue # User requested > 50% only

                    # Transform back to global coords
                    clean_bbox = []
                    for p in bbox:
                        ox, oy = trans_func(p[0], p[1], width, height)
                        clean_bbox.append([int(ox), int(oy)])
                    
                    # Convert to rect [x1, y1, x2, y2] for IOU check
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
            # Sort by confidence descending
            candidates.sort(key=lambda x: x["conf"], reverse=True)
            final_results = []
            
            while candidates:
                best = candidates.pop(0)
                final_results.append(best)
                
                # Compare best against all remaining to find duplicates
                remaining = []
                for other in candidates:
                    iou = self.calculate_iou(best["rect"], other["rect"])
                    # If they overlap significantly (> 20%), assume they are the same text
                    # Since 'best' has higher confidence, we keep 'best' and discard 'other'
                    if iou < 0.20:
                        remaining.append(other)
                candidates = remaining

            # 3. Create Visual Layer
            ocr_layer = np.zeros((height, width, 4), dtype=np.uint8)
            
            for item in final_results:
                pts = np.array(item["poly"], dtype=np.int32)
                x, y, w, h = cv2.boundingRect(pts)
                
                # Visual style: Black text with white glow
                text_str = item["text"]
                font = cv2.FONT_HERSHEY_SIMPLEX
                scale = 0.6
                thickness = 2
                
                # White Outline
                cv2.putText(ocr_layer, text_str, (x, y), font, scale, (255, 255, 255, 255), thickness + 3, cv2.LINE_AA)
                # Black Text
                cv2.putText(ocr_layer, text_str, (x, y), font, scale, (0, 0, 0, 255), thickness, cv2.LINE_AA)

            # 4. Save
            base_name = os.path.splitext(os.path.basename(self.image_path))[0]
            layer_path = f"temp_{base_name}_ocr_layer.png"
            cv2.imwrite(layer_path, cv2.cvtColor(ocr_layer, cv2.COLOR_RGBA2BGRA))
            
            self.finished.emit(layer_path, final_results)

        except Exception as e:
            import traceback
            traceback.print_exc()
            self.error.emit(str(e))