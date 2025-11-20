from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QLabel
)
from PySide6.QtGui import QPixmap, QPainter, QWheelEvent
from PySide6.QtCore import Qt
import constants

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

        self.populate_legend(self.room_layout, constants.ROOM_CLASSES, self.room_colors)
        self.populate_legend(self.item_layout, constants.ICON_CLASSES, self.icon_colors)
        
        self.room_container.setVisible(False)
        self.item_container.setVisible(False)

    def populate_legend(self, layout, classes, colors):
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
            
            text_lbl = QLabel(classes[i])
            row_layout.addWidget(color_lbl)
            row_layout.addWidget(text_lbl)
            row_layout.addStretch()
            layout.addWidget(row)

    def set_visibility(self, show_rooms, show_items):
        self.room_container.setVisible(show_rooms)
        self.item_container.setVisible(show_items)

class DocumentViewer(QWidget):
    """
    Displays an image and supports layering overlays (Rooms/Items).
    """
    def __init__(self, file_path):
        super().__init__()
        self.layout = QVBoxLayout(self)
        self.scroll_area = QScrollArea()
        self.label = QLabel()
        self.label.setAlignment(Qt.AlignCenter)
        
        self.scroll_area.setWidget(self.label)
        self.scroll_area.setWidgetResizable(True)
        self.layout.addWidget(self.scroll_area)
        
        self.file_path = file_path
        self.original_pixmap = None
        self.room_pixmap = None
        self.item_pixmap = None
        self.show_rooms = False
        self.show_items = False
        self.zoom_level = 1.0
        self.has_analysis_data = False
        self.load_base_image()

    def load_base_image(self):
        try:
            self.original_pixmap = QPixmap(self.file_path)
            if self.original_pixmap.isNull():
                self.label.setText("Failed to load image.")
            else:
                self.update_view()
        except Exception as e:
            self.label.setText(f"Error: {e}")

    def set_overlays(self, room_path, item_path):
        self.room_pixmap = QPixmap(room_path)
        self.item_pixmap = QPixmap(item_path)
        self.has_analysis_data = True
        self.update_view()

    def toggle_layers(self, show_rooms, show_items):
        self.show_rooms = show_rooms
        self.show_items = show_items
        self.update_view()

    def update_view(self):
        if not self.original_pixmap: return
        final_pixmap = QPixmap(self.original_pixmap)
        painter = QPainter(final_pixmap)
        if self.show_rooms and self.room_pixmap:
            painter.drawPixmap(0, 0, self.room_pixmap)
        if self.show_items and self.item_pixmap:
            painter.drawPixmap(0, 0, self.item_pixmap)
        painter.end()

        if self.zoom_level != 1.0:
            scaled = final_pixmap.scaled(
                final_pixmap.size() * self.zoom_level,
                Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            self.label.setPixmap(scaled)
        else:
            self.label.setPixmap(final_pixmap)

    def wheelEvent(self, event: QWheelEvent):
        if event.modifiers() & Qt.ControlModifier:
            if event.angleDelta().y() > 0: self.zoom_level *= 1.1
            else: self.zoom_level /= 1.1
            self.update_view()
            event.accept()
        else:
            super().wheelEvent(event)