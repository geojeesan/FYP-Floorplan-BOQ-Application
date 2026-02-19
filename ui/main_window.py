import os
import sys
import fitz  # PyMuPDF
import random
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QScrollArea, QLabel, QFileDialog, QTabWidget, QPushButton, QMessageBox,
    QStackedWidget, QButtonGroup
)
from PySide6.QtGui import QPixmap, QImage, QIcon
import qtawesome as qta
from PySide6.QtCore import Qt, Slot

# Imports from sibling files in the 'ui' package
from .viewer import DocumentViewer
from .legend import LegendWidget
from .chat import AIChatPanel

# Import from parent directory
from worker import CubiCasaWorker, OCRWorker
import constants
from shapely.geometry import Point, Polygon as ShapelyPolygon

class PDFViewerApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PDF BOQ Viewer")
        self.resize(1400, 900)
        self.current_pdf_path = None
        self.temp_files = [] 

        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QHBoxLayout(main_widget)

        # Sidebar (Initially Empty)
        self.thumbnail_scroll = QScrollArea()
        self.thumbnail_scroll.setFixedWidth(100)
        self.thumbnail_scroll.setWidgetResizable(True)
        
        # Tabs
        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self.update_toolbar_state)

        # --- Right Sidebar Configuration ---
        self.right_sidebar = QWidget()
        self.right_sidebar.setFixedWidth(320)
        self.right_layout = QVBoxLayout(self.right_sidebar)
        self.right_layout.setContentsMargins(5, 5, 5, 5)

        # 1. Toggle Buttons
        self.toggle_container = QWidget()
        toggle_layout = QHBoxLayout(self.toggle_container)
        toggle_layout.setContentsMargins(0, 0, 0, 0)
        
        self.btn_show_chat = QPushButton("Chat")
        self.btn_show_chat.setCheckable(True)
        self.btn_show_chat.setChecked(True)
        
        self.btn_show_legend = QPushButton("Legend / Data")
        self.btn_show_legend.setCheckable(True)
        
        self.view_group = QButtonGroup(self)
        self.view_group.addButton(self.btn_show_chat)
        self.view_group.addButton(self.btn_show_legend)
        
        toggle_layout.addWidget(self.btn_show_chat)
        toggle_layout.addWidget(self.btn_show_legend)
        
        self.right_layout.addWidget(self.toggle_container)
        
        # 2. Stacked Widget
        self.right_stack = QStackedWidget()
        
        self.chat_panel = AIChatPanel()
        self.right_stack.addWidget(self.chat_panel)
        
        self.legend_scroll = QScrollArea()
        self.legend_scroll.setWidgetResizable(True)
        self.legend = LegendWidget()
        # Connect the OCR Signals
        self.legend.ocrRequested.connect(self.on_ocr_requested)
        self.legend.ocrLabelsToggled.connect(self.on_toggle_ocr_labels)
        
        self.legend_scroll.setWidget(self.legend)
        self.right_stack.addWidget(self.legend_scroll)
        
        self.right_layout.addWidget(self.right_stack)
        
        self.btn_show_chat.clicked.connect(lambda: self.right_stack.setCurrentIndex(0))
        self.btn_show_legend.clicked.connect(lambda: self.right_stack.setCurrentIndex(1))

        self.toggle_container.hide()

        # Controls Left Side
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

        self.btn_measure = QPushButton()
        self.btn_measure.setIcon(qta.icon('fa5s.ruler-combined'))
        self.btn_measure.setToolTip("Measure Area")
        self.btn_measure.clicked.connect(self.on_measure_clicked)
        self.btn_measure.setEnabled(False)

        self.btn_mode_toggle = QPushButton()
        self.btn_mode_toggle.setCheckable(True)
        self.btn_mode_toggle.setIcon(qta.icon('fa5s.hand-rock'))
        self.btn_mode_toggle.setToolTip("Mode: Grabber")
        self.btn_mode_toggle.clicked.connect(self.toggle_interaction_mode)
        self.btn_mode_toggle.setEnabled(False)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: gray; font-style: italic;")
        self.status_label.setWordWrap(True)

        control_layout.addWidget(btn_open)
        control_layout.addSpacing(20)
        control_layout.addWidget(self.btn_rooms)
        control_layout.addWidget(self.btn_items)
        control_layout.addWidget(self.status_label)
        control_layout.addSpacing(10)
        control_layout.addWidget(self.btn_measure)
        control_layout.addWidget(self.btn_mode_toggle)
        control_layout.addStretch()

        layout.addWidget(controls)
        layout.addWidget(self.thumbnail_scroll)
        layout.addWidget(self.tabs)
        layout.addWidget(self.right_sidebar)
        
        self.worker = None
        self.ocr_worker = None # Worker for OCR
        self.update_toolbar_state()

    # ... (open_file, load_pdf, etc. remain unchanged) ...
    def open_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open File", "", "PDF/Images (*.pdf *.png *.jpg)")
        if path:
            if path.lower().endswith('.pdf'): self.load_pdf(path)
            else: self.load_single_image(path)

    def load_single_image(self, path):
        self.add_viewer_tab(path, "Image")

    def load_pdf(self, path):
        self.current_pdf_path = path
        try:
            doc = fitz.open(path)
            page0 = doc.load_page(0)
            pix = page0.get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
            temp_path = f"temp_pdf_{random.randint(0,10000)}_page_0.png"
            pix.save(temp_path)
            self.temp_files.append(temp_path)

            viewer = DocumentViewer(temp_path)
            viewer.is_pdf_browser = True
            viewer.pdf_path = path
            viewer.current_page_num = 0

            thumbnail_container = QWidget()
            thumbnail_layout = QVBoxLayout(thumbnail_container)
            thumbnail_layout.setAlignment(Qt.AlignTop)
            viewer.thumbnail_widget = thumbnail_container

            for i in range(len(doc)):
                page = doc.load_page(i)
                thumb_pix = page.get_pixmap(matrix=fitz.Matrix(0.15, 0.15))
                img_data = thumb_pix.tobytes("ppm")
                qpix = QPixmap.fromImage(QImage.fromData(img_data))
                
                btn = QPushButton()
                btn.setIcon(QIcon(qpix))
                btn.setIconSize(qpix.size())
                btn.setFixedSize(qpix.size())
                btn.setFlat(True)
                btn.setStyleSheet("border: 1px solid #ccc; margin-bottom: 5px;")
                btn.clicked.connect(lambda checked, v=viewer, p=i: self.navigate_pdf_page(v, p))
                
                thumbnail_layout.addWidget(btn)
                thumbnail_layout.addWidget(QLabel(f"Page {i+1}"))

            self.tabs.addTab(viewer, os.path.basename(path))
            self.tabs.setCurrentWidget(viewer)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not load PDF: {e}")

    def navigate_pdf_page(self, viewer, page_num):
        try:
            doc = fitz.open(viewer.pdf_path)
            page = doc.load_page(page_num)
            pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
            temp_path = f"temp_pdf_{random.randint(0,10000)}_page_{page_num}.png"
            pix.save(temp_path)
            self.temp_files.append(temp_path)
            
            viewer.update_image(temp_path)
            viewer.current_page_num = page_num
            self.update_toolbar_state()
        except Exception as e:
            print(f"Error navigating PDF: {e}")

    def add_viewer_tab(self, image_path, title):
        viewer = DocumentViewer(image_path)
        self.tabs.addTab(viewer, title)
        self.tabs.setCurrentWidget(viewer)
        self.update_toolbar_state()

    def update_toolbar_state(self):
        viewer = self.tabs.currentWidget()
        
        self.thumbnail_scroll.takeWidget()
        if isinstance(viewer, DocumentViewer):
            self.setWindowTitle(f"PDF BOQ Viewer - {viewer.file_path}")
        else:
            self.setWindowTitle("PDF BOQ Viewer")

        if isinstance(viewer, DocumentViewer) and viewer.is_pdf_browser and viewer.thumbnail_widget:
            self.thumbnail_scroll.setWidget(viewer.thumbnail_widget)
            self.thumbnail_scroll.show()
        else:
            self.thumbnail_scroll.hide()

        if isinstance(viewer, DocumentViewer):
            self.btn_rooms.setEnabled(True)
            self.btn_items.setEnabled(True)
            
            self.btn_rooms.blockSignals(True)
            self.btn_items.blockSignals(True)
            self.btn_rooms.setChecked(viewer.show_rooms)
            self.btn_items.setChecked(viewer.show_items)
            self.btn_rooms.blockSignals(False)
            self.btn_items.blockSignals(False)
            
            self.btn_measure.setEnabled(True)
            self.btn_mode_toggle.setEnabled(True)

            # Update Legend Button State for OCR
            self.legend.btn_ocr.blockSignals(True)
            self.legend.btn_ocr.setChecked(viewer.show_ocr)
            if not viewer.has_ocr_data:
                self.legend.btn_ocr.setChecked(False)
            self.legend.btn_ocr.blockSignals(False)

            self.chat_panel.set_active_viewer(viewer)

            if viewer.has_analysis_data and viewer.json_data_path:
                import json
                try:
                    with open(viewer.json_data_path, 'r') as f:
                        boq_data = json.load(f)
                    self.legend.refresh_legend(boq_data)
                    self.legend.set_visibility(viewer.show_rooms, viewer.show_items)
                except: pass 
            else:
                self.legend.refresh_legend({"rooms": [], "icons": []})
                self.legend.set_visibility(False, False)

            if viewer.has_analysis_data:
                self.toggle_container.show()
            else:
                self.toggle_container.hide()
                self.right_stack.setCurrentIndex(0) 
                self.btn_show_chat.setChecked(True)
            
            if viewer.pixel_to_unit_ratio is not None:
                # self.btn_measure.setText("Re-calibrate Scale")
                self.btn_measure.setToolTip("Re-calibrate Scale")
                self.btn_measure.setIcon(qta.icon('fa5s.ruler-vertical', color='orange'))
            elif len(viewer.current_path) > 0 or len(viewer.completed_shapes) > 0:
                # self.btn_measure.setText("Re-measure Area")
                self.btn_measure.setToolTip("Re-measure Area")
                self.btn_measure.setIcon(qta.icon('fa5s.ruler-combined', color='blue'))
            else:
                # self.btn_measure.setText("Measure Area")
                self.btn_measure.setToolTip("Measure Area")
                self.btn_measure.setIcon(qta.icon('fa5s.ruler-combined'))
            
            if viewer.mode == "measure":
                self.btn_mode_toggle.setChecked(True)
                # self.btn_mode_toggle.setText("Mode: Measurer")
                self.btn_mode_toggle.setToolTip("Mode: Measurer")
                self.btn_mode_toggle.setIcon(qta.icon('fa5s.crosshairs'))
            else:
                self.btn_mode_toggle.setChecked(False)
                # self.btn_mode_toggle.setText("Mode: Grabber")
                self.btn_mode_toggle.setToolTip("Mode: Grabber")
                self.btn_mode_toggle.setIcon(qta.icon('fa5s.hand-rock'))
            
            if viewer.has_analysis_data:
                self.status_label.setText("Analysis Ready")
            else:
                self.status_label.setText("Ready to Analyze")
        else:
            self.btn_rooms.setEnabled(False)
            self.btn_items.setEnabled(False)
            self.legend.set_visibility(False, False)
            self.status_label.setText("")
            self.btn_measure.setEnabled(False)
            self.btn_mode_toggle.setEnabled(False)
            self.thumbnail_scroll.hide()
            self.toggle_container.hide()
            self.chat_panel.set_active_viewer(None)

    # --- OCR Handling ---
    def on_ocr_requested(self, is_checked):
        viewer = self.tabs.currentWidget()
        if not isinstance(viewer, DocumentViewer): return

        # Case 1: Just toggling visibility if data exists
        if viewer.has_ocr_data:
            viewer.toggle_ocr(is_checked)
            return

        # Case 2: Data doesn't exist, need to run Worker
        if is_checked:
            self.status_label.setText("Running OCR (Scanning 4 angles)...")
            self.legend.btn_ocr.setEnabled(False) # Disable until done
            self.legend.show_progress() # Show progress bar
            
            self.ocr_worker = OCRWorker(viewer.file_path)
            self.ocr_worker.finished.connect(self.on_ocr_finished)
            self.ocr_worker.error.connect(self.on_ocr_error)
            self.ocr_worker.start()
        else:
            viewer.toggle_ocr(False)

    @Slot(str, list)
    def on_ocr_finished(self, layer_path, data_list):
        viewer = self.tabs.currentWidget()
        self.legend.hide_progress() # Hide progress bar
        
        if isinstance(viewer, DocumentViewer):
            viewer.set_ocr_layer(layer_path)
            self.temp_files.append(layer_path)
            
            # --- Match OCR to Rooms ---
            if viewer.has_analysis_data and viewer.boq_data:
                print(f"Matching {len(data_list)} OCR items to rooms...")
                updated_boq = self.match_text_to_rooms(viewer.boq_data, data_list)
                viewer.boq_data = updated_boq
                
                # Save updated JSON
                if viewer.json_data_path:
                    import json
                    try:
                        with open(viewer.json_data_path, 'w') as f:
                            json.dump(updated_boq, f, indent=4)
                    except Exception as e:
                        print(f"Error saving matching JSON: {e}")
                
            # Enable the toggle
            self.legend.btn_toggle_ocr_labels.setVisible(True)
            self.legend.btn_toggle_ocr_labels.setChecked(False)
        
        self.legend.btn_ocr.setEnabled(True)
        self.legend.btn_ocr.setChecked(True)
        self.status_label.setText("OCR Complete.")

    @Slot(str)
    def on_ocr_error(self, err_msg):
        self.legend.hide_progress()
        self.legend.btn_ocr.setEnabled(True)
        self.legend.btn_ocr.setChecked(False)
        self.status_label.setText(f"OCR Failed: {err_msg}")
        QMessageBox.warning(self, "OCR Error", err_msg)

    def match_text_to_rooms(self, boq_data, ocr_results):
        if not ocr_results: return boq_data

        import numpy as np
        # room_polys = []
        # for i, room in enumerate(boq_data.get('rooms', [])):
        #     pts = room.get('points', [])
        #     if len(pts) >= 3:
        #         try:
        #             poly = ShapelyPolygon(pts)
        #             room_polys.append((i, poly))
        #         except: pass

        # Perform checking
        # 1. Prepare Room Polygons
        rooms_with_poly = []
        for i, room in enumerate(boq_data.get('rooms', [])):
            pts = room.get('points', [])
            if len(pts) >= 3:
                try:
                    poly = ShapelyPolygon(pts)
                    rooms_with_poly.append((i, poly))
                except: pass
        
        # 2. Check Overlaps
        for item in ocr_results:
            rect = item.get('rect') # [x1, y1, x2, y2]
            if not rect: continue
            cx = (rect[0] + rect[2]) / 2
            cy = (rect[1] + rect[3]) / 2
            p = Point(cx, cy)
            
            for idx, poly in rooms_with_poly:
                if poly.contains(p):
                    # Found match
                    text = item.get('text', '').strip()
                    
                    # --- Rules ---
                    # 1. Ignore if it's just a number (e.g. "45", "12.5") without unit
                    import re
                    # Regex checks if string is purely numeric (int or float)
                    if re.match(r'^\d+(\.\d+)?$', text):
                        continue
                        
                    # 2. Replace JM -> WC
                    if text == "JM":
                        text = "WC"
                        
                    current_ocr = boq_data['rooms'][idx].get('ocr_text', '')
                    
                    if current_ocr:
                        # Append if not already there
                        if text not in current_ocr:
                            boq_data['rooms'][idx]['ocr_text'] = current_ocr + " " + text
                    else:
                        boq_data['rooms'][idx]['ocr_text'] = text
                        
        return boq_data

    def on_toggle_ocr_labels(self, is_checked):
        viewer = self.tabs.currentWidget()
        if not isinstance(viewer, DocumentViewer) or not viewer.has_analysis_data: return
        
        boq = viewer.boq_data
        if not boq: return

        # Update labels in-place
        for room in boq.get('rooms', []):
            cid = room.get('class_id', -1)
            original_label = constants.ROOM_CLASSES[cid] if 0 <= cid < len(constants.ROOM_CLASSES) else "Unknown"
            
            if is_checked:
                ocr_txt = room.get('ocr_text', None)
                if ocr_txt and len(ocr_txt) > 0:
                    room['label'] = ocr_txt
                else:
                    room['label'] = original_label
            else:
                room['label'] = original_label
        
        # Refresh Legend
        self.legend.refresh_legend(boq)
        # Refresh Viewer (Canvas)
        viewer.update_view()

    # ... (rest of methods: measure, toggle_interaction_mode, etc. unchanged)
    def on_measure_clicked(self):
        viewer = self.tabs.currentWidget()
        if isinstance(viewer, DocumentViewer):
            if viewer.pixel_to_unit_ratio is not None:
                viewer.recalibrate() 
            else:
                viewer.set_mode("measure")
            self.update_toolbar_state()

    def toggle_interaction_mode(self):
        viewer = self.tabs.currentWidget()
        if not viewer: return
        if self.btn_mode_toggle.isChecked():
            viewer.set_mode("measure")
            # self.btn_mode_toggle.setText("Mode: Measurer")
            self.btn_mode_toggle.setIcon(qta.icon('fa5s.crosshairs'))
            self.btn_mode_toggle.setToolTip("Mode: Measurer")
        else:
            viewer.set_mode("grab")
            # self.btn_mode_toggle.setText("Mode: Grabber")
            self.btn_mode_toggle.setIcon(qta.icon('fa5s.hand-rock'))
            self.btn_mode_toggle.setToolTip("Mode: Grabber")

    def close_tab(self, index):
        self.tabs.removeTab(index)
        self.update_toolbar_state()

    def on_toggle_rooms(self): self.handle_toggle()
    def on_toggle_items(self): self.handle_toggle()

    def handle_toggle(self):
        viewer = self.tabs.currentWidget()
        if not isinstance(viewer, DocumentViewer): return
        if viewer.is_pdf_browser:
            new_title = f"Analysis: Page {viewer.current_page_num + 1}"
            current_image_path = viewer.file_path
            self.add_viewer_tab(current_image_path, new_title)
            self.btn_rooms.setChecked(True) 
            self.btn_items.setChecked(self.sender() == self.btn_items) 
            self.start_worker_on_current_tab()
            return
        rooms_checked = self.btn_rooms.isChecked()
        items_checked = self.btn_items.isChecked()
        if not viewer.has_analysis_data:
            self.start_worker_on_current_tab()
        else:
            viewer.toggle_layers(rooms_checked, items_checked)
            self.legend.set_visibility(rooms_checked, items_checked)

    def start_worker_on_current_tab(self):
        viewer = self.tabs.currentWidget()
        self.btn_rooms.setEnabled(False)
        self.btn_items.setEnabled(False)
        self.status_label.setText("Extracting Contours & Analyzing...")
        self.worker = CubiCasaWorker(viewer.file_path)
        self.worker.finished.connect(self.on_analysis_finished)
        self.worker.error.connect(self.on_analysis_error)
        self.worker.start()

    @Slot(str, str, str)
    def on_analysis_finished(self, room_path, item_path, json_path):
        import json 
        viewer = self.tabs.currentWidget()
        if isinstance(viewer, DocumentViewer):
            viewer.set_overlays(room_path, item_path, json_path)
            try:
                with open(json_path, 'r') as f:
                    boq_data = json.load(f)
                self.legend.refresh_legend(boq_data) 
            except Exception as e:
                print(f"Failed to load BOQ data for legend: {e}")

            rooms_checked = self.btn_rooms.isChecked()
            items_checked = self.btn_items.isChecked()
            viewer.toggle_layers(rooms_checked, items_checked)
            self.legend.set_visibility(rooms_checked, items_checked)
            self.temp_files.extend([room_path, item_path, json_path])
            
            self.toggle_container.show()
            self.right_stack.setCurrentIndex(1) 
            self.btn_show_legend.setChecked(True)

        self.btn_rooms.setEnabled(True)
        self.btn_items.setEnabled(True)
        self.status_label.setText(f"Analysis Complete.")

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