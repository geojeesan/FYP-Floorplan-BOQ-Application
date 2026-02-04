from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
)
from PySide6.QtCore import Qt
import constants
from .viewer import DocumentViewer

class LegendWidget(QWidget):
    """
    Displays color keys for Rooms and Icons.
    """
    def __init__(self):
        super().__init__()
        self.layout = QVBoxLayout(self)
        self.layout.setAlignment(Qt.AlignTop)
        
        self.room_colors, self.icon_colors = constants.get_class_colors()
        
        self.room_container = QWidget()
        self.room_layout = QVBoxLayout(self.room_container)
        self.room_layout.setContentsMargins(0,0,0,0)
        self.layout.addWidget(QLabel("<b>Rooms</b>"))
        self.layout.addWidget(self.room_container)
        
        self.item_container = QWidget()
        self.item_layout = QVBoxLayout(self.item_container)
        self.item_layout.setContentsMargins(0,0,0,0)
        self.layout.addWidget(QLabel("<b>Items</b>"))
        self.layout.addWidget(self.item_container)

        self.populate_legend(self.room_layout, constants.ROOM_CLASSES, self.room_colors, clickable=True)
        self.populate_legend(self.item_layout, constants.ICON_CLASSES, self.icon_colors, clickable=False)
        
        self.room_container.setVisible(False)
        self.item_container.setVisible(False)

    def populate_legend(self, layout, classes, colors, clickable):
        for i in range(1, len(classes)):
            if i >= len(colors): break
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 2, 0, 2)
            
            color_lbl = QLabel()
            color_lbl.setFixedSize(20, 20)
            c = colors[i]
            hex_c = f"#{c[0]:02x}{c[1]:02x}{c[2]:02x}"
            color_lbl.setStyleSheet(f"background-color: {hex_c}; border: 1px solid gray;")
            
            # Use specific name for the click handler
            label_name = classes[i]
            
            text_btn = QPushButton(label_name)
            text_btn.setEnabled(True)
            text_btn.setCursor(Qt.PointingHandCursor)
            
            # Updated style: White text with hover effect
            text_btn.setStyleSheet("""
                QPushButton {
                    text-align: left; 
                    border: 1px solid transparent; 
                    background: transparent; 
                    padding: 2px;
                    color: white; /* Changed to white for better contrast */
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: rgba(255, 255, 255, 30);
                    border: 1px solid rgba(255, 255, 255, 50);
                }
            """)
            
            if clickable:
                # Rooms use the existing orange logic
                text_btn.clicked.connect(lambda checked=False, n=label_name: self.on_room_clicked(n))
            else:
                # Items now use the new blue logic
                text_btn.clicked.connect(lambda checked=False, n=label_name: self.on_item_clicked(n))
                
            row_layout.addWidget(color_lbl)
            row_layout.addWidget(text_btn)
            row_layout.addStretch()
            layout.addWidget(row)

    def on_item_clicked(self, item_name):
        """Highlights AI-detected items (doors, windows, etc.) in Blue."""
        print(f"Item Legend clicked: {item_name}")
        main_win = self.window()
        if hasattr(main_win, 'tabs'):
            viewer = main_win.tabs.currentWidget()
            if isinstance(viewer, DocumentViewer):
                viewer.select_item_type(item_name)

    def on_room_clicked(self, room_name):
        """Dispatches the room selection to the active tab's viewer."""
        # Print for debugging to see if the button is even registering a click
        print(f"Legend clicked: {room_name}")
        
        # Traverse up to find the main window manually if .window() fails
        parent = self.parent()
        while parent is not None:
            if hasattr(parent, 'tabs'):
                viewer = parent.tabs.currentWidget()
                if isinstance(viewer, DocumentViewer):
                    viewer.select_room_type(room_name)
                    return
            parent = parent.parent()

    def set_visibility(self, show_rooms, show_items):
        self.room_container.setVisible(show_rooms)
        self.item_container.setVisible(show_items)