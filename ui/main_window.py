import os
import sys
import fitz  # PyMuPDF
import random
import shutil
from dotenv import load_dotenv, set_key
import ctypes

from PySide6.QtWidgets import (
    QInputDialog, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QScrollArea, QLabel, QFileDialog, QPushButton, QMessageBox,
    QStackedWidget, QButtonGroup, QTabBar, QDialog, QFormLayout, QLineEdit, 
    QDialogButtonBox, QCheckBox, QToolButton, QButtonGroup
)
from PySide6.QtGui import QPixmap, QImage, QIcon, QPainter, QPainterPath
import qtawesome as qta
from PySide6.QtCore import Qt, Slot, QTimer

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


class MARGINS(ctypes.Structure):
    _fields_ = [("cxLeftWidth", ctypes.c_int),
                ("cxRightWidth", ctypes.c_int),
                ("cyTopHeight", ctypes.c_int),
                ("cyBottomHeight", ctypes.c_int)]


class StartScreenWidget(QWidget):
    def __init__(self, main_app, parent=None):
        super().__init__(parent)
        self.main_app = main_app
        
        start_layout = QVBoxLayout(self)
        start_layout.setAlignment(Qt.AlignCenter)
        start_layout.setSpacing(15)
        
        # Logo and Open Button Container
        logo_button_container = QWidget()
        logo_button_layout = QHBoxLayout(logo_button_container)
        logo_button_layout.setContentsMargins(0, 0, 0, 0)
        logo_button_layout.setSpacing(20)

        button_recent_container = QWidget()
        button_recent_layout = QVBoxLayout(button_recent_container)
        button_recent_layout.setContentsMargins(0, 0, 0, 0)
        button_recent_layout.setSpacing(10)
        
        # Logo
        self.logo_label = QLabel()
        logo_pixmap = QPixmap("resources/logo.png")
        if not logo_pixmap.isNull():
            scaled_logo = logo_pixmap.scaled(300, 300, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.logo_label.setPixmap(scaled_logo)
            self.logo_label.setAlignment(Qt.AlignCenter)
        
        logo_button_layout.addWidget(self.logo_label)
        
        # Big Open Button
        self.btn_big_open = QPushButton("Open PDF / Image")
        self.btn_big_open.setFixedSize(400, 60)
        self.btn_big_open.setStyleSheet("""
        QPushButton {
                background-color: #fb9a44; 
                color: white; 
                font-size: 20px; 
                padding: 10px; 
                border-radius: 10px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #e08c3a; }
        """)
        self.btn_big_open.setCursor(Qt.PointingHandCursor)
        self.btn_big_open.clicked.connect(self.main_app.open_file)
        button_recent_layout.addWidget(self.btn_big_open)
        
        # Recent Files Section
        recent_label = QLabel("Recent Files")
        recent_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #eeeeee;")
        button_recent_layout.addWidget(recent_label, alignment=Qt.AlignCenter)
        
        self.recent_scroll = QScrollArea()
        self.recent_scroll.setObjectName("recentFilesScrollArea")
        self.recent_scroll.setWidgetResizable(True)
        self.recent_scroll.setFixedSize(400, 200) 
        
        self.recent_container = QWidget()
        self.recent_container.setObjectName("recentFilesContainer")
        self.recent_files_layout = QVBoxLayout(self.recent_container)
        self.recent_files_layout.setAlignment(Qt.AlignTop)
        self.recent_scroll.setWidget(self.recent_container)
        
        button_recent_layout.addWidget(self.recent_scroll, alignment=Qt.AlignCenter)
        logo_button_layout.addWidget(button_recent_container)
        start_layout.addWidget(logo_button_container, alignment=Qt.AlignCenter)
        
        self.load_recent_files()

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
            btn_file.clicked.connect(lambda checked, p=file_path: self.main_app.open_specific_file(p))
            
            btn_del = QPushButton()
            btn_del.setIcon(qta.icon('fa5s.times', color='#d9534f')) 
            btn_del.setFixedSize(24, 24)
            btn_del.setCursor(Qt.PointingHandCursor)
            btn_del.setStyleSheet("border: none; background: transparent;")
            btn_del.clicked.connect(lambda checked, fid=file_id: self.main_app.remove_recent_file(fid))
            
            row_layout.addWidget(btn_file)
            row_layout.addWidget(btn_del)
            self.recent_files_layout.addWidget(row)


class PDFViewerApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PDF BOQ Viewer")
        self.setWindowIcon(QIcon("resources/logo.png"))
        self.resize(1400, 900)
        self.current_pdf_path = None
        self.temp_files = [] 
        self.tab_widgets = [] # Maintains 1:1 mapping with the center_stack

        self.apply_mica()

        # Main Layout
        main_widget = QWidget()
        main_widget.setObjectName("mainContainer")
        self.setCentralWidget(main_widget)
        
        self.main_layout = QVBoxLayout(main_widget)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        # Top Bar Container (holds Tabs + Plus Button)
        self.top_bar_widget = QWidget()
        self.top_bar_layout = QHBoxLayout(self.top_bar_widget)
        self.top_bar_layout.setContentsMargins(0, 0, 0, 0)
        self.top_bar_layout.setSpacing(2)

        # Tab Bar (Always Visible at Top)
        self.tab_bar = QTabBar()
        self.tab_bar.setDrawBase(False)
        self.tab_bar.setStyleSheet("""
            QTabBar::tab {
                background: rgba(255, 255, 255, 0.05);
                color: #dddddd;
                padding: 8px 15px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                margin-right: 2px;
                min-width: 120px;
            }
            QTabBar::tab:selected {
                background: rgba(255, 255, 255, 0.15);
                color: white;
            }
            QTabBar::tab:hover {
                background: rgba(255, 255, 255, 0.1);
            }
        """)
        self.tab_bar.currentChanged.connect(self.on_tab_changed)
        
        # New Tab Button (Square)
        self.btn_new_tab = QPushButton()
        self.btn_new_tab.setIcon(qta.icon('fa5s.plus', color='#dddddd'))
        self.btn_new_tab.setFixedSize(42, 42) # Matches general tab height
        self.btn_new_tab.setCursor(Qt.PointingHandCursor)
        self.btn_new_tab.setStyleSheet("""
            QPushButton {
                background: rgba(255, 255, 255, 0.05);
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                border-bottom-left-radius: 0px;
                border-bottom-right-radius: 0px;
                margin-top: 2px;
            }
            QPushButton:hover {
                background: rgba(255, 255, 255, 0.15);
            }
        """)
        self.btn_new_tab.clicked.connect(lambda: self.add_new_tab(StartScreenWidget(self), "New Tab"))

        self.top_bar_layout.addWidget(self.tab_bar)
        self.top_bar_layout.addWidget(self.btn_new_tab, alignment=Qt.AlignBottom)
        self.top_bar_layout.addStretch() # Pushes tabs & button to the left
        
        self.main_layout.addWidget(self.top_bar_widget)

        # Content Layout
        self.content_widget = QWidget()
        self.content_layout = QHBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.addWidget(self.content_widget, 1)

        # Sidebar (Initially Empty)
        self.thumbnail_scroll = QScrollArea()
        self.thumbnail_scroll.setWidgetResizable(True)
        self.thumbnail_scroll.setFixedWidth(150)
        
        # Center Stack (holds DocumentViewers & StartScreens)
        self.center_stack = QStackedWidget()

        # Initialize DB
        database.init_db()

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

        self.btn_toggle_thumbnails = QPushButton()
        self.btn_toggle_thumbnails.setCheckable(True)
        self.btn_toggle_thumbnails.setChecked(True)  # Visible by default for PDFs
        self.btn_toggle_thumbnails.setIcon(qta.icon('fa5s.th-list'))
        self.btn_toggle_thumbnails.setToolTip("Toggle Thumbnails")
        self.btn_toggle_thumbnails.clicked.connect(self.toggle_thumbnails)
        self.btn_toggle_thumbnails.hide()
        
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
        control_layout.addWidget(self.btn_toggle_thumbnails)
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

        self.content_layout.addWidget(self.controls)
        self.content_layout.addWidget(self.thumbnail_scroll)
        self.content_layout.addWidget(self.center_stack, 1) 
        self.content_layout.addWidget(self.right_sidebar)
        
        self.worker = None
        self.ocr_worker = None 

        self.right_sidebar.hide() 
        self.controls.hide()

        # Create Initial Tab
        self.add_new_tab(StartScreenWidget(self), "New Tab")

    def apply_mica(self):
        if os.name == 'nt':
            try:
                hwnd = int(self.winId())
                # Enable Dark Mode (20) & MicaAlt (38)
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, 20, ctypes.byref(ctypes.c_int(1)), ctypes.sizeof(ctypes.c_int)
                )
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, 38, ctypes.byref(ctypes.c_int(2)), ctypes.sizeof(ctypes.c_int)
                )
                # Tell Windows to draw the Mica effect into our transparent window
                margins = MARGINS(-1, -1, -1, -1)
                ctypes.windll.dwmapi.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(margins))
                
            except Exception as e:
                print(f"Mica not supported on this OS version: {e}")

            self.setStyleSheet("QMainWindow { background: transparent; }")

    def open_settings(self):
        dlg = SettingsDialog(self)
        if dlg.exec() == QDialog.Accepted:
            self.chat_panel.refresh_providers()

    def current_widget(self):
        """Helper to get current active widget based on TabBar index."""
        idx = self.tab_bar.currentIndex()
        if 0 <= idx < len(self.tab_widgets):
            return self.tab_widgets[idx]
        return None

    def refresh_all_start_screens(self):
        for w in self.tab_widgets:
            if isinstance(w, StartScreenWidget):
                w.load_recent_files()

    def add_new_tab(self, widget, title="New Tab"):
        self.tab_widgets.append(widget)
        self.center_stack.addWidget(widget)
        
        index = len(self.tab_widgets) - 1
        self.tab_bar.addTab(title)
        
        # Wrapping the close button in a layout container to guarantee margins!
        close_container = QWidget()
        close_layout = QHBoxLayout(close_container)
        close_layout.setContentsMargins(0, 0, 5, 0) # 5px right margin
        close_layout.setSpacing(0)
        
        close_btn = QPushButton()
        close_btn.setIcon(qta.icon('fa5s.times', color='#bbbbbb'))
        close_btn.setFixedSize(20, 20)
        close_btn.setStyleSheet("""
            QPushButton { background: transparent; border: none; } 
            QPushButton:hover { background-color: rgba(255, 255, 255, 10); color: white; border-radius: 4px; }
        """)
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.clicked.connect(lambda _, w=widget: self.close_tab_by_widget(w))
        
        close_layout.addWidget(close_btn)
        self.tab_bar.setTabButton(index, QTabBar.RightSide, close_container)
        
        self.tab_bar.setCurrentIndex(index)
        self.update_toolbar_state()
        return index

    def replace_or_add_tab(self, widget, title):
        """Replaces current tab if it's a StartScreen, otherwise adds a new tab."""
        current_idx = self.tab_bar.currentIndex()
        if 0 <= current_idx < len(self.tab_widgets):
            current_widget = self.tab_widgets[current_idx]
            if isinstance(current_widget, StartScreenWidget):
                # Replace logic
                self.center_stack.removeWidget(current_widget)
                current_widget.deleteLater()
                
                self.tab_widgets[current_idx] = widget
                self.center_stack.insertWidget(current_idx, widget)
                self.tab_bar.setTabText(current_idx, title)
                self.center_stack.setCurrentIndex(current_idx)
                
                # Update close button reference 
                close_container = self.tab_bar.tabButton(current_idx, QTabBar.RightSide)
                if close_container:
                    # Retrieve the actual button from the layout container
                    close_btn = close_container.layout().itemAt(0).widget()
                    close_btn.clicked.disconnect()
                    close_btn.clicked.connect(lambda _, w=widget: self.close_tab_by_widget(w))
                    
                self.update_toolbar_state()
                return
        
        self.add_new_tab(widget, title)

    def close_tab_by_widget(self, widget):
        if widget in self.tab_widgets:
            idx = self.tab_widgets.index(widget)
            self.close_tab(idx)

    def close_tab(self, index):
        if index < 0 or index >= len(self.tab_widgets): return
        
        widget = self.tab_widgets.pop(index)
        self.tab_bar.removeTab(index)
        self.center_stack.removeWidget(widget)
        widget.deleteLater()
        
        # If no tabs are left, spawn a new Start Screen
        if len(self.tab_widgets) == 0:
            self.add_new_tab(StartScreenWidget(self), "New Tab")
            
        self.update_toolbar_state()

    def open_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open File", "", "PDF/Images (*.pdf *.png *.jpg)")
        if path:
            if path.lower().endswith('.pdf'): self.load_pdf(path)
            else: self.load_single_image(path)

    def open_specific_file(self, path):
        if os.path.exists(path):
            if path.lower().endswith('.pdf'): 
                self.load_pdf(path)
            else: 
                self.load_single_image(path)
        else:
            QMessageBox.warning(self, "File Not Found", f"Could not locate:\n{path}")

    def remove_recent_file(self, file_id):
        database.delete_recent_file(file_id)
        self.refresh_all_start_screens()

    def load_single_image(self, path):
        viewer = DocumentViewer(path)
        self.replace_or_add_tab(viewer, os.path.basename(path))
        database.add_recent_file(path)
        self.refresh_all_start_screens()

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
            thumbnail_layout.setContentsMargins(5, 5, 5, 5)
            viewer.thumbnail_widget = thumbnail_container

            viewer.thumbnail_group = QButtonGroup(thumbnail_container)
            viewer.thumbnail_group.setExclusive(True)

            for i in range(len(doc)):
                page = doc.load_page(i)
                target_width = 140.0
                scale = target_width / page.rect.width

                thumb_pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale))
                img_data = thumb_pix.tobytes("ppm")
                qpix = QPixmap.fromImage(QImage.fromData(img_data))
                
                rounded_pixmap = QPixmap(qpix.size())
                rounded_pixmap.fill(Qt.transparent)
                painter = QPainter(rounded_pixmap)
                painter.setRenderHint(QPainter.Antialiasing)
                
                clip_path = QPainterPath()
                clip_path.addRoundedRect(0, 0, qpix.width(), qpix.height(), 8, 8) # 8px border radius
                painter.setClipPath(clip_path)
                painter.drawPixmap(0, 0, qpix)
                painter.end()

                btn = QToolButton()
                btn.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
                btn.setText(f"Page {i+1}")
                btn.setIcon(QIcon(rounded_pixmap))
                btn.setIconSize(qpix.size())
                
                # Height is image height + roughly 25px for the text
                btn.setFixedSize(qpix.width(), qpix.height() + 25) 
                
                # Enable the active/checked state
                btn.setCheckable(True)
                if i == viewer.current_page_num:
                    btn.setChecked(True)

                btn.setStyleSheet("""
                    QToolButton {
                        background-color: transparent;
                        border: 1px solid transparent;
                        border-radius: 8px;
                        color: #dddddd;
                        font-size: 12px;
                        margin-bottom: 5px;
                    }
                    QToolButton:hover { 
                        background-color: rgba(255, 255, 255, 20); 
                    }
                    QToolButton:checked {
                        background-color: rgba(255, 255, 255, 40);
                        border: 3px solid #fb9a44; /* Brand accent border */
                        color: #ffffff;
                        font-weight: bold;
                    }
                """)
                
                btn.clicked.connect(lambda checked, v=viewer, p=i: self.navigate_pdf_page(v, p))
                
                viewer.thumbnail_group.addButton(btn, i)
                thumbnail_layout.addWidget(btn)

            self.replace_or_add_tab(viewer, os.path.basename(path))
            database.add_recent_file(path)
            self.refresh_all_start_screens()
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
            viewer.thumbnail_group.button(page_num).setChecked(True)
            self.update_toolbar_state()
        except Exception as e:
            print(f"Error navigating PDF: {e}")

    def update_toolbar_state(self):
        viewer = self.current_widget()
        if not viewer: return
        
        self.thumbnail_scroll.takeWidget()
        
        if isinstance(viewer, DocumentViewer):
            if viewer.is_pdf_browser:
                path = self.current_pdf_path
            else: 
                path = viewer.file_path
            for directory in ["Documents", "Downloads", "Desktop", "Pictures", "Videos"]:
                if directory in path:
                    path = path[path.index(directory):]
                    break
            titleformatted = path.replace("/", " › ").replace("\\", " › ")
            self.setWindowTitle(f"{titleformatted}")
            self.right_sidebar.show()
            self.controls.show()
        else:
            self.setWindowTitle("PDF BOQ Viewer")
            self.right_sidebar.hide() 
            self.controls.hide()

        if isinstance(viewer, DocumentViewer) and getattr(viewer, 'is_pdf_browser', False) and viewer.thumbnail_widget:
            self.thumbnail_scroll.setWidget(viewer.thumbnail_widget)
            self.btn_toggle_thumbnails.show()
            self.thumbnail_scroll.setVisible(self.btn_toggle_thumbnails.isChecked())
        else:
            self.thumbnail_scroll.hide()
            self.btn_toggle_thumbnails.hide()

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
            elif getattr(viewer, 'current_path', None) and len(viewer.current_path) > 0 or getattr(viewer, 'completed_shapes', None) and len(viewer.completed_shapes) > 0:
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

    def toggle_thumbnails(self):
        """Shows or hides the thumbnail scroll area based on the button's state."""
        if self.btn_toggle_thumbnails.isChecked():
            self.thumbnail_scroll.show()
        else:
            self.thumbnail_scroll.hide()

    def on_tab_changed(self, index):
        if index == -1: return
        self.center_stack.setCurrentIndex(index)
        self.update_toolbar_state()

    def on_ocr_requested(self, is_checked):
        viewer = self.current_widget()
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
        viewer = self.current_widget()
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
        viewer = self.current_widget()
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
        viewer = self.current_widget()
        if isinstance(viewer, DocumentViewer):
            if viewer.pixel_to_unit_ratio is not None:
                viewer.recalibrate() 
            else:
                viewer.set_mode("measure")
            self.update_toolbar_state()

    def toggle_interaction_mode(self):
        viewer = self.current_widget()
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
        viewer = self.current_widget()
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
        viewer = self.current_widget()
        if isinstance(viewer, DocumentViewer) and viewer.has_analysis_data:
            viewer.toggle_layers(is_checked, viewer.show_items)
            self.legend.set_visibility(is_checked, viewer.show_items)

    def on_toggle_items(self, is_checked):
        viewer = self.current_widget()
        if isinstance(viewer, DocumentViewer) and viewer.has_analysis_data:
            viewer.toggle_layers(viewer.show_rooms, is_checked)
            self.legend.set_visibility(viewer.show_rooms, is_checked)

    def start_worker_on_current_tab(self):
        viewer = self.current_widget()
        if not isinstance(viewer, DocumentViewer): return
        
        # FIX: If it's a PDF browser, extract the current page into a new dedicated tab for analysis
        if getattr(viewer, 'is_pdf_browser', False):
            current_temp = viewer.file_path
            new_path = current_temp.replace(".png", f"_analysis_{random.randint(0,10000)}.png")
            shutil.copy(current_temp, new_path)
            self.temp_files.append(new_path)
            
            new_viewer = DocumentViewer(new_path)
            page_name = f"Page {viewer.current_page_num + 1} Analysis"
            
            self.add_new_tab(new_viewer, page_name)
            viewer = new_viewer # Update reference so the worker acts on the new standalone tab
        
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
        viewer = self.current_widget()
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
        viewer = self.current_widget()
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
            self.add_new_tab(viewer_3d, f"3D View: {os.path.basename(viewer.file_path)}")
            QTimer.singleShot(1000, self.apply_mica)

    def open_database_editor(self):
        database.init_db()
        dlg = DatabaseEditorDialog(parent=self)
        dlg.exec()