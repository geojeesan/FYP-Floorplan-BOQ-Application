from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
)
from PySide6.QtCore import Qt
import constants
from .viewer import DocumentViewer

class LegendWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.layout = QVBoxLayout(self)
        self.layout.setAlignment(Qt.AlignTop)
        
        self.room_colors, self.icon_colors = constants.get_class_colors()
        self.buttons = {} 
        
        # Containers for Room, Structure, and Item rows
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
        
        self.room_container.setVisible(False)
        self.structure_container.setVisible(False)
        self.item_container.setVisible(False)

    def _clear_layout(self, layout):
        """Safely removes all widgets from a layout."""
        while layout.count():
            child = layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

    def refresh_legend(self, boq_data):
        """Populates the legend dynamically based on detected objects."""
        self._clear_layout(self.room_layout)
        self._clear_layout(self.structure_layout)
        self._clear_layout(self.item_layout)
        self.buttons = {}
        
        # Extract unique labels actually present in the analysis
        present_rooms = {item['label'] for item in boq_data.get('rooms', [])}
        present_icons = {item['label'] for item in boq_data.get('icons', [])}

        structure_classes = {"Wall", "Railing"}
        room_classes_filtered = [c for c in constants.ROOM_CLASSES if c not in structure_classes]

        self._add_items_to_layout(self.room_layout, room_classes_filtered, 
                                 self.room_colors, constants.ROOM_CLASSES, present_rooms, is_room=True)
        
        # We need to map from the original constant index to get the correct color
        self._add_items_to_layout(self.structure_layout, list(structure_classes), 
                                 self.room_colors, constants.ROOM_CLASSES, present_rooms, is_room=True, clickable=False)

        self._add_items_to_layout(self.item_layout, constants.ICON_CLASSES, 
                                 self.icon_colors, constants.ICON_CLASSES, present_icons, is_room=False)
        
        # Update visibility of structure container if any structures are present
        has_structures = any(s in present_rooms for s in structure_classes)
        self.structure_container.setVisible(has_structures)

    def _add_items_to_layout(self, layout, classes_to_show, color_map, source_classes_list, present_set, is_room, clickable=True):
        for label_name in classes_to_show:
            if label_name in present_set:
                # Find original index for color
                try:
                    idx = source_classes_list.index(label_name)
                    c = color_map[idx]
                except ValueError:
                    continue # Should not happen if data is consistent

                row = QWidget()
                row_layout = QHBoxLayout(row)
                row_layout.setContentsMargins(0, 2, 0, 2)
                
                # Color Swatch
                color_lbl = QLabel()
                color_lbl.setFixedSize(14, 14)
                hex_c = f"#{c[0]:02x}{c[1]:02x}{c[2]:02x}"
                color_lbl.setStyleSheet(f"background-color: {hex_c}; border-radius: 2px;")
                
                row_layout.addWidget(color_lbl)

                if clickable:
                    # Toggleable Button
                    btn = QPushButton(label_name)
                    btn.setCheckable(True) 
                    btn.setCursor(Qt.PointingHandCursor)
                    btn.setStyleSheet(self._get_btn_style(False))
                    
                    # Pass the button itself to the handler to manage state
                    btn.clicked.connect(lambda checked, b=btn, n=label_name, r=is_room: self.handle_click(b, n, r))
                    
                    self.buttons[label_name] = btn
                    row_layout.addWidget(btn)
                else:
                    # Static Label for unclickable items
                    lbl = QLabel(label_name)
                    lbl.setStyleSheet("color: white; font-size: 11px; padding: 4px 8px;")
                    row_layout.addWidget(lbl)
                
                row_layout.addStretch()
                layout.addWidget(row)

    def _get_btn_style(self, is_selected):
        """Returns the CSS for selected vs unselected states."""
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
        """Manages the toggle logic and updates the DocumentViewer."""
        # Deselect all other buttons (Exclusive selection)
        for other_btn in self.buttons.values():
            if other_btn != btn:
                other_btn.setChecked(False)
                other_btn.setStyleSheet(self._get_btn_style(False))

        # Update style of the clicked button based on new toggle state
        is_active = btn.isChecked()
        btn.setStyleSheet(self._get_btn_style(is_active))
        
        # Find the active viewer in the main window
        main_win = self.window()
        viewer = None
        if hasattr(main_win, 'tabs'):
            viewer = main_win.tabs.currentWidget()

        if isinstance(viewer, DocumentViewer):
            # If active, highlight the class; if toggled OFF, clear it
            target = name if is_active else None
            if is_room:
                viewer.select_room_type(target)
                viewer.select_item_type(None) # Clear items if room selected
            else:
                viewer.select_item_type(target)
                viewer.select_room_type(None) # Clear rooms if item selected

    def set_visibility(self, show_rooms, show_items):
        """Syncs legend category visibility with the toolbar toggles."""
        self.room_container.setVisible(show_rooms)
        
        # Only show structures if they exist and rooms are enabled
        has_structures = self.structure_layout.count() > 0
        self.structure_container.setVisible(show_rooms and has_structures)
        
        self.item_container.setVisible(show_items)