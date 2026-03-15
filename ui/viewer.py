import os
import json
import zipfile
import numpy as np
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QScrollArea, QLabel, QInputDialog
)
from PySide6.QtGui import QPixmap, QPainter, QWheelEvent, QPen, QColor, QFont, QPolygonF
from PySide6.QtCore import Qt, QPoint, QPointF, QEvent, QByteArray, QBuffer, QIODevice
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
        self.ocr_pixmap = None
        
        self.boq_data = None
        self.chat_log = [] 
        
        self.is_pdf_browser = False  
        self.pdf_path = None         
        self.current_page_num = 0    
        self.thumbnail_widget = None 
        
        # Visibility Toggles
        self.show_rooms = False
        self.show_items = False
        self.show_ocr = False
        
        self.zoom_level = 1.0
        self.has_analysis_data = False
        self.has_ocr_data = False
        
        self.mode = "grab" 
        self.completed_shapes = [] 
        self.current_path = []  
        self.anchor_points = [] 
        
        # Drag & Curve State
        self.is_measuring_drag = False
        self.is_closing_drag = False
        self.drag_current_p2 = None
        self.current_curve_points = []
        
        self.manual_text_labels = [] 
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
        
        if self.file_path.lower().endswith('.boq'):
            self.load_from_boq(self.file_path)
        else:
            self.load_base_image()

    def _pixmap_to_bytes(self, pixmap):
        if not pixmap or pixmap.isNull(): return None
        ba = QByteArray()
        buffer = QBuffer(ba)
        buffer.open(QIODevice.WriteOnly)
        pixmap.save(buffer, "PNG")
        return ba.data()

    def save_to_boq(self, target_path):
        """Saves all current state, image layers, and JSON data to a single .boq archive"""
        with zipfile.ZipFile(target_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            orig_bytes = self._pixmap_to_bytes(self.original_pixmap)
            if orig_bytes: zf.writestr("original.png", orig_bytes)
            
            room_bytes = self._pixmap_to_bytes(self.room_pixmap)
            if room_bytes: zf.writestr("rooms.png", room_bytes)
            
            item_bytes = self._pixmap_to_bytes(self.item_pixmap)
            if item_bytes: zf.writestr("items.png", item_bytes)
            
            ocr_bytes = self._pixmap_to_bytes(self.ocr_pixmap)
            if ocr_bytes: zf.writestr("ocr.png", ocr_bytes)
            
            if self.boq_data:
                zf.writestr("data.json", json.dumps(self.boq_data, indent=4))
            
            meta = {
                "pixel_to_unit_ratio": self.pixel_to_unit_ratio,
                "manual_text_labels": [{'pos': [t['pos'].x(), t['pos'].y()], 'text': t['text']} for t in self.manual_text_labels],
                "completed_shapes": [[[p.x(), p.y()] for p in shape] for shape in self.completed_shapes],
                "has_analysis_data": self.has_analysis_data,
                "has_ocr_data": self.has_ocr_data
            }
            zf.writestr("meta.json", json.dumps(meta))

    def load_from_boq(self, source_path):
        """Restores the application state completely from a .boq archive"""
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
        self.manual_text_labels = []
        self.clear_measurements()

        with zipfile.ZipFile(source_path, 'r') as zf:
            if "original.png" in zf.namelist():
                pm = QPixmap()
                pm.loadFromData(zf.read("original.png"))
                self.original_pixmap = pm
            
            if "rooms.png" in zf.namelist():
                pm = QPixmap()
                pm.loadFromData(zf.read("rooms.png"))
                self.room_pixmap = pm
                
            if "items.png" in zf.namelist():
                pm = QPixmap()
                pm.loadFromData(zf.read("items.png"))
                self.item_pixmap = pm
                
            if "ocr.png" in zf.namelist():
                pm = QPixmap()
                pm.loadFromData(zf.read("ocr.png"))
                self.ocr_pixmap = pm
                
            if "data.json" in zf.namelist():
                self.boq_data = json.loads(zf.read("data.json").decode('utf-8'))
                
            if "meta.json" in zf.namelist():
                meta = json.loads(zf.read("meta.json").decode('utf-8'))
                self.pixel_to_unit_ratio = meta.get("pixel_to_unit_ratio")
                self.has_analysis_data = meta.get("has_analysis_data", False)
                self.has_ocr_data = meta.get("has_ocr_data", False)
                
                for t in meta.get("manual_text_labels", []):
                    self.manual_text_labels.append({
                        'pos': QPointF(t['pos'][0], t['pos'][1]),
                        'text': t['text']
                    })
                    
                for shape in meta.get("completed_shapes", []):
                    self.completed_shapes.append([QPointF(p[0], p[1]) for p in shape])

        self.show_rooms = self.has_analysis_data
        self.show_items = self.has_analysis_data
        self.show_ocr = self.has_ocr_data
        self.json_data_path = None # State is completely managed in memory now
        self.update_view()

    def update_image(self, file_path):
        self.file_path = file_path
        if self.file_path.lower().endswith('.boq'):
            self.load_from_boq(self.file_path)
        else:
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
            self.manual_text_labels = []
            self.clear_measurements()

    def set_ocr_layer(self, layer_path):
        self.ocr_pixmap = QPixmap(layer_path)
        self.has_ocr_data = True
        self.show_ocr = True
        self.update_view()

    def toggle_ocr(self, visible):
        self.show_ocr = visible
        self.update_view()

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
        elif mode == "text":
            self.label.setCursor(Qt.IBeamCursor)
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
        self.anchor_points = []
        self.is_measuring_drag = False
        self.is_closing_drag = False
        self.drag_current_p2 = None
        self.current_curve_points = []
        self.temp_mouse_pos = None
        self.update_view()

    def get_image_coords(self, pos):
        return QPointF(pos) / self.zoom_level
    
    def recalibrate(self):
        if len(self.anchor_points) >= 2:
            self.calculate_initial_scale()
        else:
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
            
            is_close = False
            if len(self.anchor_points) >= 3:
                first_pt = self.anchor_points[0]
                dist = ((img_pos.x() - first_pt.x())**2 + (img_pos.y() - first_pt.y())**2)**0.5
                if dist < tolerance:
                    is_close = True

            self.is_measuring_drag = True
            
            if is_close:
                self.drag_current_p2 = self.anchor_points[0]
                self.is_closing_drag = True
            else:
                self.drag_current_p2 = img_pos
                self.is_closing_drag = False
                
            self.current_curve_points = [self.drag_current_p2]
            
            if hasattr(self.window(), 'update_toolbar_state'):
                self.window().update_toolbar_state()
            self.update_view()
            
        elif self.mode == "text" and event.button() == Qt.LeftButton:
            local_pos = self.label.mapFromGlobal(event.globalPos())
            img_pos = self.get_image_coords(local_pos)
            
            edited = False
            tolerance = 20 / self.zoom_level
            for item in self.manual_text_labels:
                pos = item['pos']
                dist = ((img_pos.x() - pos.x())**2 + (img_pos.y() - pos.y())**2)**0.5
                if dist < tolerance:
                    text, ok = QInputDialog.getText(self, "Edit Text", "Edit label:", text=item['text'])
                    if ok:
                        if text.strip():
                            item['text'] = text.strip()
                        else:
                            self.manual_text_labels.remove(item)
                    edited = True
                    break
            
            if not edited:
                text, ok = QInputDialog.getText(self, "Add Text", "Enter label text:")
                if ok and text.strip():
                    self.manual_text_labels.append({'pos': img_pos, 'text': text.strip()})
            
            self.update_view()

        elif self.mode == "grab" and event.button() == Qt.LeftButton:
            self.label.setCursor(Qt.ClosedHandCursor)
            self.last_mouse_pos = event.globalPos()

    def mouseMoveEvent(self, event):
        if self.mode == "measure":
            if hasattr(event, 'globalPos'):
                local_pos = self.label.mapFromGlobal(event.globalPos())
            else:
                local_pos = event.pos()
            img_pos = self.get_image_coords(local_pos)
            
            if self.is_measuring_drag and len(self.anchor_points) > 0:
                P1 = self.anchor_points[-1]
                P2 = self.drag_current_p2
                M = img_pos
                
                # Drag Vector (Current Mouse - Anchor 2)
                Vx = M.x() - P2.x()
                Vy = M.y() - P2.y()
                
                if (Vx**2 + Vy**2)**0.5 < 5 / self.zoom_level:
                    self.current_curve_points = [P2]
                else:
                    Mid_x = (P1.x() + P2.x()) / 2
                    Mid_y = (P1.y() + P2.y()) / 2
                    
                    Cx = Mid_x - Vx * 1.5 
                    Cy = Mid_y - Vy * 1.5
                    
                    pts = []
                    for i in range(1, 21):
                        t = i / 20.0
                        x = (1-t)**2 * P1.x() + 2*(1-t)*t * Cx + t**2 * P2.x()
                        y = (1-t)**2 * P1.y() + 2*(1-t)*t * Cy + t**2 * P2.y()
                        pts.append(QPointF(x, y))
                    self.current_curve_points = pts
                self.update_view()
            else:
                self.temp_mouse_pos = img_pos
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
        elif self.mode == "measure" and self.is_measuring_drag and event.button() == Qt.LeftButton:
            self.is_measuring_drag = False
            
            if self.is_closing_drag:
                self.current_path.extend(self.current_curve_points)
                self.completed_shapes.append(self.current_path)
                self.current_path = []
                self.anchor_points = []
            else:
                if len(self.anchor_points) == 0:
                    self.anchor_points.append(self.drag_current_p2)
                    self.current_path.append(self.drag_current_p2)
                else:
                    self.anchor_points.append(self.drag_current_p2)
                    self.current_path.extend(self.current_curve_points)
                    
                    if len(self.anchor_points) == 2 and self.pixel_to_unit_ratio is None:
                        self.calculate_initial_scale()
                        
            self.drag_current_p2 = None
            self.current_curve_points = []
            self.is_closing_drag = False
            
            if hasattr(self.window(), 'update_toolbar_state'):
                self.window().update_toolbar_state()
            self.update_view()

    def wheelEvent(self, event: QWheelEvent):
        if event.modifiers() & Qt.ControlModifier:
            pos = event.position()
            scrollbar_pos = QPoint(self.scroll_area.horizontalScrollBar().value(),
                                  self.scroll_area.verticalScrollBar().value())
            local_pos = self.label.mapFromGlobal(event.globalPosition().toPoint())
            old_zoom = self.zoom_level
            if event.angleDelta().y() > 0: self.zoom_level *= 1.1
            else: self.zoom_level /= 1.1
            self.zoom_level = max(self.zoom_level, 0.1)
            self.zoom_level = min(self.zoom_level, 50.0)
            self.update_view()
            zoom_factor = self.zoom_level / old_zoom
            new_h = (scrollbar_pos.x() + local_pos.x()) * zoom_factor - local_pos.x()
            new_v = (scrollbar_pos.y() + local_pos.y()) * zoom_factor - local_pos.y()
            self.scroll_area.horizontalScrollBar().setValue(int(new_h))
            self.scroll_area.verticalScrollBar().setValue(int(new_v))
            event.accept()

    def calculate_initial_scale(self):
        if len(self.anchor_points) >= 2:
            p1, p2 = self.anchor_points[0], self.anchor_points[1]
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
        
        if self.show_rooms and self.room_pixmap: 
            painter_base.drawPixmap(0, 0, self.room_pixmap)
        if self.show_items and self.item_pixmap: 
            painter_base.drawPixmap(0, 0, self.item_pixmap)
        if self.show_ocr and self.ocr_pixmap:
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
        
        # Draw Completed Area Shapes
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

        # Draw Current Dynamic Path
        if self.current_path or self.anchor_points:
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(main_color, 3))
            d_path = [p * self.zoom_level for p in self.current_path]
            
            for i in range(len(d_path) - 1):
                painter.drawLine(d_path[i], d_path[i+1])
            
            if self.is_measuring_drag and self.current_curve_points and len(self.anchor_points) > 0:
                d_curve = [p * self.zoom_level for p in self.current_curve_points]
                if d_path:
                    painter.drawLine(d_path[-1], d_curve[0])
                for i in range(len(d_curve) - 1):
                    painter.drawLine(d_curve[i], d_curve[i+1])
            elif self.temp_mouse_pos and not self.is_measuring_drag and d_path:
                painter.setPen(QPen(main_color, 2, Qt.DashLine))
                painter.drawLine(d_path[-1], self.temp_mouse_pos * self.zoom_level)

            painter.setBrush(main_color)
            painter.setPen(Qt.NoPen)
            for pt in self.anchor_points:
                painter.drawEllipse((pt * self.zoom_level).toPoint(), 4, 4)
            if self.is_measuring_drag and self.drag_current_p2:
                painter.drawEllipse((self.drag_current_p2 * self.zoom_level).toPoint(), 4, 4)

            if self.pixel_to_unit_ratio and len(self.anchor_points) >= 2:
                painter.setPen(main_color)
                for i in range(len(self.anchor_points) - 1):
                    p1_img = self.anchor_points[i]
                    p2_img = self.anchor_points[i+1]
                    d_m = (((p2_img.x()-p1_img.x())**2 + (p2_img.y()-p1_img.y())**2)**0.5) * self.pixel_to_unit_ratio
                    mid_img = (p1_img + p2_img) / 2
                    painter.drawText((mid_img * self.zoom_level).toPoint(), f"{d_m:.2f}m")

        # Draw Manual Text
        if self.manual_text_labels:
             font = QFont("Segoe UI", 12, QFont.Bold)
             painter.setFont(font)
             for item in self.manual_text_labels:
                 pos = item['pos']
                 txt = item['text']
                 screen_pos = pos * self.zoom_level
                 
                 fm = painter.fontMetrics()
                 rect = fm.boundingRect(txt)
                 rect.moveCenter(screen_pos.toPoint())
                 rect.adjust(-5, -2, 5, 2)
                 
                 painter.setPen(Qt.NoPen)
                 painter.setBrush(QColor(255, 255, 255, 180))
                 painter.drawRoundedRect(rect, 4, 4)
                 
                 painter.setPen(QPen(Qt.blue, 2))
                 painter.drawText(rect, Qt.AlignCenter, txt)

        painter.end()
        self.label.setPixmap(display_pixmap)

    def get_manual_text_data(self):
        results = []
        for item in self.manual_text_labels:
            pos = item['pos']
            w, h = 10, 10
            rect = [pos.x() - w/2, pos.y() - h/2, pos.x() + w/2, pos.y() + h/2]
            results.append({
                'text': item['text'],
                'rect': rect
            })
        return results

    def draw_ai_shapes(self, painter, data_key, target_label, color):
        painter.setPen(QPen(color, 4))
        painter.setBrush(QColor(color.red(), color.green(), color.blue(), 80))
        
        instance_counter = 1 
        
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
                    
                    centroid = self.calculate_centroid(pts)
                    
                    painter.setFont(QFont("Segoe UI", 16, QFont.Bold))
                    num_str = str(instance_counter)
                    
                    painter.setPen(QPen(Qt.white, 3))
                    painter.drawText(centroid.toPoint() + QPoint(1,1), num_str)
                    painter.setPen(QPen(Qt.black, 3))
                    painter.drawText(centroid.toPoint(), num_str)
                    
                    if self.pixel_to_unit_ratio and "area_pixels" in item:
                        area_px = item.get("area_pixels", 0)
                        real_area = area_px * (self.pixel_to_unit_ratio ** 2)
                        painter.setFont(QFont("Segoe UI", 11, QFont.Bold))
                        painter.setPen(Qt.black)
                        painter.drawText(centroid.toPoint() + QPoint(0, 20), f"{real_area:.2f} m²")
                        
                    painter.setPen(QPen(color, 4))
                    
                instance_counter += 1

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
        if not self.boq_data:
            return {}

        import copy
        data = copy.deepcopy(self.boq_data)
        
        ratio = self.pixel_to_unit_ratio

        data['calibration_info'] = {
            "is_calibrated": ratio is not None,
            "pixel_to_unit_ratio": ratio if ratio is not None else 1.0
        }
        
        def convert_area(px_area):
            if ratio is None: return f"{px_area:.0f} px²"
            m2 = px_area * (ratio ** 2)
            return f"{m2:.2f} m²"

        for room in data.get('rooms', []):
            area_px = room.get('area_pixels', 0)
            room['area_readable'] = convert_area(area_px)
            if 'box_2d' in room: del room['box_2d']

        for icon in data.get('icons', []):
            if 'box_2d' in icon: del icon['box_2d']
            
        return data