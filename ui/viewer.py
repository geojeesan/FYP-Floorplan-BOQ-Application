import os
import json
import numpy as np
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QScrollArea, QLabel, QInputDialog
)
from PySide6.QtGui import QPixmap, QPainter, QWheelEvent, QPen, QColor, QFont, QPolygonF
from PySide6.QtCore import Qt, QPoint, QPointF, QEvent
import constants 

class DocumentViewer(QWidget):
    def __init__(self, file_path):
        super().__init__()
        self.file_path = file_path
        self.json_data_path = None
        
        # Image Layers
        self.original_pixmap = None
        self.room_pixmap = None
        self.item_pixmap = None
        self.ocr_pixmap = None  # <--- NEW
        
        self.boq_data = None
        self.chat_log = [] 
        
        self.is_pdf_browser = False  
        self.pdf_path = None         
        self.current_page_num = 0    
        self.thumbnail_widget = None 
        
        # Visibility Toggles
        self.show_rooms = False
        self.show_items = False
        self.show_ocr = False   # <--- NEW
        
        self.zoom_level = 1.0
        self.has_analysis_data = False
        self.has_ocr_data = False # <--- NEW
        
        self.mode = "grab" 
        self.completed_shapes = [] 
        self.current_path = []     
        self.is_closed = False     
        self.temp_mouse_pos = None
        self.pixel_to_unit_ratio = None
        self.last_mouse_pos = QPoint()
        self.selected_room_class = None
        self.selected_item_class = None

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

    def update_image(self, file_path):
        self.file_path = file_path
        self.load_base_image()
        self.room_pixmap = None
        self.item_pixmap = None
        self.ocr_pixmap = None
        self.boq_data = None
        self.has_analysis_data = False
        self.has_ocr_data = False
        self.show_rooms = False
        self.show_items = False
        self.show_ocr = False
        self.selected_room_class = None
        self.selected_item_class = None
        self.chat_log = [] 
        self.clear_measurements()

    def set_ocr_layer(self, layer_path):
        """Called when OCRWorker finishes."""
        self.ocr_pixmap = QPixmap(layer_path)
        self.has_ocr_data = True
        self.show_ocr = True
        self.update_view()

    def toggle_ocr(self, visible):
        """Toggles the visibility of the OCR layer."""
        self.show_ocr = visible
        self.update_view()

    # ... (Rest of measurement/mouse methods remain unchanged) ...

    def select_item_type(self, item_name):
        self.selected_item_class = item_name
        self.update_view()

    def select_room_type(self, room_name):
        self.selected_room_class = room_name
        self.update_view()
        self.label.update()

    def set_mode(self, mode):
        self.mode = mode
        if mode == "grab":
            self.label.setCursor(Qt.OpenHandCursor)
        else:
            self.label.setCursor(Qt.CrossCursor)
        self.update_view()

    def eventFilter(self, source, event):
        if source is self.label and event.type() == QEvent.MouseMove:
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
        self.completed_shapes = []
        self.current_path = []
        self.temp_mouse_pos = None
        self.is_closed = False
        self.update_view()

    def get_image_coords(self, pos):
        return QPointF(pos) / self.zoom_level
    
    def recalibrate(self):
        if len(self.current_path) >= 2:
            # Recalibrate based on the current active segment
            self.calculate_initial_scale()
        else:
            # Reset the scale and enter measure mode so the next drawn line sets the new scale
            self.pixel_to_unit_ratio = None
            self.set_mode("measure")
            
        self.update_view()

    def keyPressEvent(self, event):
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
            self.current_path.append(img_pos)
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
            if self.is_closed:
                self.temp_mouse_pos = None
                return
            if hasattr(event, 'globalPos'):
                local_pos = self.label.mapFromGlobal(event.globalPos())
            else:
                local_pos = event.pos()
            self.temp_mouse_pos = self.get_image_coords(local_pos)
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
            pos = event.position()
            scrollbar_pos = QPoint(self.scroll_area.horizontalScrollBar().value(),
                                  self.scroll_area.verticalScrollBar().value())
            local_pos = self.label.mapFromGlobal(event.globalPosition().toPoint())
            old_zoom = self.zoom_level
            if event.angleDelta().y() > 0: self.zoom_level *= 1.1
            else: self.zoom_level /= 1.1
            self.update_view()
            zoom_factor = self.zoom_level / old_zoom
            new_h = (scrollbar_pos.x() + local_pos.x()) * zoom_factor - local_pos.x()
            new_v = (scrollbar_pos.y() + local_pos.y()) * zoom_factor - local_pos.y()
            self.scroll_area.horizontalScrollBar().setValue(int(new_h))
            self.scroll_area.verticalScrollBar().setValue(int(new_v))
            event.accept()

    def calculate_initial_scale(self):
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
        x = [p.x() for p in points]
        y = [p.y() for p in points]
        return 0.5 * np.abs(np.dot(x, np.roll(y, 1)) - np.dot(y, np.roll(x, 1)))

    def update_view(self):
        if not self.original_pixmap: return

        final_pixmap = QPixmap(self.original_pixmap)
        painter_base = QPainter(final_pixmap)
        
        # Draw Layers in order
        if self.show_rooms and self.room_pixmap: 
            painter_base.drawPixmap(0, 0, self.room_pixmap)
        if self.show_items and self.item_pixmap: 
            painter_base.drawPixmap(0, 0, self.item_pixmap)
        if self.show_ocr and self.ocr_pixmap:  # <--- NEW
            painter_base.drawPixmap(0, 0, self.ocr_pixmap)
            
        painter_base.end()

        display_pixmap = final_pixmap
        if self.zoom_level != 1.0:
            display_pixmap = final_pixmap.scaled(
                final_pixmap.size() * self.zoom_level, 
                Qt.KeepAspectRatio, Qt.SmoothTransformation
            )

        painter = QPainter(display_pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        
        if self.selected_room_class and self.boq_data:
            self.draw_ai_shapes(painter, "rooms", self.selected_room_class, QColor(255, 140, 0))

        if self.selected_item_class and self.boq_data:
            self.draw_ai_shapes(painter, "icons", self.selected_item_class, QColor(0, 191, 255))

        main_color = QColor(255, 0, 0)
        painter.setFont(QFont("Segoe UI", 10, QFont.Bold))
        for shape in self.completed_shapes:
            d_pts = [p * self.zoom_level for p in shape]
            painter.setBrush(QColor(255, 0, 0, 40))
            painter.setPen(QPen(main_color, 3))
            painter.drawPolygon(QPolygonF(d_pts))
            
            if self.pixel_to_unit_ratio:
                area = self.calculate_area_px(shape) * (self.pixel_to_unit_ratio ** 2)
                centroid = self.calculate_centroid(d_pts)
                painter.setPen(Qt.black)
                painter.drawText(centroid.toPoint() + QPoint(1,1), f"{area:.2f} m²")
                painter.setPen(Qt.white)
                painter.drawText(centroid.toPoint(), f"{area:.2f} m²")

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

    def draw_ai_shapes(self, painter, data_key, target_label, color):
        painter.setPen(QPen(color, 4))
        painter.setBrush(QColor(color.red(), color.green(), color.blue(), 80))
        painter.setFont(QFont("Segoe UI", 11, QFont.Bold))
        for item in self.boq_data.get(data_key, []):
            if item.get("label") == target_label:
                raw_pts = item.get("points", [])
                if not raw_pts: continue
                pts = []
                for p in raw_pts:
                    try:
                        if isinstance(p, (list, tuple)) and len(p) >= 2:
                            pts.append(QPointF(float(p[0]), float(p[1])) * self.zoom_level)
                    except (TypeError, ValueError, IndexError):
                        continue
                if pts:
                    painter.drawPolygon(QPolygonF(pts))
                    if self.pixel_to_unit_ratio and "area_pixels" in item:
                        area_px = item.get("area_pixels", 0)
                        real_area = area_px * (self.pixel_to_unit_ratio ** 2)
                        centroid = self.calculate_centroid(pts)
                        painter.setPen(Qt.black)
                        painter.drawText(centroid.toPoint(), f"{real_area:.2f} m²")
                        painter.setPen(color)

    def set_overlays(self, room_path, item_path, json_data_path=None):
        self.room_pixmap = QPixmap(room_path)
        self.item_pixmap = QPixmap(item_path)
        self.json_data_path = json_data_path
        if json_data_path and os.path.exists(json_data_path):
            try:
                with open(json_data_path, 'r') as f:
                    self.boq_data = json.load(f)
            except Exception as e:
                print(f"Failed to load AI JSON: {e}")
        self.has_analysis_data = True
        self.update_view()

    def toggle_layers(self, show_rooms, show_items):
        self.show_rooms = show_rooms
        self.show_items = show_items
        self.update_view()

    def get_scaled_boq_data(self):
        """
        Returns a copy of the BOQ data with areas converted to real-world units
        if calibration (pixel_to_unit_ratio) is set.
        """
        if not self.boq_data:
            return {}

        import copy
        data = copy.deepcopy(self.boq_data)
        
        ratio = self.pixel_to_unit_ratio
        
        # Helper to convert
        def convert_area(px_area):
            if ratio is None: return f"{px_area:.0f} px²"
            m2 = px_area * (ratio ** 2)
            return f"{m2:.2f} m²"

        # Apply to Rooms
        for room in data.get('rooms', []):
            area_px = room.get('area_pixels', 0)
            room['area_readable'] = convert_area(area_px)
            # Remove raw points to save token context window for LLM
            if 'points' in room: del room['points']
            if 'box_2d' in room: del room['box_2d']

        # Apply to Icons (if they had area, but usually they are counts/points)
        for icon in data.get('icons', []):
            # Icons usually point locations, but if we had dimensions we'd scale them
            if 'box_2d' in icon: del icon['box_2d']
            if 'points' in icon: del icon['points']
            
        return data