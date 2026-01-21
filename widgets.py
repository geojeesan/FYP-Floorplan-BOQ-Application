import os
import json
import numpy as np
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QLabel, QInputDialog, QPushButton
)
from PySide6.QtGui import QPixmap, QPainter, QWheelEvent, QPen, QColor, QFont, QPolygonF, QCursor
from PySide6.QtCore import Qt, QPoint, QPointF, QEvent
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
    def __init__(self, file_path):
        super().__init__()
        self.file_path = file_path
        self.original_pixmap = None
        self.room_pixmap = None
        self.item_pixmap = None
        self.boq_data = None
        
        self.show_rooms = False
        self.show_items = False
        self.zoom_level = 1.0
        self.has_analysis_data = False
        
        # --- Persistent Measurement State ---
        self.mode = "grab" 
        self.completed_shapes = [] # List of lists: [ [p1, p2, p3], [p4, p5, p6] ]
        self.current_path = []     # Currently active line string
        self.is_closed = False     # State for the active path
        self.temp_mouse_pos = None
        self.pixel_to_unit_ratio = None
        self.last_mouse_pos = QPoint()

        # Initialize UI
        self.layout = QVBoxLayout(self)
        self.scroll_area = QScrollArea()
        self.label = QLabel()
        self.label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.label.installEventFilter(self)
        self.setFocusPolicy(Qt.StrongFocus)
        
        self.setMouseTracking(True)
        self.label.setMouseTracking(True)
        self.scroll_area.setMouseTracking(True)
        
        self.scroll_area.setWidget(self.label)
        self.scroll_area.setWidgetResizable(True)
        self.layout.addWidget(self.scroll_area)
        
        self.load_base_image()

    def set_mode(self, mode):
        """Toggle between 'grab' and 'measure' modes."""
        self.mode = mode
        if mode == "grab":
            self.label.setCursor(Qt.OpenHandCursor)
        else:
            self.label.setCursor(Qt.CrossCursor)
        self.update_view()

    def eventFilter(self, source, event):
        """Intercepts events from the label so DocumentViewer can see them."""
        if source is self.label and event.type() == QEvent.MouseMove:
            # Manually trigger our mouse move logic
            self.mouseMoveEvent(event)
        return super().eventFilter(source, event)

    def load_base_image(self):
        try:
            self.original_pixmap = QPixmap(self.file_path)
            if self.original_pixmap.isNull():
                self.label.setText("Failed to load image.")
            else:
                self.update_view()
        except Exception as e:
            self.label.setText(f"Error: {e}")

    def clear_measurements(self):
        """Clears everything: completed shapes and the active path."""
        self.completed_shapes = []
        self.current_path = []
        self.temp_mouse_pos = None
        self.is_closed = False
        self.update_view()

    def get_image_coords(self, pos):
        """Works with both global and local coordinates based on event type."""
        # If it's a QMouseEvent, it usually provides local pos relative to source
        return QPointF(pos) / self.zoom_level
    
    def recalibrate(self):
        """Re-opens scale input for the first segment of the active path."""
        if len(self.current_path) >= 2:
            self.calculate_initial_scale()
            self.update_view()

    def keyPressEvent(self, event):
        """Cancels measurement when Escape is pressed."""
        if event.key() == Qt.Key_Escape:
            self.clear_measurements()
            if hasattr(self.window(), 'update_toolbar_state'):
                self.window().update_toolbar_state()
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event):
        if self.mode == "measure" and event.button() == Qt.LeftButton:
            local_pos = self.label.mapFromGlobal(event.globalPos())
            img_pos = self.get_image_coords(local_pos)
            tolerance = 15 / self.zoom_level

            # 1. Logic for closing a loop or undoing a point
            for i, pt in enumerate(self.current_path):
                dist = ((img_pos.x() - pt.x())**2 + (img_pos.y() - pt.y())**2)**0.5
                if dist < tolerance:
                    if i == len(self.current_path) - 1:
                        self.current_path.pop()
                    else:
                        new_shape = self.current_path[i:]
                        self.completed_shapes.append(new_shape)
                        self.current_path = [] 
                    self.update_view()
                    return

            # 2. Logic for adding a new point
            self.current_path.append(img_pos)
            
            # Trigger scale prompt on the second point if not already calibrated
            if len(self.current_path) == 2 and self.pixel_to_unit_ratio is None:
                self.calculate_initial_scale()
            
            if hasattr(self.window(), 'update_toolbar_state'):
                self.window().update_toolbar_state()
                
            self.update_view()

        elif self.mode == "grab" and event.button() == Qt.LeftButton:
            self.label.setCursor(Qt.ClosedHandCursor)
            self.last_mouse_pos = event.globalPos()

    def mouseMoveEvent(self, event):
        if self.mode == "measure":
            # Stop the dotted line if shape is closed
            if self.is_closed:
                self.temp_mouse_pos = None
                return

            # Map mouse position to image coordinates
            if hasattr(event, 'globalPos'):
                local_pos = self.label.mapFromGlobal(event.globalPos())
            else:
                local_pos = event.pos()

            self.temp_mouse_pos = self.get_image_coords(local_pos)
            
            # FIX: Changed measurement_points to current_path
            if len(self.current_path) > 0:
                self.update_view()
        
        elif self.mode == "grab" and event.buttons() == Qt.LeftButton:
            current_pos = event.globalPos()
            delta = current_pos - self.last_mouse_pos
            self.last_mouse_pos = current_pos
            
            h_bar = self.scroll_area.horizontalScrollBar()
            v_bar = self.scroll_area.verticalScrollBar()
            h_bar.setValue(h_bar.value() - delta.x())
            v_bar.setValue(v_bar.value() - delta.y())

    def mouseReleaseEvent(self, event):
        if self.mode == "grab":
            self.label.setCursor(Qt.OpenHandCursor)

    def wheelEvent(self, event: QWheelEvent):
        if event.modifiers() & Qt.ControlModifier:
            # 1. Record current mouse position relative to the image (0.0 to 1.0)
            # This is the "anchor" point we want to zoom into
            pos = event.position()
            scrollbar_pos = QPoint(self.scroll_area.horizontalScrollBar().value(),
                                  self.scroll_area.verticalScrollBar().value())
            
            # Map mouse to global, then to label local
            local_pos = self.label.mapFromGlobal(event.globalPosition().toPoint())
            
            old_zoom = self.zoom_level
            if event.angleDelta().y() > 0: self.zoom_level *= 1.1
            else: self.zoom_level /= 1.1
            
            self.update_view()
            
            # 2. Adjust scrollbars to keep the mouse over the same image pixel
            zoom_factor = self.zoom_level / old_zoom
            new_h = (scrollbar_pos.x() + local_pos.x()) * zoom_factor - local_pos.x()
            new_v = (scrollbar_pos.y() + local_pos.y()) * zoom_factor - local_pos.y()
            
            self.scroll_area.horizontalScrollBar().setValue(int(new_h))
            self.scroll_area.verticalScrollBar().setValue(int(new_v))
            
            event.accept()

    def calculate_initial_scale(self):
        """Prompt for real-world distance using the first two points of the active path."""
        # FIX: Changed measurement_points to current_path
        if len(self.current_path) >= 2:
            p1, p2 = self.current_path[0], self.current_path[1]
            dist_px = ((p2.x() - p1.x())**2 + (p2.y() - p1.y())**2)**0.5
            
            val, ok = QInputDialog.getDouble(self, "Set Scale", 
                                            "Enter real-world length (m) for this segment:", 
                                            1.0, 0.01, 1000.0, 2)
            if ok:
                self.pixel_to_unit_ratio = val / dist_px
                self.update_view()

    def calculate_centroid(self, points):
        if not points: return QPointF(0, 0)
        return QPointF(sum(p.x() for p in points) / len(points), 
                       sum(p.y() for p in points) / len(points))
    
    def calculate_area_px(self, points):
        """Shoelace formula for a specific point list."""
        x = [p.x() for p in points]
        y = [p.y() for p in points]
        return 0.5 * np.abs(np.dot(x, np.roll(y, 1)) - np.dot(y, np.roll(x, 1)))

    def update_view(self):
        if not self.original_pixmap: return
        final_pixmap = QPixmap(self.original_pixmap)
        painter = QPainter(final_pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        if self.show_rooms and self.room_pixmap: painter.drawPixmap(0, 0, self.room_pixmap)
        if self.show_items and self.item_pixmap: painter.drawPixmap(0, 0, self.item_pixmap)
        painter.end()

        display_pixmap = final_pixmap
        if self.zoom_level != 1.0:
            display_pixmap = final_pixmap.scaled(final_pixmap.size() * self.zoom_level, Qt.KeepAspectRatio, Qt.SmoothTransformation)

        painter = QPainter(display_pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        main_color = QColor(0, 255, 0)
        painter.setFont(QFont("Segoe UI", 10, QFont.Bold))

        # --- DRAW COMPLETED SHAPES ---
        for shape in self.completed_shapes:
            d_pts = [p * self.zoom_level for p in shape]
            # Fill
            painter.setBrush(QColor(0, 255, 0, 40))
            painter.setPen(QPen(main_color, 3))
            painter.drawPolygon(QPolygonF(d_pts))
            
            # Area Label
            if self.pixel_to_unit_ratio:
                area = self.calculate_area_px(shape) * (self.pixel_to_unit_ratio ** 2)
                centroid = self.calculate_centroid(d_pts)
                painter.setPen(Qt.black)
                painter.drawText(centroid.toPoint() + QPoint(1,1), f"{area:.2f} m²")
                painter.setPen(Qt.white)
                painter.drawText(centroid.toPoint(), f"{area:.2f} m²")

        # --- DRAW ACTIVE PATH ---
        if self.current_path:
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(main_color, 3))
            d_path = [p * self.zoom_level for p in self.current_path]
            
            for pt in d_path:
                painter.setBrush(main_color)
                painter.drawEllipse(pt.toPoint(), 4, 4)

            painter.setBrush(Qt.NoBrush)
            for i in range(len(d_path) - 1):
                p1, p2 = d_path[i], d_path[i+1]
                painter.drawLine(p1, p2)
                if self.pixel_to_unit_ratio:
                    p1_img, p2_img = self.current_path[i], self.current_path[i+1]
                    d_m = (((p2_img.x()-p1_img.x())**2 + (p2_img.y()-p1_img.y())**2)**0.5) * self.pixel_to_unit_ratio
                    painter.drawText(((p1+p2)/2).toPoint(), f"{d_m:.2f}m")

            if self.temp_mouse_pos:
                painter.setPen(QPen(main_color, 2, Qt.DashLine))
                painter.drawLine(d_path[-1], self.temp_mouse_pos * self.zoom_level)

        painter.end()
        self.label.setPixmap(display_pixmap)

    def set_overlays(self, room_path, item_path, json_data_path=None):
        self.room_pixmap = QPixmap(room_path)
        self.item_pixmap = QPixmap(item_path)
        self.has_analysis_data = True
        self.update_view()

    def toggle_layers(self, show_rooms, show_items):
        self.show_rooms = show_rooms
        self.show_items = show_items
        self.update_view()