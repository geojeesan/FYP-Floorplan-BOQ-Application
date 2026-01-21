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
except ImportError as e:
    print(f"Error importing CubiCasa modules: {e}")
    print("Ensure main.py is running from the root of the CubiCasa5k repository.")
    torch = None

# --- EasyOCR Setup (Optional/Placeholder) ---
import easyocr
try:
    print("Loading EasyOCR model...")
    EASYOCR_READER = easyocr.Reader(['en'], gpu=torch.cuda.is_available() if torch else False)
    _HAS_EASYOCR = True
    print("EasyOCR loaded successfully.")
except Exception as e:
    EASYOCR_READER = None
    _HAS_EASYOCR = False
    print(f"Failed to load EasyOCR. OCR will be disabled: {e}")

class CubiCasaWorker(QThread):
    """
    Background thread to run CubiCasa5k inference.
    Generates separate transparent layers for Rooms and Items.
    Also extracts contours (polygons) for BOQ generation.
    """
    finished = Signal(str, str, str)  # (room_layer_path, item_layer_path, json_data_path)
    error = Signal(str)

    def __init__(self, image_path, scale_ratio=1.0, model_path="model_best_val_loss_var.pkl"):
        super().__init__()
        self.image_path = image_path
        self.scale_ratio = scale_ratio
        self.model_path = model_path

    def snap_to_90(points):
        """
        Snaps polygon points to 0, 90, 180, or 270 degrees.
        Ensures the resulting polygon is 'Manhattan-style'.
        """
        if len(points) < 3:
            return points

        snapped_points = []
        for i in range(len(points)):
            p1 = points[i]
            p2 = points[(i + 1) % len(points)] # Next point (looping)
            
            dx = p2[0] - p1[0]
            dy = p2[1] - p1[1]
            
            # Determine if the line is more horizontal or vertical
            if abs(dx) > abs(dy):
                # Snap to horizontal: keep y constant
                snapped_points.append([p1[0], p1[1]])
                p2[1] = p1[1] 
            else:
                # Snap to vertical: keep x constant
                snapped_points.append([p1[0], p1[1]])
                p2[0] = p1[0]
                
        return np.array(snapped_points)

    def run(self):
        if not torch:
            self.error.emit("PyTorch or CubiCasa modules not found.")
            return

        if not os.path.exists(self.model_path):
            self.error.emit(f"Model file not found: {self.model_path}")
            return

        try:
            print("--- Starting CubiCasa Analysis ---")
            
            # 1. Load and Preprocess Image
            fplan = cv2.imread(self.image_path)
            if fplan is None:
                self.error.emit("Could not read image file.")
                return
                
            fplan = cv2.cvtColor(fplan, cv2.COLOR_BGR2RGB)
            original_shape = fplan.shape[:2] # H, W
            height, width = original_shape
            
            # Normalize [-1, 1]
            img_norm = 2 * (fplan / 255.0) - 1
            img_norm = np.moveaxis(img_norm, -1, 0) # HWC -> CHW
            input_tensor = torch.tensor(img_norm).float().unsqueeze(0)

            # 2. Load Model
            print("Initializing model architecture...")
            model = hg_furukawa_original(44)
            
            print(f"Loading weights from {self.model_path}...")
            checkpoint = torch.load(self.model_path, map_location='cpu')
            if 'model_state' in checkpoint:
                state_dict = checkpoint['model_state']
            else:
                state_dict = checkpoint
            model.load_state_dict(state_dict)
            
            device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            model.to(device)
            input_tensor = input_tensor.to(device)
            model.eval()

            # 3. Inference
            print("Running model inference...")
            with torch.no_grad():
                pred = model(input_tensor)

            # 4. Post-processing (Visual Layers)
            print("Processing visual output layers...")
            pred_np = pred.cpu().numpy()[0]
            
            # --- Helper to create transparent RGBA overlay ---
            def create_overlay(segmentation_map, colors, start_idx=1):
                # Upscale first for better smoothing resolution
                overlay = np.zeros((height, width, 4), dtype=np.uint8)
                
                for i in range(start_idx, len(colors)):
                    if i >= len(colors): break
                    
                    # Create a binary mask for this class and resize to original image size
                    mask = (segmentation_map == i).astype(np.uint8) * 255
                    mask = cv2.resize(mask, (width, height), interpolation=cv2.INTER_NEAREST)
                    
                    # --- SMOOTHING THE VISUAL MASK ---
                    # 1. Blur the mask to soften edges
                    mask = cv2.GaussianBlur(mask, (7, 7), 0)
                    # 2. Re-threshold to sharpen the edges back up but with smoother curves
                    _, mask = cv2.threshold(mask, 127, 255, cv2.THRESH_BINARY)
                    
                    if np.any(mask):
                        overlay[mask > 0, 0:3] = colors[i]
                        overlay[mask > 0, 3] = 140 
                        
                return overlay

            room_colors, icon_colors = constants.get_class_colors()

            # Rooms
            room_pred = pred_np[21:33]
            room_seg = np.argmax(room_pred, axis=0)
            room_layer = create_overlay(room_seg, room_colors, start_idx=1)

            # Items
            icon_pred = pred_np[33:44]
            icon_seg = np.argmax(icon_pred, axis=0)
            item_layer = create_overlay(icon_seg, icon_colors, start_idx=1)

            # 5. Contour Extraction (The Logic Layer for BOQ)
            print("Extracting contours (Polygons) for BOQ...")
            boq_data = {"rooms": [], "icons": []}

            try:
                # A. Use Native CubiCasa functions if possible
                heatmaps, rooms, icons = split_prediction(pred)
                pol_rooms, pol_icons = get_polygons((heatmaps, rooms, icons), 0.2, [height, width])
                
                # Structure Room Data
                for poly in pol_rooms:
                    class_idx = int(poly[0])
                    points = poly[1]
                    label_name = constants.ROOM_CLASSES[class_idx] if 0 <= class_idx < len(constants.ROOM_CLASSES) else "Unknown"
                    
                    # Calculate pixel area using Shoelace formula
                    area_px = 0.5 * np.abs(np.dot(points[:, 0], np.roll(points[:, 1], 1)) - np.dot(points[:, 1], np.roll(points[:, 0], 1)))
                    
                    boq_data["rooms"].append({
                        "class_id": class_idx,
                        "label": label_name,
                        "area_pixels": float(area_px),
                        "points": points.tolist() 
                    })

                # Structure Icon Data
                for poly in pol_icons:
                    class_idx = int(poly[0])
                    points = poly[1]
                    label_name = constants.ICON_CLASSES[class_idx] if 0 <= class_idx < len(constants.ICON_CLASSES) else "Unknown"
                    
                    boq_data["icons"].append({
                        "class_id": class_idx,
                        "label": label_name,
                        "points": points.tolist()
                    })
                    
            except Exception as e:
                print(f"Native polygon extraction failed: {e}. Using OpenCV fallback.")
                
                # Process Rooms
                for i in range(1, len(constants.ROOM_CLASSES)):
                    mask = ((room_seg == i).astype(np.uint8)) * 255
                    mask = cv2.resize(mask, (width, height), interpolation=cv2.INTER_NEAREST)
                    
                    # Optional: Morphological Opening to remove small artifacts/noise
                    kernel = np.ones((5,5), np.uint8)
                    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
                    
                    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                    
                    for cnt in contours:
                        area = cv2.contourArea(cnt)
                        if area > 500: 
                            # Adjust 0.01 to 0.02 for more aggressive smoothing.
                            epsilon = 0.01 * cv2.arcLength(cnt, True)
                            approx = cv2.approxPolyDP(cnt, epsilon, True)
                            
                            boq_data["rooms"].append({
                                "class_id": i,
                                "label": constants.ROOM_CLASSES[i],
                                "area_pixels": float(area),
                                "points": approx.squeeze().tolist()
                            })

                # Process Icons
                for i in range(1, len(constants.ICON_CLASSES)):
                    mask = ((icon_seg == i).astype(np.uint8)) * 255
                    mask = cv2.resize(mask, (width, height), interpolation=cv2.INTER_NEAREST)
                    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                    for cnt in contours:
                        boq_data["icons"].append({
                            "class_id": i,
                            "label": constants.ICON_CLASSES[i],
                            "points": cnt.squeeze().tolist()
                        })

            # 6. Save Outputs
            base_name = os.path.splitext(os.path.basename(self.image_path))[0]
            room_path = f"temp_{base_name}_rooms.png"
            item_path = f"temp_{base_name}_items.png"
            json_path = f"temp_{base_name}_data.json"
            
            cv2.imwrite(room_path, cv2.cvtColor(room_layer, cv2.COLOR_RGBA2BGRA))
            cv2.imwrite(item_path, cv2.cvtColor(item_layer, cv2.COLOR_RGBA2BGRA))
            
            with open(json_path, 'w') as f:
                json.dump(boq_data, f, indent=4)
            
            print(f"Analysis Saved: {room_path}, {item_path}")
            print(f"Data JSON Saved: {json_path}")
            
            self.finished.emit(room_path, item_path, json_path)

        except Exception as e:
            import traceback
            traceback.print_exc()
            self.error.emit(str(e))