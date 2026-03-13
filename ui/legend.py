import json
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QProgressBar,
    QMessageBox, QInputDialog, QDialog, QFormLayout, QLineEdit, QComboBox,
    QDialogButtonBox, QColorDialog
)
from PySide6.QtCore import Qt, Signal, QPointF
from PySide6.QtGui import QPainter, QPolygonF, QColor
import qtawesome as qta
import constants
from .viewer import DocumentViewer
from .material_assigner import MaterialAssignmentDialog


class AddMeasurementDialog(QDialog):
    """Custom dialog to ask for the name and type of a new measurement."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Save Measurement")
        self.setMinimumWidth(300)
        
        self.layout = QVBoxLayout(self)
        self.form_layout = QFormLayout()
        
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("e.g., Bedroom, Closet, Window...")
        
        self.type_combo = QComboBox()
        self.type_combo.addItems(["Room", "Item"])
        
        self.form_layout.addRow("Name:", self.name_input)
        self.form_layout.addRow("Type:", self.type_combo)
        self.layout.addLayout(self.form_layout)
        
        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        self.layout.addWidget(self.button_box)
        
    def get_data(self):
        return self.name_input.text().strip(), self.type_combo.currentText() == "Item"


class LegendButton(QPushButton):
    """Custom button to emit a double click signal."""
    doubleClicked = Signal()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.doubleClicked.emit()
        super().mouseDoubleClickEvent(event)


class ColorLabel(QLabel):
    """Custom label to emit a double click signal for color changing."""
    doubleClicked = Signal()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.doubleClicked.emit()
        super().mouseDoubleClickEvent(event)


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

        # Custom Tools Section Divider
        self.layout.addSpacing(10)
        
        # Save Measurement Button
        self.btn_add_measurement = QPushButton("Save Last Measurement")
        self.btn_add_measurement.setIcon(qta.icon('fa5s.draw-polygon', color='white'))
        self.btn_add_measurement.setCursor(Qt.PointingHandCursor)
        self.btn_add_measurement.setStyleSheet(self._get_action_btn_style())
        self.btn_add_measurement.clicked.connect(self.on_add_measurement)
        self.layout.addWidget(self.btn_add_measurement)

        # OCR Button
        self.btn_ocr = QPushButton("OCR Text Detection")
        self.btn_ocr.setIcon(qta.icon('fa5s.camera', color='white'))
        self.btn_ocr.setCheckable(True)
        self.btn_ocr.setCursor(Qt.PointingHandCursor)
        self.btn_ocr.setStyleSheet(self._get_ocr_btn_style(False))
        self.btn_ocr.clicked.connect(self.on_ocr_clicked)
        self.layout.addWidget(self.btn_ocr)

        # OCR Progress Bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0) # Indeterminate
        self.progress_bar.setFixedHeight(10)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setVisible(False)
        self.layout.addWidget(self.progress_bar)

        # OCR Label Toggle
        self.btn_toggle_ocr_labels = QPushButton("Replace text labels with OCR")
        self.btn_toggle_ocr_labels.setCheckable(True)
        self.btn_toggle_ocr_labels.setCursor(Qt.PointingHandCursor)
        self.btn_toggle_ocr_labels.setVisible(False) # Hidden until OCR is done
        self.btn_toggle_ocr_labels.setStyleSheet(self._get_btn_style(False))
        self.btn_toggle_ocr_labels.clicked.connect(self.on_ocr_labels_toggled)
        self.layout.addWidget(self.btn_toggle_ocr_labels)
        
        self.structure_container.setVisible(False)

    def on_add_measurement(self):
        main_win = self.window()
        viewer = main_win.current_widget() if hasattr(main_win, 'current_widget') else None
        
        if not isinstance(viewer, DocumentViewer) or not viewer.boq_data:
            QMessageBox.warning(self, "Error", "No active analysis data. Please analyze a floorplan first.")
            return
            
        if not viewer.completed_shapes:
            QMessageBox.information(self, "No Measurement", "Please use the Measure Tool to outline a closed area first.")
            return
            
        dialog = AddMeasurementDialog(self)
        if dialog.exec() == QDialog.Accepted:
            name, is_item = dialog.get_data()
            if not name:
                QMessageBox.warning(self, "Error", "Name cannot be empty.")
                return
        else:
            return
            
        # Take the most recently drawn shape
        shape = viewer.completed_shapes[-1]
        
        target_list_key = 'icons' if is_item else 'rooms'
        colors_list = self.icon_colors if is_item else self.room_colors
        
        class_id = -1
        # Check if the name already exists in the selected category to inherit the ID
        for item in viewer.boq_data.get(target_list_key, []):
            if item.get('label') == name:
                class_id = item.get('class_id', -1)
                break
                    
        # If completely new name in this category, assign a new ID
        if class_id == -1:
            existing_ids = [r.get('class_id', 0) for r in viewer.boq_data.get(target_list_key, [])]
            class_id = max(existing_ids) + 1 if existing_ids else 1
            if class_id >= len(colors_list):
                class_id = len(colors_list) - 1 # Cap it so it doesn't crash colors
        
        area_px = viewer.calculate_area_px(shape)
        points_list = [[p.x(), p.y()] for p in shape]
        
        new_item = {
            "class_id": class_id,
            "label": name,
            "area_pixels": area_px,
            "points": points_list
        }
        
        viewer.boq_data.setdefault(target_list_key, []).append(new_item)
        
        # Remove it from the temporary red measurement shapes
        viewer.completed_shapes.pop()
        
        # Permanently embed it into the segmentation mask layer
        target_pixmap = viewer.item_pixmap if is_item else viewer.room_pixmap
        if target_pixmap and not target_pixmap.isNull():
            painter = QPainter(target_pixmap)
            c = colors_list[class_id % len(colors_list)]
            # Draw with 140 Alpha so it matches CubiCasa's transparency
            painter.setBrush(QColor(c[0], c[1], c[2], 140))
            painter.setPen(Qt.NoPen)
            poly = QPolygonF([QPointF(p[0], p[1]) for p in points_list])
            painter.drawPolygon(poly)
            painter.end()
            
        # Save to File
        if viewer.json_data_path:
            try:
                with open(viewer.json_data_path, 'w') as f:
                    json.dump(viewer.boq_data, f, indent=4)
            except Exception as e:
                print(f"Error saving JSON after adding measurement: {e}")
                
        # Force redraw and UI refresh
        viewer.update_view()
        self.refresh_legend(viewer.boq_data)

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
        
    def _get_action_btn_style(self):
        return f"""
            QPushButton {{
                text-align: center; 
                border: 1px solid #555; 
                background-color: "transparent"; 
                padding: 6px;
                color: white;
                font-weight: bold;
                border-radius: 4px;
            }}
            QPushButton:hover {{
                background-color: rgba(251, 154, 68, 90);
            }}
        """

    def _get_ocr_btn_style(self, is_selected):
        bg = "rgba(251, 154, 68, 90)" if is_selected else "transparent"
        border = "1px solid rgba(251, 154, 68, 100)" if is_selected else "1px solid #555"
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
                background-color: rgba(251, 154, 68, 90);
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
        
        present_rooms = {} 
        present_structures = {}
        present_icons = {}

        structure_classes = {"Wall", "Railing"}

        for item in boq_data.get('rooms', []):
            lbl = item.get('label', 'Unknown')
            cid = item.get('class_id', -1)
            
            original_class_name = constants.ROOM_CLASSES[cid] if 0 <= cid < len(constants.ROOM_CLASSES) else "Unknown"
            
            if original_class_name in structure_classes:
                present_structures[lbl] = cid
            else:
                present_rooms[lbl] = cid

        if "Wall" not in present_structures:
            present_structures["Wall"] = 2
        if "Railing" not in present_structures:
            present_structures["Railing"] = 8

        for item in boq_data.get('icons', []):
            lbl = item.get('label', 'Unknown')
            cid = item.get('class_id', -1)
            present_icons[lbl] = cid

        room_labels = sorted(present_rooms.keys())
        struct_labels = sorted(present_structures.keys())
        icon_labels = sorted(present_icons.keys())

        self._add_dynamic_items(self.room_layout, room_labels, present_rooms, self.room_colors, is_room=True)
        self._add_dynamic_items(self.structure_layout, struct_labels, present_structures, self.room_colors, is_room=True, clickable=False)
        self._add_dynamic_items(self.item_layout, icon_labels, present_icons, self.icon_colors, is_room=False)
        
        has_structures = len(struct_labels) > 0
        self.structure_container.setVisible(has_structures)
        self.lbl_structures.setVisible(has_structures)

    def change_category_color(self, class_id, is_room, current_color):
        main_win = self.window()
        viewer = main_win.current_widget() if hasattr(main_win, 'current_widget') else None
        
        if not isinstance(viewer, DocumentViewer) or not viewer.boq_data:
            return

        initial_qcolor = QColor(current_color[0], current_color[1], current_color[2])
        new_qcolor = QColorDialog.getColor(initial_qcolor, self, "Select New Color")

        if not new_qcolor.isValid():
            return

        new_c = (new_qcolor.red(), new_qcolor.green(), new_qcolor.blue())

        # Update Local Palette
        if is_room:
            while len(self.room_colors) <= class_id:
                self.room_colors.append((100, 100, 100))
            self.room_colors[class_id] = new_c
        else:
            while len(self.icon_colors) <= class_id:
                self.icon_colors.append((100, 100, 100))
            self.icon_colors[class_id] = new_c

        # Redraw all polygons of this class on the pixmap
        target_pixmap = viewer.room_pixmap if is_room else viewer.item_pixmap
        data_key = 'rooms' if is_room else 'icons'
        target_list = viewer.boq_data.get(data_key, [])

        if target_pixmap and not target_pixmap.isNull():
            painter = QPainter(target_pixmap)
            
            # Use CompositionMode_Source to overwrite the existing pixels exactly for the chosen category
            painter.setCompositionMode(QPainter.CompositionMode_Source)
            painter.setBrush(QColor(new_c[0], new_c[1], new_c[2], 140))
            painter.setPen(Qt.NoPen)
            
            for item in target_list:
                if item.get('class_id') == class_id:
                    pts = item.get('points', [])
                    qpts = []
                    for p in pts:
                        try:
                            if isinstance(p, (list, tuple)) and len(p) >= 2:
                                qpts.append(QPointF(float(p[0]), float(p[1])))
                        except:
                            pass
                    if qpts:
                        painter.drawPolygon(QPolygonF(qpts))
                        
            # Restore structural elements if we are modifying rooms so they stay visibly on top
            if is_room:
                painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
                for r in target_list:
                    if r.get('label') in ["Wall", "Railing"]:
                        cid = r.get('class_id', -1)
                        if cid == class_id:
                            continue # Already drawn above
                            
                        if 0 <= cid < len(self.room_colors):
                            c_str = self.room_colors[cid]
                        else:
                            c_str = (100, 100, 100)
                            
                        painter.setBrush(QColor(c_str[0], c_str[1], c_str[2], 140))
                        
                        pts = r.get('points', [])
                        qpts = []
                        for p in pts:
                            try:
                                if isinstance(p, (list, tuple)) and len(p) >= 2:
                                    qpts.append(QPointF(float(p[0]), float(p[1])))
                            except:
                                pass
                        if qpts:
                            painter.drawPolygon(QPolygonF(qpts))
                            
            painter.end()

        # Update Viewer and Legend Canvas
        viewer.update_view()
        self.refresh_legend(viewer.boq_data)

    def _add_dynamic_items(self, layout, label_list, label_map, color_palette, is_room, clickable=True):
        item_type = 'room'
        if not clickable: 
            item_type = 'structure'
        elif not is_room:
            item_type = 'icon'

        for label_name in label_list:
            class_id = label_map[label_name]
            if 0 <= class_id < len(color_palette):
                c = color_palette[class_id]
            else:
                c = (100, 100, 100)

            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 2, 0, 2)
            
            color_lbl = ColorLabel()
            color_lbl.setFixedSize(14, 14)
            hex_c = f"#{c[0]:02x}{c[1]:02x}{c[2]:02x}"
            color_lbl.setStyleSheet(f"background-color: {hex_c}; border-radius: 2px;")
            color_lbl.setCursor(Qt.PointingHandCursor)
            color_lbl.setToolTip("Double-click to change color")
            # Connect the color label double click event to our new method
            color_lbl.doubleClicked.connect(lambda cid=class_id, r=is_room, cur_c=c: self.change_category_color(cid, r, cur_c))
            row_layout.addWidget(color_lbl)

            if clickable:
                btn = LegendButton(label_name)
                btn.setCheckable(True) 
                btn.setCursor(Qt.PointingHandCursor)
                btn.setStyleSheet(self._get_btn_style(False))
                btn.clicked.connect(lambda checked, b=btn, n=label_name, r=is_room: self.handle_click(b, n, r))
                btn.doubleClicked.connect(lambda n=label_name, r=is_room: self.rename_label(n, r))
                self.buttons[label_name] = btn
                row_layout.addWidget(btn)
            else:
                lbl = QLabel(label_name)
                lbl.setStyleSheet("color: white; font-size: 11px; padding: 4px 8px;")
                row_layout.addWidget(lbl)
            
            row_layout.addStretch()
            
            btn_prop = QPushButton()
            btn_prop.setIcon(qta.icon('fa5s.wrench', color='#aaaaaa'))
            btn_prop.setFixedSize(24, 24)
            btn_prop.setCursor(Qt.PointingHandCursor)
            btn_prop.setToolTip(f"{label_name} Properties")
            btn_prop.setStyleSheet("""
                QPushButton { background: transparent; border: none; }
                QPushButton:hover { background: rgba(255, 255, 255, 30); border-radius: 4px; }
            """)
            btn_prop.clicked.connect(lambda checked, n=label_name, t=item_type: self.open_properties(n, t))
            row_layout.addWidget(btn_prop)

            # Add Delete Button for all items that are not walls/railings (implied by clickable)
            if clickable and label_name not in ["Wall", "Railing"]:
                btn_del = QPushButton()
                btn_del.setIcon(qta.icon('fa5s.trash-alt', color='#d9534f'))
                btn_del.setFixedSize(24, 24)
                btn_del.setCursor(Qt.PointingHandCursor)
                btn_del.setToolTip(f"Delete all {label_name}s")
                btn_del.setStyleSheet("""
                    QPushButton { background: transparent; border: none; }
                    QPushButton:hover { background: rgba(255, 0, 0, 30); border-radius: 4px; }
                """)
                btn_del.clicked.connect(lambda checked, n=label_name, r=is_room: self.delete_label_instances(n, r))
                row_layout.addWidget(btn_del)

            layout.addWidget(row)

    def rename_label(self, old_name, is_room):
        main_win = self.window()
        viewer = main_win.current_widget() if hasattr(main_win, 'current_widget') else None
        
        if not isinstance(viewer, DocumentViewer) or not viewer.boq_data:
            return

        new_name, ok = QInputDialog.getText(self, "Rename", f"Enter new name for '{old_name}':", text=old_name)
        
        if not ok or not new_name.strip() or new_name.strip() == old_name:
            return
            
        new_name = new_name.strip()
        data_key = 'rooms' if is_room else 'icons'
        target_list = viewer.boq_data.get(data_key, [])

        # Update JSON Objects
        for item in target_list:
            if item.get('label') == old_name:
                item['label'] = new_name

        # Save to File
        if viewer.json_data_path:
            try:
                with open(viewer.json_data_path, 'w') as f:
                    json.dump(viewer.boq_data, f, indent=4)
            except Exception as e:
                print(f"Error saving JSON after rename: {e}")

        # Update Viewer Selection State if it was active
        if is_room and viewer.selected_room_class == old_name:
            viewer.selected_room_class = new_name
        elif not is_room and viewer.selected_item_class == old_name:
            viewer.selected_item_class = new_name

        viewer.update_view()
        self.refresh_legend(viewer.boq_data)

    def delete_label_instances(self, label_name, is_room):
        main_win = self.window()
        viewer = main_win.current_widget() if hasattr(main_win, 'current_widget') else None
        
        if not isinstance(viewer, DocumentViewer) or not viewer.boq_data:
            return

        reply = QMessageBox.question(self, "Confirm Delete",
                                     f"Are you sure you want to delete all instances of '{label_name}'?",
                                     QMessageBox.Yes | QMessageBox.No)
        if reply != QMessageBox.Yes:
            return

        data_key = 'rooms' if is_room else 'icons'
        target_list = viewer.boq_data.get(data_key, [])

        items_to_remove = [item for item in target_list if item.get('label') == label_name]

        if not items_to_remove:
            return

        # Prepare for erasing the polygons off the segmentation mask
        target_pixmap = viewer.room_pixmap if is_room else viewer.item_pixmap
        painter = None
        
        if target_pixmap and not target_pixmap.isNull():
            painter = QPainter(target_pixmap)
            painter.setCompositionMode(QPainter.CompositionMode_Clear)
            painter.setBrush(Qt.black)
            painter.setPen(Qt.NoPen)

        for item in items_to_remove:
            target_list.remove(item)

            if painter:
                points = item.get('points', [])
                qpts = []
                for p in points:
                    try:
                        if isinstance(p, (list, tuple)) and len(p) >= 2:
                            qpts.append(QPointF(float(p[0]), float(p[1])))
                    except:
                        pass
                
                if qpts:
                    painter.drawPolygon(QPolygonF(qpts))
                    
        # Restore structural elements (Walls, Railings)
        if painter and is_room:
            painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
            for r in target_list:
                if r.get('label') in ["Wall", "Railing"]:
                    class_id = r.get('class_id', -1)
                    if 0 <= class_id < len(self.room_colors):
                        c = self.room_colors[class_id]
                    else:
                        c = (100, 100, 100)
                    
                    painter.setBrush(QColor(c[0], c[1], c[2], 140))
                    painter.setPen(Qt.NoPen)
                    
                    pts = r.get('points', [])
                    qpts = []
                    for p in pts:
                        try:
                            if isinstance(p, (list, tuple)) and len(p) >= 2:
                                qpts.append(QPointF(float(p[0]), float(p[1])))
                        except:
                            pass
                    if qpts:
                        painter.drawPolygon(QPolygonF(qpts))

        if painter:
            painter.end()

        # Save JSON changes
        if viewer.json_data_path:
            try:
                with open(viewer.json_data_path, 'w') as f:
                    json.dump(viewer.boq_data, f, indent=4)
            except Exception as e:
                print(f"Error saving JSON after deletion: {e}")

        # Clear viewer selection if we just deleted the active selection
        if is_room and viewer.selected_room_class == label_name:
            viewer.select_room_type(None)
        elif not is_room and viewer.selected_item_class == label_name:
            viewer.select_item_type(None)

        viewer.update_view()
        self.refresh_legend(viewer.boq_data)

    def open_properties(self, label_name, item_type):
        main_win = self.window()
        viewer = None
        
        if hasattr(main_win, 'current_widget'):
            viewer = main_win.current_widget()
            
        if not isinstance(viewer, DocumentViewer):
            return
            
        dialog = MaterialAssignmentDialog(label_name, item_type, viewer, self)
        dialog.exec()
        
        if viewer and viewer.boq_data:
            self.refresh_legend(viewer.boq_data)

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
        if hasattr(main_win, 'current_widget'):
            viewer = main_win.current_widget()
        if isinstance(viewer, DocumentViewer):
            target = name if is_active else None
            if is_room:
                viewer.select_room_type(target)
                viewer.select_item_type(None)
            else:
                viewer.select_item_type(target)
                viewer.select_room_type(None)

    def set_visibility(self, show_rooms, show_items):
        self.rooms_wrapper.setVisible(show_rooms)
        self.items_wrapper.setVisible(show_items)
        
        has_structures = self.structure_layout.count() > 0
        self.structure_container.setVisible(has_structures)
        self.lbl_structures.setVisible(has_structures)
        
        self.btn_toggle_rooms.setChecked(show_rooms)
        self.btn_toggle_items.setChecked(show_items)
        self.btn_toggle_rooms.setStyleSheet(self._get_btn_style(show_rooms))
        self.btn_toggle_items.setStyleSheet(self._get_btn_style(show_items))