import sys
import os
import fitz  # PyMuPDF

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QScrollArea, QLabel, QFileDialog, QTabWidget, QPushButton, QMessageBox
)
from PySide6.QtGui import QPixmap, QImage, QIcon
from PySide6.QtCore import Qt, Slot

# --- Local Module Imports ---
from widgets import DocumentViewer, LegendWidget
from worker import CubiCasaWorker

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