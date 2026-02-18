from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
)
from PySide6.QtCore import Qt, Signal
import constants
from .viewer import DocumentViewer

class LegendWidget(QWidget):
    ocrRequested = Signal(bool) # Signal to Main Window: True=Show/Run, False=Hide

    def __init__(self):
        super().__init__()
        self.layout = QVBoxLayout(self)
        self.layout.setAlignment(Qt.AlignTop)
        
        self.room_colors, self.icon_colors = constants.get_class_colors()
        self.buttons = {} 
        
        # Containers
        self.room_container = QWidget()
        self.room_layout = QVBoxLayout(self.room_container)
        self.room_layout.setContentsMargins(0,0,0,0)
        
        self.structure_container = QWidget()
        self.structure_layout = QVBoxLayout(self.structure_container)
        self.structure_layout.setContentsMargins(0,0,0,0)

        self.item_container = QWidget()
        self.item_layout = QVBoxLayout(self.item_container)
        self.item_layout.setContentsMargins(0,0,0,0)

        self.layout.addWidget(QLabel("<b>Rooms</b>"))
        self.layout.addWidget(self.room_container)
        self.layout.addWidget(QLabel("<b>Structures</b>"))
        self.layout.addWidget(self.structure_container)
        self.layout.addWidget(QLabel("<b>Items</b>"))
        self.layout.addWidget(self.item_container)

        self.layout.addSpacing(15)
        self.layout.addWidget(QLabel("<b>Tools</b>"))
        
        # --- OCR Button ---
        self.btn_ocr = QPushButton("OCR Text Detection")
        self.btn_ocr.setCheckable(True)
        self.btn_ocr.setCursor(Qt.PointingHandCursor)
        self.btn_ocr.setStyleSheet(self._get_ocr_btn_style(False))
        self.btn_ocr.clicked.connect(self.on_ocr_clicked)
        self.layout.addWidget(self.btn_ocr)
        
        self.room_container.setVisible(False)
        self.structure_container.setVisible(False)
        self.item_container.setVisible(False)

    def on_ocr_clicked(self):
        is_checked = self.btn_ocr.isChecked()
        self.btn_ocr.setStyleSheet(self._get_ocr_btn_style(is_checked))
        self.ocrRequested.emit(is_checked)

    def _get_ocr_btn_style(self, is_selected):
        bg = "rgba(0, 200, 255, 60)" if is_selected else "transparent"
        border = "1px solid rgba(0, 200, 255, 100)" if is_selected else "1px solid #555"
        return f"""
            QPushButton {{
                text-align: center; 
                border: {border}; 
                background-color: {bg}; 
                padding: 6px;
                color: white;
                font-weight: bold;
                border-radius: 4px;
            }}
            QPushButton:hover {{
                background-color: rgba(0, 200, 255, 30);
            }}
        """

    def _clear_layout(self, layout):
        while layout.count():
            child = layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

    def refresh_legend(self, boq_data):
        self._clear_layout(self.room_layout)
        self._clear_layout(self.structure_layout)
        self._clear_layout(self.item_layout)
        self.buttons = {}
        
        present_rooms = {item['label'] for item in boq_data.get('rooms', [])}
        present_icons = {item['label'] for item in boq_data.get('icons', [])}

        structure_classes = {"Wall", "Railing"}
        room_classes_filtered = [c for c in constants.ROOM_CLASSES if c not in structure_classes]

        self._add_items_to_layout(self.room_layout, room_classes_filtered, 
                                 self.room_colors, constants.ROOM_CLASSES, present_rooms, is_room=True)
        self._add_items_to_layout(self.structure_layout, list(structure_classes), 
                                 self.room_colors, constants.ROOM_CLASSES, present_rooms, is_room=True, clickable=False)
        self._add_items_to_layout(self.item_layout, constants.ICON_CLASSES, 
                                 self.icon_colors, constants.ICON_CLASSES, present_icons, is_room=False)
        
        has_structures = any(s in present_rooms for s in structure_classes)
        self.structure_container.setVisible(has_structures)

    def _add_items_to_layout(self, layout, classes_to_show, color_map, source_classes_list, present_set, is_room, clickable=True):
        for label_name in classes_to_show:
            if label_name in present_set:
                try:
                    idx = source_classes_list.index(label_name)
                    c = color_map[idx]
                except ValueError: continue

                row = QWidget()
                row_layout = QHBoxLayout(row)
                row_layout.setContentsMargins(0, 2, 0, 2)
                
                color_lbl = QLabel()
                color_lbl.setFixedSize(14, 14)
                hex_c = f"#{c[0]:02x}{c[1]:02x}{c[2]:02x}"
                color_lbl.setStyleSheet(f"background-color: {hex_c}; border-radius: 2px;")
                row_layout.addWidget(color_lbl)

                if clickable:
                    btn = QPushButton(label_name)
                    btn.setCheckable(True) 
                    btn.setCursor(Qt.PointingHandCursor)
                    btn.setStyleSheet(self._get_btn_style(False))
                    btn.clicked.connect(lambda checked, b=btn, n=label_name, r=is_room: self.handle_click(b, n, r))
                    self.buttons[label_name] = btn
                    row_layout.addWidget(btn)
                else:
                    lbl = QLabel(label_name)
                    lbl.setStyleSheet("color: white; font-size: 11px; padding: 4px 8px;")
                    row_layout.addWidget(lbl)
                
                row_layout.addStretch()
                layout.addWidget(row)

    def _get_btn_style(self, is_selected):
        bg = "rgba(255, 255, 255, 60)" if is_selected else "transparent"
        border = "1px solid rgba(255, 255, 255, 100)" if is_selected else "1px solid transparent"
        return f"""
            QPushButton {{
                text-align: left; 
                border: {border}; 
                background-color: {bg}; 
                padding: 4px 8px;
                color: white;
                font-size: 11px;
                border-radius: 4px;
            }}
            QPushButton:hover {{
                background-color: rgba(255, 255, 255, 30);
            }}
        """

    def handle_click(self, btn, name, is_room):
        for other_btn in self.buttons.values():
            if other_btn != btn:
                other_btn.setChecked(False)
                other_btn.setStyleSheet(self._get_btn_style(False))
        is_active = btn.isChecked()
        btn.setStyleSheet(self._get_btn_style(is_active))
        main_win = self.window()
        viewer = None
        if hasattr(main_win, 'tabs'):
            viewer = main_win.tabs.currentWidget()
        if isinstance(viewer, DocumentViewer):
            target = name if is_active else None
            if is_room:
                viewer.select_room_type(target)
                viewer.select_item_type(None)
            else:
                viewer.select_item_type(target)
                viewer.select_room_type(None)

    def set_visibility(self, show_rooms, show_items):
        self.room_container.setVisible(show_rooms)
        has_structures = self.structure_layout.count() > 0
        self.structure_container.setVisible(show_rooms and has_structures)
        self.item_container.setVisible(show_items)