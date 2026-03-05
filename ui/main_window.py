import os
import sys
import fitz  # PyMuPDF
import random
from dotenv import load_dotenv, set_key

from PySide6.QtWidgets import (
    QInputDialog, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QScrollArea, QLabel, QFileDialog, QTabWidget, QPushButton, QMessageBox,
    QStackedWidget, QButtonGroup, QTabBar, QDialog, QFormLayout, QLineEdit, 
    QDialogButtonBox, QCheckBox
)
from PySide6.QtGui import QPixmap, QImage, QIcon
import qtawesome as qta
from PySide6.QtCore import Qt, Slot

# Imports from sibling files in the 'ui' package
from .viewer import DocumentViewer
from .legend import LegendWidget
from .chat import AIChatPanel
from .db_editor import DatabaseEditorDialog
import database

# Import from parent directory
from worker import CubiCasaWorker, OCRWorker
import constants
from shapely.geometry import Point, Polygon as ShapelyPolygon

from ui.model_3d import ThreeDViewer

# Load existing environment variables
load_dotenv()


class SettingsDialog(QDialog):
    """Popup Dialog to configure AI Providers, API Keys, and Models."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AI Provider Settings")
        self.setMinimumWidth(500)
        
        main_layout = QVBoxLayout(self)
        
        # Define Providers configuration: (Display Name, Has API Key, Has Custom Models, Env Prefix)
        providers_config = [
            ("Ollama", False, True, "OLLAMA"),
            ("OpenAI", True, False, "OPENAI"),
            ("Google GenAI", True, False, "GOOGLE"),
            ("Anthropic", True, False, "ANTHROPIC"),
            ("OpenRouter", True, True, "OPENROUTER")
        ]
        
        self.provider_data = {}
        
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        
        for name, has_api_key, has_models, prefix in providers_config:
            # Checkbox for enabling/disabling the provider
            default_enabled = "True" if name == "Ollama" else "False"
            is_enabled = os.getenv(f"{prefix}_ENABLED", default_enabled).lower() == "true"
            
            chk_enable = QCheckBox(f"Enable {name}")
            chk_enable.setChecked(is_enabled)
            scroll_layout.addWidget(chk_enable)
            
            # Container for the inner settings (API Key, Custom Models)
            settings_container = QWidget()
            form_layout = QFormLayout(settings_container)
            form_layout.setContentsMargins(25, 0, 0, 15) # Indent underneath checkbox
            
            api_input = None
            if has_api_key:
                api_input = QLineEdit()
                api_input.setEchoMode(QLineEdit.Password)
                api_input.setText(os.getenv(f"{prefix}_API_KEY", ""))
                api_input.setPlaceholderText(f"Enter {name} API Key...")
                form_layout.addRow("API Key:", api_input)
                
            models_input = None
            if has_models:
                models_input = QLineEdit()
                # Defaults
                if prefix == "OLLAMA":
                    default_m = "phi4-mini, llama3, mistral, gemma"
                else:
                    default_m = "meta-llama/llama-3.1-8b-instruct, anthropic/claude-3.5-sonnet"
                
                models_input.setText(os.getenv(f"{prefix}_MODELS", default_m))
                models_input.setPlaceholderText("model_name1, model_name2...")
                form_layout.addRow("Custom Models:", models_input)
                
            scroll_layout.addWidget(settings_container)
            
            # Tie the container visibility to the checkbox state
            chk_enable.toggled.connect(settings_container.setVisible)
            settings_container.setVisible(is_enabled)
            
            self.provider_data[prefix] = {
                "chk_enable": chk_enable,
                "api_input": api_input,
                "models_input": models_input
            }

        scroll_area.setWidget(scroll_content)
        main_layout.addWidget(scroll_area)
            
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.save_keys)
        buttons.rejected.connect(self.reject)
        main_layout.addWidget(buttons)
        
    def save_keys(self):
        env_file = ".env"
        if not os.path.exists(env_file):
            open(env_file, 'w').close()
            
        for prefix, widgets in self.provider_data.items():
            # Save Enabled State
            is_enabled = str(widgets["chk_enable"].isChecked())
            os.environ[f"{prefix}_ENABLED"] = is_enabled
            set_key(env_file, f"{prefix}_ENABLED", is_enabled)
            
            # Save API Key
            if widgets["api_input"]:
                api_val = widgets["api_input"].text().strip()
                os.environ[f"{prefix}_API_KEY"] = api_val
                set_key(env_file, f"{prefix}_API_KEY", api_val)
                
            # Save Custom Models
            if widgets["models_input"]:
                model_val = widgets["models_input"].text().strip()
                os.environ[f"{prefix}_MODELS"] = model_val
                set_key(env_file, f"{prefix}_MODELS", model_val)
                
        self.accept()
        QMessageBox.information(self, "Settings Saved", "Provider settings and API keys updated.")


class PDFViewerApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PDF BOQ Viewer")
        self.setWindowIcon(QIcon("resources/logo.ico"))
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
        self.tabs.currentChanged.connect(self.on_tab_changed)
        
        # Start Screen (Initial View)
        self.start_screen = QWidget()
        start_layout = QVBoxLayout(self.start_screen)
        start_layout.setAlignment(Qt.AlignCenter)
        start_layout.setSpacing(15)
        
        # Logo
        self.logo_label = QLabel()
        logo_pixmap = QPixmap("resources/logo.png")
        if not logo_pixmap.isNull():
            scaled_logo = logo_pixmap.scaled(200, 200, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.logo_label.setPixmap(scaled_logo)
            self.logo_label.setAlignment(Qt.AlignCenter)
            start_layout.addWidget(self.logo_label)
        
        # Big Open Button
        self.btn_big_open = QPushButton("Open PDF / Image")
        self.btn_big_open.setFixedSize(300, 60)
        self.btn_big_open.setStyleSheet("font-size: 20px; font-weight: bold; border-radius: 10px; background-color: #fb9a44; color: white;")
        self.btn_big_open.setCursor(Qt.PointingHandCursor)
        self.btn_big_open.clicked.connect(self.open_file)
        start_layout.addWidget(self.btn_big_open, alignment=Qt.AlignCenter)
        
        # Recent Files Section
        recent_label = QLabel("Recent Files")
        recent_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #eeeeee;")
        start_layout.addWidget(recent_label, alignment=Qt.AlignCenter)
        
        self.recent_scroll = QScrollArea()
        self.recent_scroll.setObjectName("recentFilesScrollArea")
        self.recent_scroll.setWidgetResizable(True)
        self.recent_scroll.setFixedSize(400, 200) 
        
        self.recent_container = QWidget()
        self.recent_container.setObjectName("recentFilesContainer")
        self.recent_files_layout = QVBoxLayout(self.recent_container)
        self.recent_files_layout.setAlignment(Qt.AlignTop)
        self.recent_scroll.setWidget(self.recent_container)
        
        start_layout.addWidget(self.recent_scroll, alignment=Qt.AlignCenter)
        
        # Initialize DB and load the list
        database.init_db()
        self.load_recent_files()
        
        # Stack to hold Tabs or Start Screen
        self.center_stack = QStackedWidget()
        self.center_stack.addWidget(self.start_screen) 
        self.center_stack.addWidget(self.tabs)       

        # Right Sidebar Configuration
        self.right_sidebar = QWidget()
        self.right_sidebar.setFixedWidth(320)
        self.right_layout = QVBoxLayout(self.right_sidebar)
        self.right_layout.setContentsMargins(5, 5, 5, 5)

        # 1. Analyse Button
        self.btn_analyse = QPushButton("Analyse")
        self.btn_analyse.setStyleSheet("""
            QPushButton {
                background-color: #fb9a44; 
                color: white; 
                font-size: 16px; 
                padding: 10px; 
                border-radius: 5px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #e08c3a; }
            QPushButton:disabled { background-color: #cccccc; color: #666666; }
        """)
        self.btn_analyse.setCursor(Qt.PointingHandCursor)
        self.btn_analyse.clicked.connect(self.start_worker_on_current_tab)
        self.right_layout.addWidget(self.btn_analyse)

        # 2. Toggle Buttons
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
        
        # 3. Stacked Widget
        self.right_stack = QStackedWidget()
        
        self.chat_panel = AIChatPanel()
        self.right_stack.addWidget(self.chat_panel)
        
        self.legend_scroll = QScrollArea()
        self.legend_scroll.setWidgetResizable(True)
        self.legend = LegendWidget()
        # Connect the OCR Signals
        self.legend.ocrRequested.connect(self.on_ocr_requested)
        self.legend.ocrLabelsToggled.connect(self.on_toggle_ocr_labels)
        self.legend.roomsToggled.connect(self.on_toggle_rooms)
        self.legend.itemsToggled.connect(self.on_toggle_items)
        
        self.legend_scroll.setWidget(self.legend)
        self.right_stack.addWidget(self.legend_scroll)
        
        self.right_layout.addWidget(self.right_stack)
        
        self.btn_show_chat.clicked.connect(lambda: self.right_stack.setCurrentIndex(0))
        self.btn_show_legend.clicked.connect(lambda: self.right_stack.setCurrentIndex(1))

        self.toggle_container.hide()

        # Controls Left Side
        self.controls = QWidget() 
        control_layout = QVBoxLayout(self.controls)
        
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

        self.btn_text = QPushButton()
        self.btn_text.setCheckable(True)
        self.btn_text.setIcon(qta.icon('fa5s.font'))
        self.btn_text.setToolTip("Add Text Label")
        self.btn_text.clicked.connect(self.toggle_text_mode)
        self.btn_text.setEnabled(False)

        self.btn_3d = QPushButton()
        self.btn_3d.setIcon(qta.icon('fa5s.cube'))
        self.btn_3d.setToolTip("Generate 3D Model")
        self.btn_3d.clicked.connect(self.on_generate_3d_clicked)
        self.btn_3d.setEnabled(False)

        self.btn_db = QPushButton()
        self.btn_db.setIcon(qta.icon('fa5s.database'))
        self.btn_db.setToolTip("Material & BOQ Database")
        self.btn_db.clicked.connect(self.open_database_editor)

        control_layout.addSpacing(10)
        control_layout.addWidget(self.btn_measure)
        control_layout.addWidget(self.btn_mode_toggle)
        control_layout.addWidget(self.btn_text)
        control_layout.addWidget(self.btn_3d)
        control_layout.addWidget(self.btn_db)
        
        # Pushes everything above to the top, allowing the settings button to rest at the bottom
        control_layout.addStretch()

        # Add Settings Button at the bottom
        self.btn_settings = QPushButton()
        self.btn_settings.setIcon(qta.icon('fa5s.cog'))
        self.btn_settings.setToolTip("Settings / API Keys")
        self.btn_settings.clicked.connect(self.open_settings)
        control_layout.addWidget(self.btn_settings)

        # Status Label - Moved to StatusBar
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: gray; font-style: italic;")
        self.statusBar().addWidget(self.status_label)

        layout.addWidget(self.controls)
        layout.addWidget(self.thumbnail_scroll)
        layout.addWidget(self.center_stack) 
        layout.addWidget(self.right_sidebar)
        
        self.worker = None
        self.ocr_worker = None 
        
        self.update_tabs_visibility()
        self.right_sidebar.hide() 
        self.controls.hide() 

    def open_settings(self):
        """Opens the API Key Settings popup and refreshes ChatPanel on accept."""
        dlg = SettingsDialog(self)
        if dlg.exec() == QDialog.Accepted:
            # Refresh the Chat UI to show/hide the correct providers & custom models
            self.chat_panel.refresh_providers()

    def open_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open File", "", "PDF/Images (*.pdf *.png *.jpg)")
        if path:
            if path.lower().endswith('.pdf'): self.load_pdf(path)
            else: self.load_single_image(path)
            self.center_stack.setCurrentIndex(1) 
            self.update_tabs_visibility()

    def load_recent_files(self):
        while self.recent_files_layout.count():
            child = self.recent_files_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
                
        recent_files = database.get_recent_files()
        
        if not recent_files:
            lbl = QLabel("No recent files.")
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setStyleSheet("color: #aaaaaa;")
            self.recent_files_layout.addWidget(lbl)
            return

        for file_id, file_path in recent_files:
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(5, 2, 5, 2)
            
            filename = os.path.basename(file_path)
            
            btn_file = QPushButton(filename)
            btn_file.setToolTip(file_path)
            btn_file.setStyleSheet("""
                QPushButton { text-align: left; background: transparent; border: none; color: #dddddd; font-size: 14px; }
                QPushButton:hover { color: #fb9a44; } 
            """)
            btn_file.setCursor(Qt.PointingHandCursor)
            btn_file.clicked.connect(lambda checked, p=file_path: self.open_specific_file(p))
            
            btn_del = QPushButton()
            btn_del.setIcon(qta.icon('fa5s.times', color='#d9534f')) 
            btn_del.setFixedSize(24, 24)
            btn_del.setCursor(Qt.PointingHandCursor)
            btn_del.setStyleSheet("border: none; background: transparent;")
            btn_del.clicked.connect(lambda checked, fid=file_id: self.remove_recent_file(fid))
            
            row_layout.addWidget(btn_file)
            row_layout.addWidget(btn_del)
            self.recent_files_layout.addWidget(row)

    def open_specific_file(self, path):
        if os.path.exists(path):
            if path.lower().endswith('.pdf'): 
                self.load_pdf(path)
            else: 
                self.load_single_image(path)
            self.center_stack.setCurrentIndex(1)
            self.update_tabs_visibility()
        else:
            QMessageBox.warning(self, "File Not Found", f"Could not locate:\n{path}")

    def remove_recent_file(self, file_id):
        database.delete_recent_file(file_id)
        self.load_recent_files() 

    def load_single_image(self, path):
        self.add_viewer_tab(path, "Image")
        database.add_recent_file(path)
        self.load_recent_files()

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
            self.ensure_plus_tab()

            database.add_recent_file(path)
            self.load_recent_files()
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
        self.ensure_plus_tab()
        self.update_toolbar_state() 

    def update_toolbar_state(self):
        viewer = self.tabs.currentWidget()
        
        if self.tabs.tabText(self.tabs.currentIndex()) == "+":
            self.btn_analyse.hide()
            self.toggle_container.hide()
            self.right_sidebar.hide() 
            self.controls.hide()
            return

        self.thumbnail_scroll.takeWidget()
        if isinstance(viewer, DocumentViewer):
            self.setWindowTitle(f"PDF BOQ Viewer - {viewer.file_path}")
            self.right_sidebar.show()
            self.controls.show()
        else:
            self.setWindowTitle("PDF BOQ Viewer")
            self.right_sidebar.hide() 
            self.controls.hide()

        if isinstance(viewer, DocumentViewer) and viewer.is_pdf_browser and viewer.thumbnail_widget:
            self.thumbnail_scroll.setWidget(viewer.thumbnail_widget)
            self.thumbnail_scroll.show()
        else:
            self.thumbnail_scroll.hide()

        if isinstance(viewer, DocumentViewer):
            self.btn_measure.setEnabled(True)
            self.btn_mode_toggle.setEnabled(True)
            self.btn_text.setEnabled(True)

            self.legend.btn_ocr.blockSignals(True)
            self.legend.btn_ocr.setChecked(viewer.show_ocr)
            if not viewer.has_ocr_data:
                self.legend.btn_ocr.setChecked(False)
            self.legend.btn_ocr.blockSignals(False)
            
            self.legend.btn_toggle_rooms.blockSignals(True)
            self.legend.btn_toggle_items.blockSignals(True)
            self.legend.btn_toggle_rooms.setChecked(viewer.show_rooms)
            self.legend.btn_toggle_items.setChecked(viewer.show_items)
            self.legend.btn_toggle_rooms.blockSignals(False)
            self.legend.btn_toggle_items.blockSignals(False)

            self.chat_panel.set_active_viewer(viewer)

            if viewer.has_analysis_data and viewer.json_data_path:
                import json
                try:
                    with open(viewer.json_data_path, 'r') as f:
                        boq_data = json.load(f)
                    self.legend.refresh_legend(boq_data)
                    self.legend.set_visibility(viewer.show_rooms, viewer.show_items)
                except: pass 
                
                self.btn_analyse.hide()
                self.toggle_container.show()
                self.status_label.setText("Analysis Ready")
                self.btn_3d.setEnabled(True)
            else:
                self.legend.refresh_legend({"rooms": [], "icons": []})
                self.legend.set_visibility(False, False)
                
                self.btn_analyse.show()
                self.btn_analyse.setEnabled(True)
                self.toggle_container.hide()
                self.right_stack.setCurrentIndex(1) 
                self.status_label.setText("Ready to Analyze")
                self.btn_3d.setEnabled(False)
            
            if viewer.pixel_to_unit_ratio is not None:
                self.btn_measure.setToolTip("Re-calibrate Scale")
                self.btn_measure.setIcon(qta.icon('fa5s.ruler-vertical'))
            elif len(viewer.current_path) > 0 or len(viewer.completed_shapes) > 0:
                self.btn_measure.setToolTip("Re-measure Area")
                self.btn_measure.setIcon(qta.icon('fa5s.ruler-combined', color='orange'))
            else:
                self.btn_measure.setToolTip("Measure Area")
                self.btn_measure.setIcon(qta.icon('fa5s.ruler-combined'))
            
            if viewer.mode == "measure":
                self.btn_mode_toggle.setChecked(True)
                self.btn_mode_toggle.setToolTip("Mode: Measurer")
                self.btn_mode_toggle.setIcon(qta.icon('fa5s.crosshairs'))
            else:
                self.btn_mode_toggle.setChecked(False)
                self.btn_mode_toggle.setToolTip("Mode: Grabber")
                self.btn_mode_toggle.setIcon(qta.icon('fa5s.hand-rock'))
            
            if viewer.mode == "text":
                self.btn_text.setChecked(True)
            else:
                self.btn_text.setChecked(False)
            
        else:
            self.legend.set_visibility(False, False)
            self.status_label.setText("")
            self.btn_measure.setEnabled(False)
            self.btn_mode_toggle.setEnabled(False)
            self.btn_text.setEnabled(False)
            self.thumbnail_scroll.hide()
            
            self.btn_analyse.hide()
            self.toggle_container.hide()
            self.chat_panel.set_active_viewer(None)

    def on_tab_changed(self, index):
        if index == -1: return
        
        if self.tabs.tabText(index) == "+":
            self.open_file()
            if self.tabs.count() > 1 and self.tabs.currentWidget() == self.tabs.widget(index):
                 self.tabs.setCurrentIndex(self.tabs.count() - 2)
        else:
            self.update_toolbar_state()

    def ensure_plus_tab(self):
        for i in range(self.tabs.count()):
            if self.tabs.tabText(i) == "+":
                self.tabs.removeTab(i)
                break
        
        if self.tabs.count() > 0: 
            plus_widget = QWidget()
            index = self.tabs.addTab(plus_widget, "+")
            self.tabs.tabBar().setTabButton(index, QTabBar.RightSide, None)

    def update_tabs_visibility(self):
        count = self.tabs.count()
        real_tab_count = sum(1 for i in range(count) if self.tabs.tabText(i) != "+")
                
        if real_tab_count == 0:
            self.center_stack.setCurrentIndex(0) 
            for i in range(self.tabs.count()):
                if self.tabs.tabText(i) == "+":
                    self.tabs.removeTab(i)
        else:
            self.center_stack.setCurrentIndex(1) 
            self.ensure_plus_tab()

    def close_tab(self, index):
        if self.tabs.tabText(index) == "+": return 
        self.tabs.removeTab(index)
        self.update_tabs_visibility()
        self.update_toolbar_state()

    def on_ocr_requested(self, is_checked):
        viewer = self.tabs.currentWidget()
        if not isinstance(viewer, DocumentViewer): return

        if viewer.has_ocr_data:
            viewer.toggle_ocr(is_checked)
            return

        if is_checked:
            self.status_label.setText("Running OCR (Scanning 4 angles)...")
            self.legend.btn_ocr.setEnabled(False) 
            self.legend.show_progress() 
            
            self.ocr_worker = OCRWorker(viewer.file_path)
            self.ocr_worker.finished.connect(self.on_ocr_finished)
            self.ocr_worker.error.connect(self.on_ocr_error)
            self.ocr_worker.start()
        else:
            viewer.toggle_ocr(False)

    @Slot(str, list)
    def on_ocr_finished(self, layer_path, data_list):
        viewer = self.tabs.currentWidget()
        self.legend.hide_progress() 
        
        if isinstance(viewer, DocumentViewer):
            viewer.set_ocr_layer(layer_path)
            self.temp_files.append(layer_path)
            
            if viewer.has_analysis_data and viewer.boq_data:
                if hasattr(viewer, 'get_manual_text_data'):
                     manual_data = viewer.get_manual_text_data()
                     if manual_data:
                         data_list.extend(manual_data)

                updated_boq = self.match_text_to_rooms(viewer.boq_data, data_list)
                viewer.boq_data = updated_boq
                
                if viewer.json_data_path:
                    import json
                    try:
                        with open(viewer.json_data_path, 'w') as f:
                            json.dump(updated_boq, f, indent=4)
                    except Exception as e:
                        print(f"Error saving matching JSON: {e}")
                
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

        rooms_with_poly = []
        for i, room in enumerate(boq_data.get('rooms', [])):
            pts = room.get('points', [])
            if len(pts) >= 3:
                try:
                    poly = ShapelyPolygon(pts)
                    rooms_with_poly.append((i, poly))
                except: pass
        
        for item in ocr_results:
            rect = item.get('rect') 
            if not rect: continue
            cx = (rect[0] + rect[2]) / 2
            cy = (rect[1] + rect[3]) / 2
            p = Point(cx, cy)
            
            for idx, poly in rooms_with_poly:
                if poly.contains(p):
                    text = item.get('text', '').strip()
                    import re
                    if re.match(r'^\d+(\.\d+)?$', text):
                        continue
                        
                    if text == "JM":
                        text = "WC"
                        
                    current_ocr = boq_data['rooms'][idx].get('ocr_text', '')
                    
                    if current_ocr:
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
        
        self.legend.refresh_legend(boq)
        viewer.update_view()

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
            self.btn_mode_toggle.setIcon(qta.icon('fa5s.crosshairs'))
            self.btn_mode_toggle.setToolTip("Mode: Measurer")
        else:
            viewer.set_mode("grab")
            self.btn_mode_toggle.setIcon(qta.icon('fa5s.hand-rock'))
            self.btn_mode_toggle.setToolTip("Mode: Grabber")

        self.btn_text.setChecked(False)

    def toggle_text_mode(self):
        viewer = self.tabs.currentWidget()
        if not viewer: return
        
        if self.btn_text.isChecked():
            viewer.set_mode("text")
            self.btn_mode_toggle.setChecked(False)
        else:
            viewer.set_mode("grab")
            self.btn_mode_toggle.setChecked(False)
            self.btn_mode_toggle.setIcon(qta.icon('fa5s.hand-rock'))
            self.btn_mode_toggle.setToolTip("Mode: Grabber")

    def on_toggle_rooms(self, is_checked):
        viewer = self.tabs.currentWidget()
        if isinstance(viewer, DocumentViewer) and viewer.has_analysis_data:
            viewer.toggle_layers(is_checked, viewer.show_items)
            self.legend.set_visibility(is_checked, viewer.show_items)

    def on_toggle_items(self, is_checked):
        viewer = self.tabs.currentWidget()
        if isinstance(viewer, DocumentViewer) and viewer.has_analysis_data:
            viewer.toggle_layers(viewer.show_rooms, is_checked)
            self.legend.set_visibility(viewer.show_rooms, is_checked)

    def start_worker_on_current_tab(self):
        viewer = self.tabs.currentWidget()
        if not isinstance(viewer, DocumentViewer): return
        
        self.btn_analyse.setEnabled(False)
        self.btn_analyse.setText("Analysing...")
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

            rooms_checked = True 
            items_checked = True 
            viewer.toggle_layers(rooms_checked, items_checked)
            self.legend.set_visibility(rooms_checked, items_checked)
            
            self.legend.btn_toggle_rooms.blockSignals(True)
            self.legend.btn_toggle_items.blockSignals(True)
            self.legend.btn_toggle_rooms.setChecked(rooms_checked)
            self.legend.btn_toggle_items.setChecked(items_checked)
            self.legend.btn_toggle_rooms.blockSignals(False)
            self.legend.btn_toggle_items.blockSignals(False)
            self.temp_files.extend([room_path, item_path, json_path])
            
            self.toggle_container.show()
            self.right_stack.setCurrentIndex(1) 
            self.btn_show_legend.setChecked(True)
            self.btn_analyse.hide()
            self.btn_analyse.setText("Analyse") 
            self.btn_analyse.setEnabled(True)

        self.status_label.setText(f"Analysis Complete.")

    @Slot(str)
    def on_analysis_error(self, err_msg):
        self.btn_analyse.setEnabled(True)
        self.btn_analyse.setText("Analyse")
        self.status_label.setText("Analysis Failed")
        QMessageBox.critical(self, "Analysis Error", err_msg)

    def closeEvent(self, event):
        for f in self.temp_files:
            if os.path.exists(f):
                try: os.remove(f)
                except: pass
        super().closeEvent(event)

    def on_generate_3d_clicked(self):
        viewer = self.tabs.currentWidget()
        if not isinstance(viewer, DocumentViewer) or not viewer.has_analysis_data:
            return

        default_height = 2.4
        height, ok = QInputDialog.getDouble(
            self, 
            "Wall Height", 
            "Enter wall height (in real-world units):", 
            default_height, 0.1, 100.0, 2
        )
        
        if ok:
            viewer_3d = ThreeDViewer(viewer.boq_data, height, viewer.pixel_to_unit_ratio)
            self.tabs.addTab(viewer_3d, f"3D View: {os.path.basename(viewer.file_path)}")
            self.tabs.setCurrentWidget(viewer_3d)

    def open_database_editor(self):
        database.init_db()
        dlg = DatabaseEditorDialog(parent=self)
        dlg.exec()