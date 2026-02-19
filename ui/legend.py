from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QProgressBar
)
from PySide6.QtCore import Qt, Signal
import constants
from .viewer import DocumentViewer

class LegendWidget(QWidget):
    ocrRequested = Signal(bool) # Signal to Main Window: True=Show/Run, False=Hide
    ocrLabelsToggled = Signal(bool) # Signal to use OCR text as labels
    roomsToggled = Signal(bool)
    itemsToggled = Signal(bool)

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

        # Wrapper Widgets for toggle visibility
        self.rooms_wrapper = QWidget()
        self.rooms_wrapper_layout = QVBoxLayout(self.rooms_wrapper)
        self.rooms_wrapper_layout.setContentsMargins(0,0,0,0)
        
        self.items_wrapper = QWidget()
        self.items_wrapper_layout = QVBoxLayout(self.items_wrapper)
        self.items_wrapper_layout.setContentsMargins(0,0,0,0)

        # 1. Rooms Toggle and Section
        self.btn_toggle_rooms = QPushButton("Show Rooms and Structures")
        self.btn_toggle_rooms.setCheckable(True)
        self.btn_toggle_rooms.setChecked(True)
        self.btn_toggle_rooms.setCursor(Qt.PointingHandCursor)
        self.btn_toggle_rooms.setStyleSheet(self._get_btn_style(False))
        self.btn_toggle_rooms.clicked.connect(self.on_rooms_clicked)
        self.layout.addWidget(self.btn_toggle_rooms)
        
        # Rooms Content
        self.rooms_wrapper_layout.addWidget(QLabel("<b>Rooms</b>"))
        self.rooms_wrapper_layout.addWidget(self.room_container)
        self.lbl_structures = QLabel("<b>Structures</b>")
        self.rooms_wrapper_layout.addWidget(self.lbl_structures)
        self.rooms_wrapper_layout.addWidget(self.structure_container)
        self.layout.addWidget(self.rooms_wrapper)

        # 2. Items Toggle and Section
        self.btn_toggle_items = QPushButton("Show Items")
        self.btn_toggle_items.setCheckable(True)
        self.btn_toggle_items.setChecked(True)
        self.btn_toggle_items.setCursor(Qt.PointingHandCursor)
        self.btn_toggle_items.setStyleSheet(self._get_btn_style(False))
        self.btn_toggle_items.clicked.connect(self.on_items_clicked)
        self.layout.addWidget(self.btn_toggle_items)

        # Items Content
        self.items_wrapper_layout.addWidget(QLabel("<b>Items</b>"))
        self.items_wrapper_layout.addWidget(self.item_container)
        self.layout.addWidget(self.items_wrapper)
        
        # Initialize Visibility
        self.rooms_wrapper.setVisible(True)
        self.items_wrapper.setVisible(True)
        

        #self.layout.addWidget(QLabel("<b>Tools</b>"))
        
        # --- OCR Button ---
        self.btn_ocr = QPushButton("OCR Text Detection")
        self.btn_ocr.setCheckable(True)
        self.btn_ocr.setCursor(Qt.PointingHandCursor)
        self.btn_ocr.setStyleSheet(self._get_ocr_btn_style(False))
        self.btn_ocr.clicked.connect(self.on_ocr_clicked)
        self.layout.addWidget(self.btn_ocr)

        # --- OCR Progress Bar ---
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0) # Indeterminate
        self.progress_bar.setFixedHeight(10)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setVisible(False)
        self.layout.addWidget(self.progress_bar)

        # --- OCR Label Toggle ---
        self.btn_toggle_ocr_labels = QPushButton("Replace text labels with OCR")
        self.btn_toggle_ocr_labels.setCheckable(True)
        self.btn_toggle_ocr_labels.setCursor(Qt.PointingHandCursor)
        self.btn_toggle_ocr_labels.setVisible(False) # Hidden until OCR is done
        self.btn_toggle_ocr_labels.setStyleSheet(self._get_btn_style(False))
        self.btn_toggle_ocr_labels.clicked.connect(self.on_ocr_labels_toggled)
        self.layout.addWidget(self.btn_toggle_ocr_labels)
        
        self.structure_container.setVisible(False)

    def on_ocr_clicked(self):
        is_checked = self.btn_ocr.isChecked()
        self.btn_ocr.setStyleSheet(self._get_ocr_btn_style(is_checked))
        self.ocrRequested.emit(is_checked)

    def on_ocr_labels_toggled(self):
        is_checked = self.btn_toggle_ocr_labels.isChecked()
        self.btn_toggle_ocr_labels.setStyleSheet(self._get_btn_style(is_checked))
        self.ocrLabelsToggled.emit(is_checked)

    def on_rooms_clicked(self):
        is_checked = self.btn_toggle_rooms.isChecked()
        self.btn_toggle_rooms.setStyleSheet(self._get_btn_style(is_checked))
        self.rooms_wrapper.setVisible(is_checked)
        self.roomsToggled.emit(is_checked)

    def on_items_clicked(self):
        is_checked = self.btn_toggle_items.isChecked()
        self.btn_toggle_items.setStyleSheet(self._get_btn_style(is_checked))
        self.items_wrapper.setVisible(is_checked)
        self.itemsToggled.emit(is_checked)

    def show_progress(self):
        self.progress_bar.setVisible(True)

    def hide_progress(self):
        self.progress_bar.setVisible(False)

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
        
        # Helper to process room/icon list
        # We need to group by (label, class_id) to handle custom OCR labels
        # structure: { "LabelName": class_id }
        present_rooms = {} 
        present_structures = {}
        present_icons = {}

        structure_classes = {"Wall", "Railing"}

        for item in boq_data.get('rooms', []):
            lbl = item.get('label', 'Unknown')
            cid = item.get('class_id', -1)
            # Check if it's a structure based on the ORIGINAL class name if possible, 
            # or check if the current label is a structure name.
            # Best reliance is class_id
            
            original_class_name = constants.ROOM_CLASSES[cid] if 0 <= cid < len(constants.ROOM_CLASSES) else "Unknown"
            
            if original_class_name in structure_classes:
                present_structures[lbl] = cid
            else:
                present_rooms[lbl] = cid

        # Ensure mandatory structures are present
        if "Wall" not in present_structures:
            present_structures["Wall"] = 2
        if "Railing" not in present_structures:
            present_structures["Railing"] = 8

        for item in boq_data.get('icons', []):
            lbl = item.get('label', 'Unknown')
            cid = item.get('class_id', -1)
            present_icons[lbl] = cid

        # Sort keys for consistent display
        room_labels = sorted(present_rooms.keys())
        struct_labels = sorted(present_structures.keys())
        icon_labels = sorted(present_icons.keys())

        # Render
        self._add_dynamic_items(self.room_layout, room_labels, present_rooms, self.room_colors, is_room=True)
        self._add_dynamic_items(self.structure_layout, struct_labels, present_structures, self.room_colors, is_room=True, clickable=False)
        self._add_dynamic_items(self.item_layout, icon_labels, present_icons, self.icon_colors, is_room=False)
        
        has_structures = len(struct_labels) > 0
        self.structure_container.setVisible(has_structures)
        self.lbl_structures.setVisible(has_structures)

    def _add_dynamic_items(self, layout, label_list, label_map, color_palette, is_room, clickable=True):
        """
        label_list: list of strings (names to show)
        label_map: dict { name: class_id }
        color_palette: list of colors
        """
        for label_name in label_list:
            class_id = label_map[label_name]
            # Safety check on class_id
            if 0 <= class_id < len(color_palette):
                c = color_palette[class_id]
            else:
                c = (100, 100, 100) # Gray fallback

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
        # This acts as an external override or init
        self.rooms_wrapper.setVisible(show_rooms)
        self.items_wrapper.setVisible(show_items)
        
        # Manage internal structure visibility
        # If structures are empty, hide the subtitle too
        has_structures = self.structure_layout.count() > 0
        self.structure_container.setVisible(has_structures)
        self.lbl_structures.setVisible(has_structures)
        
        # Sync buttons
        self.btn_toggle_rooms.setChecked(show_rooms)
        self.btn_toggle_items.setChecked(show_items)
        self.btn_toggle_rooms.setStyleSheet(self._get_btn_style(show_rooms))
        self.btn_toggle_items.setStyleSheet(self._get_btn_style(show_items))