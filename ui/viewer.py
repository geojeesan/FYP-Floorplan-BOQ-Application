import os
import json
import zipfile
import math
import numpy as np
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QInputDialog, QGraphicsView, QGraphicsScene, 
    QGraphicsPixmapItem, QGraphicsRectItem, QGraphicsTextItem, QGraphicsItem
)
from PySide6.QtGui import QPixmap, QPainter, QPen, QColor, QFont, QPolygonF, QPainterPath, QBrush
from PySide6.QtCore import Qt, QPoint, QPointF, QEvent, QByteArray, QBuffer, QIODevice
import constants 

class NpEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super(NpEncoder, self).default(obj)

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
        self.ocr_data = []
        
        self.boq_data = None
        self.chat_log = [] 
        
        self.is_pdf_browser = False  
        self.pdf_path = None         
        self.current_page_num = 0    
        self.thumbnail_widget = None 
        
        # Visibility Toggles
        self.show_base_image = True
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
        self.selected_room_class = None
        self.selected_item_class = None

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        
        self.scene = QGraphicsScene()
        self.view = QGraphicsView(self.scene)
        self.view.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.view.setFrameShape(QGraphicsView.NoFrame)
        self.view.setStyleSheet("background-color: rgba(255, 255, 255, 10); border-radius: 10px; margin-top: 5px; margin-bottom: 10px;")
        
        # Native Center-Under-Mouse Zooming
        self.view.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.view.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        
        # Intercept events on the viewport
        self.view.viewport().installEventFilter(self)
        
        self.layout.addWidget(self.view)
        
        self.display_item = QGraphicsPixmapItem()

        self.display_item.setTransformationMode(Qt.SmoothTransformation)

        self.scene.addItem(self.display_item)
        
        if self.file_path.lower().endswith('.boq'):
            self.load_from_boq(self.file_path)
        else:
            self.load_base_image()
            
        self.set_mode("grab") # Initialize mode

    def _pixmap_to_bytes(self, pixmap):
        if not pixmap or pixmap.isNull(): return None
        ba = QByteArray()
        buffer = QBuffer(ba)
        buffer.open(QIODevice.WriteOnly)
        pixmap.save(buffer, "PNG")
        return ba.data()

    def save_to_boq(self, target_path):
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
                zf.writestr("data.json", json.dumps(self.boq_data, indent=4, cls=NpEncoder))
            
            meta = {
                "pixel_to_unit_ratio": self.pixel_to_unit_ratio,
                "manual_text_labels": [{'pos': [t['pos'].x(), t['pos'].y()], 'text': t['text']} for t in self.manual_text_labels],
                "completed_shapes": [[[p.x(), p.y()] for p in shape] for shape in self.completed_shapes],
                "has_analysis_data": self.has_analysis_data,
                "has_ocr_data": self.has_ocr_data,
                "ocr_data": self.ocr_data
            }
            zf.writestr("meta.json", json.dumps(meta, cls=NpEncoder))

    def load_from_boq(self, source_path):
        self.room_pixmap = None
        self.item_pixmap = None
        self.ocr_pixmap = None
        self.boq_data = None
        self.has_analysis_data = False
        self.has_ocr_data = False
        self.show_base_image = True
        self.ocr_data = []
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
                self.ocr_data = meta.get("ocr_data", [])
                
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
        self.json_data_path = None 
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
            self.ocr_data = []
            self.show_base_image = True
            self.show_rooms = False
            self.show_items = False
            self.show_ocr = False
            self.selected_room_class = None
            self.selected_item_class = None
            self.chat_log = [] 
            self.manual_text_labels = []
            self.clear_measurements()

    def set_ocr_data(self, ocr_data):
        self.ocr_data = ocr_data
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

    def set_mode(self, mode):
        self.mode = mode
        if mode == "grab":
            self.view.setDragMode(QGraphicsView.ScrollHandDrag)
            self.view.viewport().setCursor(Qt.OpenHandCursor)
        elif mode == "text":
            self.view.setDragMode(QGraphicsView.NoDrag)
            self.view.viewport().setCursor(Qt.IBeamCursor)
        else:
            self.view.setDragMode(QGraphicsView.NoDrag)
            self.view.viewport().setCursor(Qt.CrossCursor)
        self.update_view()

    def load_base_image(self):
        try:
            self.original_pixmap = QPixmap(self.file_path)
            if not self.original_pixmap.isNull():
                self.update_view()
        except Exception as e:
            print(f"Error: {e}")

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

    def get_scene_pos(self, event):
        """Converts raw mouse clicks into exact pixel coordinates on the image."""
        view_pos = event.pos()
        scene_pos = self.view.mapToScene(view_pos)
        return scene_pos

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
        elif event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            items = self.scene.selectedItems()
            if items:
                changed = False
                for item in items:
                    itype = item.data(0)
                    dict_id = item.data(1)
                    if itype == "ocr":
                        self.ocr_data = [d for d in self.ocr_data if id(d) != dict_id]
                        changed = True
                    elif itype == "manual":
                        self.manual_text_labels = [d for d in self.manual_text_labels if id(d) != dict_id]
                        changed = True
                
                if changed:
                    self.update_view()
                    event.accept()
                    return
            super().keyPressEvent(event)
        else:
            super().keyPressEvent(event)

    # Event Router
    def eventFilter(self, source, event):
        if source is self.view.viewport():
            # Handle Smooth Zooming
            if event.type() == QEvent.Wheel and (event.modifiers() & Qt.ControlModifier):
                zoom_factor = math.pow(1.0015, event.angleDelta().y())
                self.apply_zoom(zoom_factor)
                return True
                
            elif event.type() == QEvent.NativeGesture and event.gestureType() == Qt.NativeGestureType.ZoomNativeGesture:
                zoom_factor = 1.0 + event.value()
                self.apply_zoom(zoom_factor)
                return True
                
            # Handle Tool Interactions
            elif event.type() == QEvent.MouseButtonPress:
                self.handle_mouse_press(event)
                if self.mode != "grab": return True 
                
            elif event.type() == QEvent.MouseMove:
                self.handle_mouse_move(event)
                if self.mode != "grab": return True 
                
            elif event.type() == QEvent.MouseButtonRelease:
                self.handle_mouse_release(event)
                if self.mode != "grab": return True 

        return super().eventFilter(source, event)

    def apply_zoom(self, zoom_factor):
        self.view.scale(zoom_factor, zoom_factor)
        self.zoom_level = self.view.transform().m11()

    # Tool Logic
    def handle_mouse_press(self, event):
        img_pos = self.get_scene_pos(event)

        if self.mode == "measure" and event.button() == Qt.LeftButton:
            img_pos = self.snap_to_corner(img_pos)
            tolerance = 15 / max(self.zoom_level, 0.001)
            
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
            edited = False
            tolerance = 20 / max(self.zoom_level, 0.001)
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

    def handle_mouse_move(self, event):
        img_pos = self.get_scene_pos(event)

        if self.mode == "measure":
            img_pos = self.snap_to_corner(img_pos)

            if self.is_measuring_drag and len(self.anchor_points) > 0:
                P1 = self.anchor_points[-1]
                P2 = self.drag_current_p2
                M = img_pos
                
                Vx = M.x() - P2.x()
                Vy = M.y() - P2.y()
                
                if (Vx**2 + Vy**2)**0.5 < 5 / max(self.zoom_level, 0.001):
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

    def handle_mouse_release(self, event):
        if self.mode == "measure" and self.is_measuring_drag and event.button() == Qt.LeftButton:
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

        self.scene.clear()
        self.display_item = self.scene.addPixmap(self.original_pixmap)
        self.display_item.setTransformationMode(Qt.SmoothTransformation)
        self.display_item.setVisible(self.show_base_image)
        
        # 2. Add Vector Segmentation Layers
        if self.boq_data:
            try:
                room_colors, icon_colors = constants.get_class_colors()
                if self.show_rooms:
                    for item in self.boq_data.get("rooms", []):
                        c_id = item.get("class_id", 0)
                        c = room_colors[c_id] if c_id < len(room_colors) else [150, 150, 150]
                        if self.show_base_image == False:
                            brush = QBrush(QColor(int(c[0]), int(c[1]), int(c[2]), 255))
                        else:
                            brush = QBrush(QColor(int(c[0]), int(c[1]), int(c[2]), 140))
                        pts = [QPointF(float(p[0]), float(p[1])) for p in item.get("points", []) if len(p) >= 2]
                        if pts: self.scene.addPolygon(QPolygonF(pts), QPen(Qt.NoPen), brush)

                if self.show_items:
                    for item in self.boq_data.get("icons", []):
                        c_id = item.get("class_id", 0)
                        c = icon_colors[c_id] if c_id < len(icon_colors) else [150, 150, 150]
                        if self.show_base_image == False:
                            brush = QBrush(QColor(int(c[0]), int(c[1]), int(c[2]), 255))
                        else:
                            brush = QBrush(QColor(int(c[0]), int(c[1]), int(c[2]), 140))
                        pts = [QPointF(float(p[0]), float(p[1])) for p in item.get("points", []) if len(p) >= 2]
                        if pts: self.scene.addPolygon(QPolygonF(pts), QPen(Qt.NoPen), brush)
            except Exception as e: print(f"Error drawing vector layers: {e}")

        # 3. Draw AI Vector Polygons
        if self.selected_room_class and self.boq_data:
            self.draw_ai_shapes("rooms", self.selected_room_class, QColor(255, 140, 0))
        if self.selected_item_class and self.boq_data:
            self.draw_ai_shapes("icons", self.selected_item_class, QColor(0, 191, 255))

        if self.show_ocr and self.ocr_data:
            ocr_font = QFont("Segoe UI")
            ocr_font.setPixelSize(22) # Pixel sizing for OCR!
            ocr_font.setBold(True)
            
            for item in self.ocr_data:
                txt = item.get("text", "")
                poly = item.get("poly", [])
                angle = item.get("angle", "0")
                
                if not poly: continue
                
                cx = sum([p[0] for p in poly]) / 4
                cy = sum([p[1] for p in poly]) / 4
                
                text_item = self.scene.addText(txt, ocr_font)
                text_item.setDefaultTextColor(Qt.black)
                
                # Make text selectable, copyable, and editable natively
                text_item.setTextInteractionFlags(Qt.TextEditorInteraction)
                text_item.setFlag(QGraphicsItem.ItemIsSelectable, True)
                text_item.setData(0, "ocr")
                text_item.setData(1, id(item))
                
                # Bind edits directly to the underlying data
                def make_ocr_updater(t_item, d_dict):
                    return lambda: d_dict.update({"text": t_item.toPlainText()})
                text_item.document().contentsChanged.connect(make_ocr_updater(text_item, item))
                
                rect = text_item.boundingRect()

                text_item.setTransformOriginPoint(rect.width() / 2, rect.height() / 2)
                transform = text_item.transform()
                transform.scale(1, 1)
                text_item.setTransform(transform)

                if angle == "90": text_item.setRotation(270)
                elif angle == "180": text_item.setRotation(180)
                elif angle == "270": text_item.setRotation(90)

                text_item.setPos(cx - rect.width()/2, cy - rect.height()/2)

        main_color = QColor(255, 0, 0)
        poly_pen = QPen(main_color, 5)
        poly_pen.setCosmetic(True)
        dash_pen = QPen(main_color, 5, Qt.DashLine)
        dash_pen.setCosmetic(True)
        
        # Native Font for Measurements
        meas_font = QFont("Segoe UI")
        meas_font.setPixelSize(18)
        meas_font.setBold(True)

        # 4. Draw Completed Area Shapes
        for shape in self.completed_shapes:
            self.scene.addPolygon(QPolygonF(shape), poly_pen, QBrush(QColor(255, 0, 0, 40)))
            if self.pixel_to_unit_ratio:
                area = self.calculate_area_px(shape) * (self.pixel_to_unit_ratio ** 2)
                centroid = self.calculate_centroid(shape)
                
                fg_text = self.scene.addSimpleText(f"{area:.2f} m²", meas_font)
                fg_text.setBrush(Qt.white)
                
                # Center the text and ignore zoom
                rect = fg_text.boundingRect()
                fg_text.setPos(centroid.x() - rect.width()/2, centroid.y() - rect.height()/2)
                fg_text.setFlag(QGraphicsItem.ItemIgnoresTransformations)

        # 5. Draw Dynamic Path (Measurer)
        if self.current_path or self.anchor_points:
            # (Keep the existing line drawing loops exactly the same)
            for i in range(len(self.current_path) - 1):
                self.scene.addLine(self.current_path[i].x(), self.current_path[i].y(), 
                                   self.current_path[i+1].x(), self.current_path[i+1].y(), poly_pen)
            
            if self.is_measuring_drag and self.current_curve_points and len(self.anchor_points) > 0:
                if self.current_path:
                    self.scene.addLine(self.current_path[-1].x(), self.current_path[-1].y(), 
                                       self.current_curve_points[0].x(), self.current_curve_points[0].y(), poly_pen)
                for i in range(len(self.current_curve_points) - 1):
                    self.scene.addLine(self.current_curve_points[i].x(), self.current_curve_points[i].y(), 
                                       self.current_curve_points[i+1].x(), self.current_curve_points[i+1].y(), poly_pen)
            
            elif self.temp_mouse_pos and not self.is_measuring_drag and self.current_path:
                self.scene.addLine(self.current_path[-1].x(), self.current_path[-1].y(), 
                                   self.temp_mouse_pos.x(), self.temp_mouse_pos.y(), dash_pen)

            r = 3 # Small fixed radius
            anchor_brush = QBrush(main_color)
            for pt in self.anchor_points:
                dot = self.scene.addEllipse(-r, -r, r*2, r*2, QPen(Qt.NoPen), anchor_brush)
                dot.setPos(pt)
                dot.setFlag(QGraphicsItem.ItemIgnoresTransformations)
                
            if self.is_measuring_drag and self.drag_current_p2:
                dot = self.scene.addEllipse(-r, -r, r*2, r*2, QPen(Qt.NoPen), anchor_brush)
                dot.setPos(self.drag_current_p2)
                dot.setFlag(QGraphicsItem.ItemIgnoresTransformations)

            if self.pixel_to_unit_ratio and len(self.anchor_points) >= 2:
                for i in range(len(self.anchor_points) - 1):
                    p1 = self.anchor_points[i]
                    p2 = self.anchor_points[i+1]
                    d_m = (((p2.x()-p1.x())**2 + (p2.y()-p1.y())**2)**0.5) * self.pixel_to_unit_ratio
                    mid = (p1 + p2) / 2
                    
                    t = self.scene.addSimpleText(f"{d_m:.2f}m", meas_font)
                    t.setBrush(main_color)
                    rect = t.boundingRect()
                    t.setPos(mid.x() - rect.width()/2, mid.y() - rect.height()/2)
                    t.setFlag(QGraphicsItem.ItemIgnoresTransformations)

        # 6. Draw Manual Text Labels
        if self.manual_text_labels:
             label_font = QFont("Segoe UI")
             label_font.setPixelSize(22)
             label_font.setBold(True)
             
             for item in self.manual_text_labels:
                 pos = item['pos']
                 txt = item['text']
                 
                 text_item = self.scene.addText(txt, label_font)
                 text_item.setDefaultTextColor(Qt.blue)
                 
                 # Make text selectable, copyable, and editable natively
                 text_item.setTextInteractionFlags(Qt.TextEditorInteraction)
                 text_item.setFlag(QGraphicsItem.ItemIsSelectable, True)
                 text_item.setData(0, "manual")
                 text_item.setData(1, id(item))
                 
                 # Bind edits directly to the underlying data
                 def make_manual_updater(t_item, d_dict):
                     return lambda: d_dict.update({"text": t_item.toPlainText()})
                 text_item.document().contentsChanged.connect(make_manual_updater(text_item, item))
                 
                 rect = text_item.boundingRect()
                 text_item.setPos(pos.x() - rect.width()/2, pos.y() - rect.height()/2)

        self.scene.setSceneRect(self.display_item.boundingRect())

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

    def draw_ai_shapes(self, data_key, target_label, color):
        poly_pen = QPen(color, 2)
        poly_pen.setCosmetic(True) 
        poly_brush = QBrush(QColor(color.red(), color.green(), color.blue(), 80))
        
        instance_counter = 1 
        
        font = QFont("Segoe UI")
        font.setPixelSize(20)
        font.setBold(True)
        
        small_font = QFont("Segoe UI")
        small_font.setPixelSize(22)
        small_font.setBold(True)
        
        for item in self.boq_data.get(data_key, []):
            if item.get("label") == target_label:
                raw_pts = item.get("points", [])
                if not raw_pts: continue
                pts = []
                for p in raw_pts:
                    try:
                        if isinstance(p, (list, tuple)) and len(p) >= 2:
                            pts.append(QPointF(float(p[0]), float(p[1])))
                    except (TypeError, ValueError, IndexError):
                        continue
                if pts:
                    poly = QPolygonF(pts)
                    self.scene.addPolygon(poly, poly_pen, poly_brush)
                    
                    centroid = self.calculate_centroid(pts)
                    num_str = str(instance_counter)
                    
                    bg_num = self.scene.addSimpleText(num_str, font)
                    bg_num.setBrush(Qt.white)
                    bg_num.setPos(centroid + QPointF(2, 2))
                    
                    fg_num = self.scene.addSimpleText(num_str, font)
                    fg_num.setBrush(Qt.black)
                    fg_num.setPos(centroid)
                    
                    if self.pixel_to_unit_ratio and "area_pixels" in item:
                        area_px = item.get("area_pixels", 0)
                        real_area = area_px * (self.pixel_to_unit_ratio ** 2)
                        
                        area_txt = self.scene.addSimpleText(f"{real_area:.2f} m²", small_font)
                        area_txt.setBrush(Qt.black)
                        area_txt.setPos(centroid + QPointF(0, 45))
                        
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
    
    def snap_to_corner(self, pos, pixel_tolerance=15):
        """Finds the closest AI polygon corner and snaps to it if within tolerance."""
        if not self.boq_data:
            return pos
            
        closest_pt = pos
        # Convert visual pixel tolerance to scene coordinates based on current zoom
        min_dist = pixel_tolerance / max(self.zoom_level, 0.001) 
        
        for category in ["rooms", "icons"]:
            for item in self.boq_data.get(category, []):
                for p in item.get("points", []):
                    if len(p) >= 2:
                        pt = QPointF(float(p[0]), float(p[1]))
                        dist = ((pos.x() - pt.x())**2 + (pos.y() - pt.y())**2)**0.5
                        if dist < min_dist:
                            min_dist = dist
                            closest_pt = pt
                            
        return closest_pt
    
    def toggle_base_image(self, show_image):
        self.show_base_image = show_image
        self.update_view()