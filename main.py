import sys
import os
import threading
import subprocess
import re
import inspect
import json  # Added for data export
from collections import Counter

import fitz  # PyMuPDF
from PIL import Image
import numpy as np
import cv2

# PySide6 imports
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QScrollArea, QLabel, QFileDialog, QTabWidget, QSplitter,
    QFrame, QTabBar, QPushButton, QTextEdit, QLineEdit, QMessageBox,
    QToolButton, QDockWidget
)
from PySide6.QtGui import QPixmap, QImage, QIcon, QWheelEvent, QPainter, QColor
from PySide6.QtCore import Qt, QEvent, Signal, Slot, QThread, QSize

# --- CubiCasa5k Imports ---
try:
    import torch
    import torch.nn as nn
    from floortrans.models.hg_furukawa_original import hg_furukawa_original
    # NEW: Import native contour extraction tools
    from floortrans.post_prosessing import split_prediction, get_polygons
except ImportError as e:
    print(f"Error importing CubiCasa modules: {e}")
    print("Ensure main.py is running from the root of the CubiCasa5k repository.")
    torch = None

# --- EasyOCR Setup ---
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


# ----------------- Constants & Helpers -----------------

ROOM_CLASSES = [
    "Background", "Outdoor", "Wall", "Kitchen", "Living Room", 
    "Bed Room", "Bath", "Entry", "Railing", "Storage", "Garage", "Undefined"
]

ICON_CLASSES = [
    "No Icon", "Window", "Door", "Closet", "Electrical Appliance", 
    "Toilet", "Sink", "Sauna Bench", "Fire Place", "Bathtub", "Chimney"
]

def get_class_colors():
    """
    Generates the same color maps used in inference.
    Returns (room_colors, icon_colors).
    """
    np.random.seed(42)
    
    # Room colors (13 to be safe, for 12 classes)
    room_colors = np.random.randint(100, 255, (13, 3), dtype=np.uint8)
    room_colors[0] = [0, 0, 0]
    
    # Icon colors
    icon_colors = np.random.randint(0, 200, (12, 3), dtype=np.uint8)
    icon_colors[:, 0] = 255  # High Red channel for visibility
    icon_colors[0] = [0, 0, 0]
    
    return room_colors, icon_colors


# ----------------- CubiCasa Analysis Thread -----------------

class CubiCasaWorker(QThread):
    """
    Background thread to run CubiCasa5k inference.
    Generates separate transparent layers for Rooms and Items.
    Also extracts contours (polygons) for BOQ generation.
    """
    # Update signal to include JSON data path
    finished = Signal(str, str, str)  # (room_layer_path, item_layer_path, json_data_path)
    error = Signal(str)

    def __init__(self, image_path, model_path="model_best_val_loss_var.pkl"):
        super().__init__()
        self.image_path = image_path
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
                overlay = np.zeros((segmentation_map.shape[0], segmentation_map.shape[1], 4), dtype=np.uint8)
                for i in range(start_idx, len(colors)):
                    if i >= len(colors): break
                    mask = (segmentation_map == i)
                    if np.any(mask):
                        overlay[mask, 0:3] = colors[i]
                        overlay[mask, 3] = 140 
                overlay = cv2.resize(overlay, (width, height), interpolation=cv2.INTER_NEAREST)
                return overlay

            room_colors, icon_colors = get_class_colors()

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
                # split_prediction separates the tensor into heatmaps, rooms, and icons
                # get_polygons converts these heatmaps into vector coordinates
                heatmaps, rooms, icons = split_prediction(pred)
                pol_rooms, pol_icons = get_polygons((heatmaps, rooms, icons), 0.2, [height, width])
                
                # Structure Room Data
                # pol_rooms is typically [class_index, points_array]
                for poly in pol_rooms:
                    class_idx = int(poly[0])
                    points = poly[1]
                    label_name = ROOM_CLASSES[class_idx] if 0 <= class_idx < len(ROOM_CLASSES) else "Unknown"
                    
                    # Calculate Area (Simple polygon area)
                    # This area is in Pixels. You need a scale factor to get Meters.
                    area_px = 0.5 * np.abs(np.dot(points[:, 0], np.roll(points[:, 1], 1)) - np.dot(points[:, 1], np.roll(points[:, 0], 1)))
                    
                    boq_data["rooms"].append({
                        "class_id": class_idx,
                        "label": label_name,
                        "area_pixels": float(area_px),
                        "points": points.tolist() # Convert numpy to list for JSON
                    })

                # Structure Icon Data
                for poly in pol_icons:
                    class_idx = int(poly[0])
                    points = poly[1]
                    label_name = ICON_CLASSES[class_idx] if 0 <= class_idx < len(ICON_CLASSES) else "Unknown"
                    
                    boq_data["icons"].append({
                        "class_id": class_idx,
                        "label": label_name,
                        "points": points.tolist()
                    })
                    
            except Exception as e:
                print(f"Native polygon extraction failed: {e}. Using OpenCV fallback.")
                # Fallback: Extract from the segmentation masks we already made
                # (Robustness measure in case floortrans internal APIs vary)
                
                # Process Rooms
                for i in range(1, len(ROOM_CLASSES)):
                    mask = ((room_seg == i).astype(np.uint8)) * 255
                    mask = cv2.resize(mask, (width, height), interpolation=cv2.INTER_NEAREST)
                    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                    for cnt in contours:
                        area = cv2.contourArea(cnt)
                        if area > 100: # Filter noise
                            boq_data["rooms"].append({
                                "class_id": i,
                                "label": ROOM_CLASSES[i],
                                "area_pixels": float(area),
                                "points": cnt.squeeze().tolist()
                            })

                # Process Icons
                for i in range(1, len(ICON_CLASSES)):
                    mask = ((icon_seg == i).astype(np.uint8)) * 255
                    mask = cv2.resize(mask, (width, height), interpolation=cv2.INTER_NEAREST)
                    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                    for cnt in contours:
                        boq_data["icons"].append({
                            "class_id": i,
                            "label": ICON_CLASSES[i],
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

# ----------------- UI Components -----------------

class LegendWidget(QWidget):
    """
    Displays color keys for Rooms and Icons.
    """
    def __init__(self):
        super().__init__()
        self.layout = QVBoxLayout(self)
        self.layout.setAlignment(Qt.AlignTop)
        
        self.room_colors, self.icon_colors = get_class_colors()
        
        self.room_container = QWidget()
        self.room_layout = QVBoxLayout(self.room_container)
        self.room_layout.setContentsMargins(0,0,0,0)
        self.layout.addWidget(QLabel("<b>Rooms</b>"))
        self.layout.addWidget(self.room_container)
        
        self.item_container = QWidget()
        self.item_layout = QVBoxLayout(self.item_container)
        self.item_layout.setContentsMargins(0,0,0,0)
        self.layout.addWidget(QLabel("<b>Items</b>"))
        self.layout.addWidget(self.item_container)

        self.populate_legend(self.room_layout, ROOM_CLASSES, self.room_colors)
        self.populate_legend(self.item_layout, ICON_CLASSES, self.icon_colors)
        
        self.room_container.setVisible(False)
        self.item_container.setVisible(False)

    def populate_legend(self, layout, classes, colors):
        for i in range(1, len(classes)):
            if i >= len(colors): break
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 2, 0, 2)
            
            color_lbl = QLabel()
            color_lbl.setFixedSize(20, 20)
            c = colors[i]
            hex_c = f"#{c[0]:02x}{c[1]:02x}{c[2]:02x}"
            color_lbl.setStyleSheet(f"background-color: {hex_c}; border: 1px solid gray;")
            
            text_lbl = QLabel(classes[i])
            row_layout.addWidget(color_lbl)
            row_layout.addWidget(text_lbl)
            row_layout.addStretch()
            layout.addWidget(row)

    def set_visibility(self, show_rooms, show_items):
        self.room_container.setVisible(show_rooms)
        self.item_container.setVisible(show_items)

class DocumentViewer(QWidget):
    def __init__(self, file_path):
        super().__init__()
        self.layout = QVBoxLayout(self)
        self.scroll_area = QScrollArea()
        self.label = QLabel()
        self.label.setAlignment(Qt.AlignCenter)
        
        self.scroll_area.setWidget(self.label)
        self.scroll_area.setWidgetResizable(True)
        self.layout.addWidget(self.scroll_area)
        
        self.file_path = file_path
        self.original_pixmap = None
        self.room_pixmap = None
        self.item_pixmap = None
        self.show_rooms = False
        self.show_items = False
        self.zoom_level = 1.0
        self.has_analysis_data = False
        self.load_base_image()

    def load_base_image(self):
        try:
            self.original_pixmap = QPixmap(self.file_path)
            if self.original_pixmap.isNull():
                self.label.setText("Failed to load image.")
            else:
                self.update_view()
        except Exception as e:
            self.label.setText(f"Error: {e}")

    def set_overlays(self, room_path, item_path):
        self.room_pixmap = QPixmap(room_path)
        self.item_pixmap = QPixmap(item_path)
        self.has_analysis_data = True
        self.update_view()

    def toggle_layers(self, show_rooms, show_items):
        self.show_rooms = show_rooms
        self.show_items = show_items
        self.update_view()

    def update_view(self):
        if not self.original_pixmap: return
        final_pixmap = QPixmap(self.original_pixmap)
        painter = QPainter(final_pixmap)
        if self.show_rooms and self.room_pixmap:
            painter.drawPixmap(0, 0, self.room_pixmap)
        if self.show_items and self.item_pixmap:
            painter.drawPixmap(0, 0, self.item_pixmap)
        painter.end()

        if self.zoom_level != 1.0:
            scaled = final_pixmap.scaled(
                final_pixmap.size() * self.zoom_level,
                Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            self.label.setPixmap(scaled)
        else:
            self.label.setPixmap(final_pixmap)

    def wheelEvent(self, event: QWheelEvent):
        if event.modifiers() & Qt.ControlModifier:
            if event.angleDelta().y() > 0: self.zoom_level *= 1.1
            else: self.zoom_level /= 1.1
            self.update_view()
            event.accept()
        else:
            super().wheelEvent(event)

class PDFViewerApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("CubiCasa5k Viewer + BOQ Extractor")
        self.resize(1400, 900)
        self.current_pdf_path = None
        self.temp_files = [] 

        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QHBoxLayout(main_widget)

        # Sidebar
        self.thumbnail_scroll = QScrollArea()
        self.thumbnail_scroll.setFixedWidth(200)
        self.thumbnail_scroll.setWidgetResizable(True)
        self.thumbnail_content = QWidget()
        self.thumbnail_layout = QVBoxLayout(self.thumbnail_content)
        self.thumbnail_layout.setAlignment(Qt.AlignTop)
        self.thumbnail_scroll.setWidget(self.thumbnail_content)
        
        # Tabs
        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self.update_toolbar_state)

        # Legend
        self.legend_scroll = QScrollArea()
        self.legend_scroll.setFixedWidth(220)
        self.legend_scroll.setWidgetResizable(True)
        self.legend = LegendWidget()
        self.legend_scroll.setWidget(self.legend)

        # Controls
        controls = QWidget()
        control_layout = QVBoxLayout(controls)
        btn_open = QPushButton("Open PDF/Image")
        btn_open.clicked.connect(self.open_file)
        
        self.btn_rooms = QPushButton("Room Segmentation")
        self.btn_rooms.setCheckable(True)
        self.btn_rooms.clicked.connect(self.on_toggle_rooms)
        self.btn_rooms.setEnabled(False)
        
        self.btn_items = QPushButton("Item Segmentation")
        self.btn_items.setCheckable(True)
        self.btn_items.clicked.connect(self.on_toggle_items)
        self.btn_items.setEnabled(False)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: gray; font-style: italic;")
        self.status_label.setWordWrap(True)

        control_layout.addWidget(btn_open)
        control_layout.addSpacing(20)
        control_layout.addWidget(self.btn_rooms)
        control_layout.addWidget(self.btn_items)
        control_layout.addWidget(self.status_label)
        control_layout.addStretch()

        layout.addWidget(controls)
        layout.addWidget(self.thumbnail_scroll)
        layout.addWidget(self.tabs)
        layout.addWidget(self.legend_scroll)
        
        self.worker = None

    def open_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open File", "", "PDF/Images (*.pdf *.png *.jpg)")
        if path:
            if path.lower().endswith('.pdf'): self.load_pdf(path)
            else: self.load_single_image(path)

    def load_single_image(self, path):
        self.add_viewer_tab(path, "Image")
        self.clear_layout(self.thumbnail_layout)

    def load_pdf(self, path):
        self.current_pdf_path = path
        self.clear_layout(self.thumbnail_layout)
        try:
            doc = fitz.open(path)
            for i in range(len(doc)):
                page = doc.load_page(i)
                pix = page.get_pixmap(matrix=fitz.Matrix(0.2, 0.2))
                img_data = pix.tobytes("ppm")
                pixmap = QPixmap.fromImage(QImage.fromData(img_data))
                
                btn = QPushButton()
                btn.setIcon(QIcon(pixmap))
                btn.setIconSize(pixmap.size())
                btn.setFixedSize(pixmap.size())
                btn.clicked.connect(lambda checked, p=i: self.load_pdf_page(p))
                
                self.thumbnail_layout.addWidget(btn)
                self.thumbnail_layout.addWidget(QLabel(f"Page {i+1}"))
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not load PDF: {e}")

    def load_pdf_page(self, page_num):
        if not self.current_pdf_path: return
        doc = fitz.open(self.current_pdf_path)
        page = doc.load_page(page_num)
        pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
        temp_path = f"temp_page_{page_num}.png"
        pix.save(temp_path)
        self.temp_files.append(temp_path)
        self.add_viewer_tab(temp_path, f"Page {page_num+1}")

    def add_viewer_tab(self, image_path, title):
        viewer = DocumentViewer(image_path)
        self.tabs.addTab(viewer, title)
        self.tabs.setCurrentWidget(viewer)
        self.update_toolbar_state()

    def update_toolbar_state(self):
        viewer = self.tabs.currentWidget()
        if isinstance(viewer, DocumentViewer):
            self.btn_rooms.setEnabled(True)
            self.btn_items.setEnabled(True)
            self.btn_rooms.blockSignals(True)
            self.btn_items.blockSignals(True)
            self.btn_rooms.setChecked(viewer.show_rooms)
            self.btn_items.setChecked(viewer.show_items)
            self.btn_rooms.blockSignals(False)
            self.btn_items.blockSignals(False)
            self.legend.set_visibility(viewer.show_rooms, viewer.show_items)
            
            if viewer.has_analysis_data:
                self.status_label.setText("Analysis & Data Ready")
            else:
                self.status_label.setText("Ready to Analyze")
        else:
            self.btn_rooms.setEnabled(False)
            self.btn_items.setEnabled(False)
            self.legend.set_visibility(False, False)
            self.status_label.setText("")

    def close_tab(self, index):
        self.tabs.removeTab(index)
        self.update_toolbar_state()

    def clear_layout(self, layout):
        while layout.count():
            child = layout.takeAt(0)
            if child.widget(): child.widget().deleteLater()

    def on_toggle_rooms(self): self.handle_toggle()
    def on_toggle_items(self): self.handle_toggle()

    def handle_toggle(self):
        viewer = self.tabs.currentWidget()
        if not isinstance(viewer, DocumentViewer): return

        rooms_checked = self.btn_rooms.isChecked()
        items_checked = self.btn_items.isChecked()

        if not viewer.has_analysis_data:
            self.btn_rooms.setEnabled(False)
            self.btn_items.setEnabled(False)
            self.status_label.setText("Extracting Contours & Analyzing...")
            
            self.worker = CubiCasaWorker(viewer.file_path)
            self.worker.finished.connect(self.on_analysis_finished)
            self.worker.error.connect(self.on_analysis_error)
            self.worker.start()
        else:
            viewer.toggle_layers(rooms_checked, items_checked)
            self.legend.set_visibility(rooms_checked, items_checked)

    @Slot(str, str, str)
    def on_analysis_finished(self, room_path, item_path, json_path):
        viewer = self.tabs.currentWidget()
        if isinstance(viewer, DocumentViewer):
            viewer.set_overlays(room_path, item_path)
            rooms_checked = self.btn_rooms.isChecked()
            items_checked = self.btn_items.isChecked()
            viewer.toggle_layers(rooms_checked, items_checked)
            self.legend.set_visibility(rooms_checked, items_checked)
            self.temp_files.extend([room_path, item_path, json_path])

        self.btn_rooms.setEnabled(True)
        self.btn_items.setEnabled(True)
        self.status_label.setText(f"Analysis Complete.\nData saved to: {os.path.basename(json_path)}")
        QMessageBox.information(self, "Success", f"Analysis and Contour Extraction complete.\nRaw data saved to {json_path}")

    @Slot(str)
    def on_analysis_error(self, err_msg):
        self.btn_rooms.setEnabled(True)
        self.btn_items.setEnabled(True)
        self.btn_rooms.setChecked(False)
        self.btn_items.setChecked(False)
        self.status_label.setText("Analysis Failed")
        QMessageBox.critical(self, "Analysis Error", err_msg)

    def closeEvent(self, event):
        for f in self.temp_files:
            if os.path.exists(f):
                try: os.remove(f)
                except: pass
        super().closeEvent(event)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    try:
        with open("style.qss", "r") as f:
            app.setStyleSheet(f.read())
    except:
        pass
    window = PDFViewerApp()
    window.show()
    sys.exit(app.exec())