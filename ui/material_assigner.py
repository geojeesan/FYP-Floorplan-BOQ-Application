import sqlite3
import json
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, 
    QPushButton, QMessageBox, QWidget, QFormLayout
)
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtCore import Qt, QSize

DB_NAME = "boq_materials.db"

class MaterialAssignmentDialog(QDialog):
    def __init__(self, target_label, item_type, viewer, parent=None):
        super().__init__(parent)
        self.target_label = target_label
        self.item_type = item_type # 'room', 'structure', or 'icon'
        self.viewer = viewer
        
        self.setWindowTitle(f"Assign Materials: {target_label}")
        self.setMinimumWidth(400)
        
        self.layout = QVBoxLayout(self)
        self.form_layout = QFormLayout()
        self.layout.addLayout(self.form_layout)
        
        self.combo_boxes = {} # To keep track of selections
        
        # Determine which categories (database tables) to show based on the item
        self.categories = self._determine_categories()
        
        # Build the UI
        self._build_dropdowns()
        
        # Buttons
        btn_layout = QHBoxLayout()
        btn_save = QPushButton("Save Assignments")
        btn_save.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold; padding: 6px;")
        btn_save.clicked.connect(self.save_assignments)
        
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        
        btn_layout.addStretch()
        btn_layout.addWidget(btn_cancel)
        btn_layout.addWidget(btn_save)
        self.layout.addLayout(btn_layout)
        
        # Pre-load existing selections from JSON if they exist
        self._load_existing_assignments()

    def _determine_categories(self):
        """Map the UI item to the corresponding database tables."""
        if self.item_type == 'room':
            # Rooms typically need Floor and Wall materials
            return ["Floors", "Walls"]
            
        elif self.item_type == 'structure':
            if self.target_label == "Wall": return ["Walls"]
            return ["Fixtures"]
            
        else: # Icons / Items
            # Exact mapping or pluralized mapping based on your DB schema
            mapping = {
                "Door": "Doors",
                "Window": "Windows",
                "Electrical Appliance": "Electrical Appliances",
                "Closet": "Closet",
                "Toilet": "Toilet",
                "Sink": "Sink",
                "Sauna Bench": "Sauna Bench",
                "Fire Place": "Fire Place",
                "Bathtub": "Bathtub",
                "Chimney": "Chimney"
            }
            return [mapping.get(self.target_label, "Fixtures")]

    def _build_dropdowns(self):
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        for category in self.categories:
            combo = QComboBox()
            combo.setIconSize(QSize(40, 40)) # Size for the image preview
            combo.addItem("--- Select Material ---", userData=None)
            
            try:
                # Query the database for items in this category
                cursor.execute(f'SELECT id, item_name, cost, image FROM "{category}"')
                rows = cursor.fetchall()
                
                for row_id, name, cost, image_blob in rows:
                    display_text = f"[ID: {row_id}] {name} - £{cost:.2f}"
                    
                    # Process the image BLOB
                    icon = QIcon()
                    if image_blob:
                        pixmap = QPixmap()
                        pixmap.loadFromData(image_blob)
                        if not pixmap.isNull():
                            icon = QIcon(pixmap)
                            
                    combo.addItem(icon, display_text, userData={"id": row_id, "name": name, "cost": cost, "table": category})
            except sqlite3.Error as e:
                print(f"DB Error fetching {category}: {e}")
                
            self.combo_boxes[category] = combo
            self.form_layout.addRow(f"{category}:", combo)
            
        conn.close()

    def _load_existing_assignments(self):
        """Looks into the viewer's boq_data to set the dropdowns if already assigned."""
        if not self.viewer or not self.viewer.boq_data: return
        
        # Search for the first instance of this label to grab its current materials
        target_list = self.viewer.boq_data.get('rooms', []) if self.item_type in ['room', 'structure'] else self.viewer.boq_data.get('icons', [])
        
        for item in target_list:
            if item.get('label') == self.target_label:
                materials = item.get('materials', {})
                for category, combo in self.combo_boxes.items():
                    if category in materials:
                        mat_id = materials[category].get('id')
                        # Find the index in the combobox matching this ID
                        for i in range(combo.count()):
                            data = combo.itemData(i)
                            if data and data.get('id') == mat_id:
                                combo.setCurrentIndex(i)
                                break
                break # Only need to read from the first match

    def save_assignments(self):
        if not self.viewer or not self.viewer.boq_data:
            QMessageBox.warning(self, "Error", "No active document data found.")
            return
            
        # Collect selected data
        new_materials = {}
        for category, combo in self.combo_boxes.items():
            data = combo.currentData()
            if data:
                new_materials[category] = data
                
        # Apply to all instances of this label in the JSON data
        target_list = self.viewer.boq_data.get('rooms', []) if self.item_type in ['room', 'structure'] else self.viewer.boq_data.get('icons', [])
        
        for item in target_list:
            if item.get('label') == self.target_label:
                item['materials'] = new_materials
                
        # Save changes to the JSON file
        if self.viewer.json_data_path:
            try:
                with open(self.viewer.json_data_path, 'w') as f:
                    json.dump(self.viewer.boq_data, f, indent=4)
                QMessageBox.information(self, "Success", "Materials assigned and saved successfully.")
                self.accept()
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to save JSON:\n{e}")
        else:
            QMessageBox.warning(self, "Warning", "Could not find JSON file path to save.")
            self.reject()