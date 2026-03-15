import sqlite3
import json
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, 
    QPushButton, QMessageBox, QWidget, QFormLayout, QGroupBox, QScrollArea
)
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtCore import Qt, QSize
import os
import ctypes

DB_NAME = "boq_materials.db"

class MARGINS(ctypes.Structure):
    _fields_ = [("cxLeftWidth", ctypes.c_int),
                ("cxRightWidth", ctypes.c_int),
                ("cyTopHeight", ctypes.c_int),
                ("cyBottomHeight", ctypes.c_int)]

class MaterialAssignmentDialog(QDialog):
    def __init__(self, target_label, item_type, viewer, parent=None):
        super().__init__(parent)
        self.target_label = target_label
        self.item_type = item_type
        self.viewer = viewer
        
        self.setWindowTitle(f"Assign Materials: {target_label}")
        self.resize(500, 600)

        self.apply_mica()
        
        self.layout = QVBoxLayout(self)
        
        # Scroll Area for Multiple Instances
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll_widget = QWidget()
        self.scroll_layout = QVBoxLayout(self.scroll_widget)
        self.scroll.setWidget(self.scroll_widget)
        self.layout.addWidget(self.scroll)
        
        self.combo_boxes = {} # Format: { instance_idx: { category: combo_box } }
        self.categories = self._determine_categories()
        
        # Fetch all instances of this item from the active JSON data
        self.target_list = self.viewer.boq_data.get('rooms', []) if self.item_type in ['room', 'structure'] else self.viewer.boq_data.get('icons', [])
        self.instances = [item for item in self.target_list if item.get('label') == self.target_label]
        
        # Build UI
        self._build_ui_for_instances()
        
        # Buttons
        btn_layout = QHBoxLayout()
        btn_save = QPushButton("Save Assignments")
        btn_save.setStyleSheet("background-color: #fb9a44; color: white; font-weight: bold;")
        btn_save.clicked.connect(self.save_assignments)
        
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        
        btn_layout.addStretch()
        btn_layout.addWidget(btn_cancel)
        btn_layout.addWidget(btn_save)
        self.layout.addLayout(btn_layout)
        
        self._load_existing_assignments()

    def _determine_categories(self):
        if self.item_type == 'room':
            return ["Floors", "Walls"]
        elif self.item_type == 'structure':
            if self.target_label == "Wall": return ["Walls"]
            return ["Fixtures"]
        else:
            mapping = {
                "Door": "Doors", "Window": "Windows", "Electrical Appliance": "Electrical Appliances",
                "Closet": "Closet", "Toilet": "Toilet", "Sink": "Sink", "Sauna Bench": "Sauna Bench",
                "Fire Place": "Fire Place", "Bathtub": "Bathtub", "Chimney": "Chimney"
            }
            return [mapping.get(self.target_label, "Fixtures")]

    def _build_ui_for_instances(self):
        # Pre-fetch database items so we don't query the DB in a loop
        db_items = {}
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        for category in self.categories:
            db_items[category] = []
            try:
                cursor.execute(f'SELECT id, item_name, cost, image FROM "{category}"')
                db_items[category] = cursor.fetchall()
            except sqlite3.Error as e:
                print(f"DB Error fetching {category}: {e}")
        conn.close()

        # Build a group box for each instance found in the JSON
        for idx, inst in enumerate(self.instances):
            group = QGroupBox(f"{self.target_label} {idx + 1}")
            group.setStyleSheet("QGroupBox { font-weight: bold; background-color: rgba(255, 255, 255, 10); border-radius: 8px; margin-top: 10px; padding-top: 15px; }")
            form_layout = QFormLayout(group)
            
            self.combo_boxes[idx] = {}
            
            for category in self.categories:
                combo = QComboBox()
                combo.setIconSize(QSize(40, 40))
                combo.addItem(f"-- Select {category} ---", userData=None)
                
                for row_id, name, cost, image_blob in db_items[category]:
                    display_text = f"[ID: {row_id}] {name} - £{cost:.2f}"
                    icon = QIcon()
                    if image_blob:
                        pixmap = QPixmap()
                        pixmap.loadFromData(image_blob)
                        if not pixmap.isNull():
                            icon = QIcon(pixmap)
                    combo.addItem(icon, display_text, userData={"id": row_id, "name": name, "cost": cost, "table": category})
                
                self.combo_boxes[idx][category] = combo
                form_layout.addRow(f"{category}:", combo)
                
            self.scroll_layout.addWidget(group)
        self.scroll_layout.addStretch()

    def _load_existing_assignments(self):
        for idx, item in enumerate(self.instances):
            materials = item.get('materials', {})
            for category, combo in self.combo_boxes[idx].items():
                if category in materials:
                    mat_id = materials[category].get('id')
                    for i in range(combo.count()):
                        data = combo.itemData(i)
                        if data and data.get('id') == mat_id:
                            combo.setCurrentIndex(i)
                            break

    def save_assignments(self):
        if not self.viewer or not self.viewer.boq_data:
            return
            
        # 1. Apply selections back to the specific instances in memory
        for idx, item in enumerate(self.instances):
            new_materials = {}
            for category, combo in self.combo_boxes[idx].items():
                data = combo.currentData()
                if data:
                    new_materials[category] = data
            item['materials'] = new_materials
                
        # 2. Update temp JSON file ONLY if it exists (for fresh, unsaved analyses)
        if getattr(self.viewer, 'json_data_path', None):
            try:
                with open(self.viewer.json_data_path, 'w') as f:
                    json.dump(self.viewer.boq_data, f, indent=4)
            except Exception as e:
                print(f"Non-critical error saving temp JSON:\n{e}")

        # 3. Always succeed, close dialog, and remind user to save project
        QMessageBox.information(self, "Success", "Materials assigned successfully.\n\nNote: Remember to click 'Save Project' in the main window to write these changes to your .boq file.")
        self.accept()

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