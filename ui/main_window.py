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
from PySide6.QtCore import Qt, Slot

# Imports from sibling files in the 'ui' package
from .viewer import DocumentViewer
from .legend import LegendWidget
from .chat import AIChatPanel

# Import from parent directory
from worker import CubiCasaWorker

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

        # 1. Toggle Buttons (Chat vs Legend) - Hidden by default
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
        
        # Index 0: Chat Panel
        self.chat_panel = AIChatPanel()
        self.right_stack.addWidget(self.chat_panel)
        
        # Index 1: Legend (Wrapped in ScrollArea)
        self.legend_scroll = QScrollArea()
        self.legend_scroll.setWidgetResizable(True)
        self.legend = LegendWidget()
        self.legend_scroll.setWidget(self.legend)
        self.right_stack.addWidget(self.legend_scroll)
        
        self.right_layout.addWidget(self.right_stack)
        
        # Connect Toggles
        self.btn_show_chat.clicked.connect(lambda: self.right_stack.setCurrentIndex(0))
        self.btn_show_legend.clicked.connect(lambda: self.right_stack.setCurrentIndex(1))

        # Hide toggles initially
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

        # Control Buttons
        self.btn_measure = QPushButton("Measure Area")
        self.btn_measure.clicked.connect(self.on_measure_clicked)
        self.btn_measure.setEnabled(False)

        self.btn_mode_toggle = QPushButton("Mode: Grabber")
        self.btn_mode_toggle.setCheckable(True)
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

        # Add all to main layout
        layout.addWidget(controls)
        layout.addWidget(self.thumbnail_scroll)
        layout.addWidget(self.tabs)
        layout.addWidget(self.right_sidebar)
        
        self.worker = None
        self.update_toolbar_state() # Init state

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
            
            # 1. Prepare Page 0 for the viewer
            page0 = doc.load_page(0)
            pix = page0.get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
            temp_path = f"temp_pdf_{random.randint(0,10000)}_page_0.png"
            pix.save(temp_path)
            self.temp_files.append(temp_path)

            # 2. Create the Viewer (This tab represents the PDF)
            viewer = DocumentViewer(temp_path)
            viewer.is_pdf_browser = True
            viewer.pdf_path = path
            viewer.current_page_num = 0

            # 3. Build the Sidebar Widget FOR THIS TAB
            thumbnail_container = QWidget()
            thumbnail_layout = QVBoxLayout(thumbnail_container)
            thumbnail_layout.setAlignment(Qt.AlignTop)
            
            # Store it in the viewer so we can retrieve it later
            viewer.thumbnail_widget = thumbnail_container

            for i in range(len(doc)):
                page = doc.load_page(i)
                # Small thumbnail
                thumb_pix = page.get_pixmap(matrix=fitz.Matrix(0.15, 0.15))
                img_data = thumb_pix.tobytes("ppm")
                qpix = QPixmap.fromImage(QImage.fromData(img_data))
                
                btn = QPushButton()
                btn.setIcon(QIcon(qpix))
                btn.setIconSize(qpix.size())
                btn.setFixedSize(qpix.size())
                btn.setFlat(True)
                btn.setStyleSheet("border: 1px solid #ccc; margin-bottom: 5px;")
                
                # Update current view when clicked
                btn.clicked.connect(lambda checked, v=viewer, p=i: self.navigate_pdf_page(v, p))
                
                thumbnail_layout.addWidget(btn)
                thumbnail_layout.addWidget(QLabel(f"Page {i+1}"))

            self.tabs.addTab(viewer, os.path.basename(path))
            self.tabs.setCurrentWidget(viewer)
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not load PDF: {e}")

    def navigate_pdf_page(self, viewer, page_num):
        """Loads a specific page into the existing viewer."""
        try:
            doc = fitz.open(viewer.pdf_path)
            page = doc.load_page(page_num)
            pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
            temp_path = f"temp_pdf_{random.randint(0,10000)}_page_{page_num}.png"
            pix.save(temp_path)
            self.temp_files.append(temp_path)
            
            viewer.update_image(temp_path)
            viewer.current_page_num = page_num
            
            # Reset toolbar logic since analysis is gone
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
        
        # --- Sidebar Management (Thumbnails) ---
        self.thumbnail_scroll.takeWidget()
        
        if isinstance(viewer, DocumentViewer) and viewer.is_pdf_browser and viewer.thumbnail_widget:
            self.thumbnail_scroll.setWidget(viewer.thumbnail_widget)
            self.thumbnail_scroll.show()
        else:
            self.thumbnail_scroll.hide()

        # --- Controls & Right Pane Management ---
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

            has_data = len(viewer.current_path) > 0 or len(viewer.completed_shapes) > 0

            # --- Update Chat Panel Context ---
            # Isolate chat to this specific viewer
            self.chat_panel.set_active_viewer(viewer)

            if viewer.has_analysis_data and viewer.json_data_path:
                import json
                try:
                    with open(viewer.json_data_path, 'r') as f:
                        boq_data = json.load(f)
                    self.legend.refresh_legend(boq_data)
                    self.legend.set_visibility(viewer.show_rooms, viewer.show_items)
                except:
                    pass 
            else:
                # If no data, clear the legend
                self.legend.refresh_legend({"rooms": [], "icons": []})
                self.legend.set_visibility(False, False)

            # --- Right Pane Logic ---
            if viewer.has_analysis_data:
                self.toggle_container.show()
            else:
                self.toggle_container.hide()
                self.right_stack.setCurrentIndex(0) 
                self.btn_show_chat.setChecked(True)
            
            if viewer.pixel_to_unit_ratio is not None:
                self.btn_measure.setText("Re-calibrate Scale")
            elif has_data:
                self.btn_measure.setText("Re-measure Area")
            else:
                self.btn_measure.setText("Measure Area")
            
            if viewer.mode == "measure":
                self.btn_mode_toggle.setChecked(True)
                self.btn_mode_toggle.setText("Mode: Measurer")
            else:
                self.btn_mode_toggle.setChecked(False)
                self.btn_mode_toggle.setText("Mode: Grabber")

            if viewer.has_analysis_data:
                self.status_label.setText("Analysis & Data Ready")
            elif viewer.is_pdf_browser:
                 self.status_label.setText("PDF Mode: Select segmentation to open Analysis Tab")
            else:
                self.status_label.setText("Ready to Analyze")
        else:
            # No tab selected
            self.btn_rooms.setEnabled(False)
            self.btn_items.setEnabled(False)
            self.legend.set_visibility(False, False)
            self.status_label.setText("")
            self.btn_measure.setEnabled(False)
            self.btn_mode_toggle.setEnabled(False)
            self.thumbnail_scroll.hide()
            
            # Hide right pane contents if no viewer
            self.toggle_container.hide()
            self.chat_panel.set_active_viewer(None)

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
            self.btn_mode_toggle.setText("Mode: Measurer")
        else:
            viewer.set_mode("grab")
            self.btn_mode_toggle.setText("Mode: Grabber")

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
        
        # Fork PDF page into new tab
        if viewer.is_pdf_browser:
            new_title = f"Analysis: Page {viewer.current_page_num + 1}"
            current_image_path = viewer.file_path
            self.add_viewer_tab(current_image_path, new_title)
            self.btn_rooms.setChecked(True) 
            self.btn_items.setChecked(self.sender() == self.btn_items) 
            self.start_worker_on_current_tab()
            return

        # --- Standard Logic ---
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
        import json # Ensure json is imported
        viewer = self.tabs.currentWidget()
        if isinstance(viewer, DocumentViewer):
            viewer.set_overlays(room_path, item_path, json_path)
            
            # Load BOQ data and refresh legend
            try:
                with open(json_path, 'r') as f:
                    boq_data = json.load(f)
                self.legend.refresh_legend(boq_data) # Populate only present items
            except Exception as e:
                print(f"Failed to load BOQ data for legend: {e}")

            rooms_checked = self.btn_rooms.isChecked()
            items_checked = self.btn_items.isChecked()
            viewer.toggle_layers(rooms_checked, items_checked)
            self.legend.set_visibility(rooms_checked, items_checked)
            self.temp_files.extend([room_path, item_path, json_path])
            
            # Right Pane Logic on Finish
            self.toggle_container.show()
            self.right_stack.setCurrentIndex(1) # Switch to Legend automatically
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