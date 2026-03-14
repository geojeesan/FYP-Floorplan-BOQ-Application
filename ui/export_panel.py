import os
import traceback
from PySide6.QtWidgets import QWidget, QVBoxLayout, QPushButton, QMessageBox, QLabel, QFileDialog
from PySide6.QtCore import Qt
import qtawesome as qta

# Try to import ezdxf for CAD generation
try:
    import ezdxf
    from ezdxf.enums import TextEntityAlignment  # <-- NEW: Required for newer ezdxf versions
    EZDXF_AVAILABLE = True
except ImportError:
    EZDXF_AVAILABLE = False


class ExportPanel(QWidget):
    def __init__(self, main_window=None):
        super().__init__()
        self.main_window = main_window
        
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignTop)
        layout.setSpacing(15)
        layout.setContentsMargins(5, 10, 5, 5)
        
        # Header
        header_lbl = QLabel("<b>Export & Reports</b>")
        header_lbl.setStyleSheet("font-size: 16px; margin-bottom: 5px;")
        layout.addWidget(header_lbl)
        
        # Export Buttons
        self.btn_qto = QPushButton(" Generate Quantity Take-off")
        self.btn_qto.setIcon(qta.icon('fa5s.file-excel', color='white'))
        
        self.btn_boq = QPushButton(" Generate BOQ")
        self.btn_boq.setIcon(qta.icon('fa5s.file-invoice-dollar', color='white'))
        
        self.btn_cad = QPushButton(" Export to CAD (.dxf)")
        self.btn_cad.setIcon(qta.icon('fa5s.drafting-compass', color='white'))
        
        # Styling for primary export buttons
        btn_style = """
            QPushButton {
                background-color: #4CAF50; 
                color: white; 
                font-size: 14px; 
                padding: 12px; 
                border-radius: 6px;
                font-weight: bold;
                text-align: left;
                padding-left: 15px;
            }
            QPushButton:hover { background-color: #45a049; }
        """
        
        # Styling for CAD button to distinguish it
        cad_style = """
            QPushButton {
                background-color: #2196F3; 
                color: white; 
                font-size: 14px; 
                padding: 12px; 
                border-radius: 6px;
                font-weight: bold;
                text-align: left;
                padding-left: 15px;
            }
            QPushButton:hover { background-color: #1e88e5; }
        """
        
        self.btn_qto.setStyleSheet(btn_style)
        self.btn_boq.setStyleSheet(btn_style)
        self.btn_cad.setStyleSheet(cad_style)
        
        # Function connections
        self.btn_qto.clicked.connect(self.generate_qto)
        self.btn_boq.clicked.connect(self.generate_boq)
        self.btn_cad.clicked.connect(self.export_cad)
        
        layout.addWidget(self.btn_qto)
        layout.addWidget(self.btn_boq)
        layout.addWidget(self.btn_cad)
        
        layout.addStretch()

    def generate_qto(self):
        QMessageBox.information(self, "Export", "Quantity Take-off (QTO) generation is coming soon!")

    def generate_boq(self):
        QMessageBox.information(self, "Export", "Bill of Quantities (BOQ) generation is coming soon!")

    def export_cad(self):
        if not EZDXF_AVAILABLE:
            QMessageBox.warning(
                self, 
                "Missing Dependency", 
                "The 'ezdxf' library is required to export to CAD.\n\nPlease install it using your terminal:\npip install ezdxf"
            )
            return
            
        viewer = self.main_window.current_widget() if self.main_window else None
        
        if not viewer or not getattr(viewer, 'boq_data', None):
            QMessageBox.warning(self, "Export Error", "No active analysis data to export. Please analyze a floorplan first.")
            return
            
        boq_data = viewer.boq_data
        
        # Determine scaling ratio. Use 1.0 if not calibrated
        ratio = float(getattr(viewer, 'pixel_to_unit_ratio', 1.0) or 1.0)
            
        # Open save dialog
        file_path, _ = QFileDialog.getSaveFileName(self, "Save CAD File", "", "DXF Files (*.dxf)")
        if not file_path:
            return
            
        try:
            # Create a new DXF document
            doc = ezdxf.new('R2010')
            msp = doc.modelspace()
            
            # Setup CAD Layers with standard index colors
            doc.layers.add(name="Rooms", color=3)       # Green
            doc.layers.add(name="Structures", color=1)  # Red (Walls/Railings)
            doc.layers.add(name="Icons", color=5)       # Blue
            doc.layers.add(name="Labels", color=7)      # White/Black
            
            # Dynamic text height equivalent to roughly 15 pixels in real-world units
            text_height = float(15 * ratio)
            
            def add_polygon_to_msp(item_list, default_layer):
                for item in item_list:
                    points = item.get('points', [])
                    if not points or len(points) < 3:
                        continue
                        
                    # Format points for CAD: Apply scale, invert Y axis, and FORCE standard floats
                    cad_points = [(float(p[0] * ratio), float(-p[1] * ratio)) for p in points]
                    
                    label = str(item.get('label', 'Unknown'))
                    
                    # Distinguish layers based on labels
                    layer = default_layer
                    if default_layer == "Rooms" and label in ["Wall", "Railing"]:
                        layer = "Structures"
                        
                    # Draw Polygon
                    msp.add_lwpolyline(cad_points, close=True, dxfattribs={'layer': layer})
                    
                    # Calculate Centroid for placing text (forcing float again)
                    cx = float(sum([p[0] for p in cad_points]) / len(cad_points))
                    cy = float(sum([p[1] for p in cad_points]) / len(cad_points))
                    
                    # Add Text Label inside the polygon using the Enum required by newer ezdxf versions
                    msp.add_text(
                        label, 
                        dxfattribs={'layer': 'Labels', 'height': text_height}
                    ).set_placement((cx, cy), align=TextEntityAlignment.MIDDLE_CENTER)
                    
            # Export data categories
            add_polygon_to_msp(boq_data.get('rooms', []), "Rooms")
            add_polygon_to_msp(boq_data.get('icons', []), "Icons")
            
            # Export manual floating text labels (if the user added any)
            if hasattr(viewer, 'manual_text_labels'):
                for txt_item in viewer.manual_text_labels:
                    pos = txt_item['pos']
                    text = str(txt_item['text'])
                    x, y = float(pos.x() * ratio), float(-pos.y() * ratio)
                    msp.add_text(
                        text, 
                        dxfattribs={'layer': 'Labels', 'height': text_height}
                    ).set_placement((x, y), align=TextEntityAlignment.MIDDLE_CENTER)

            # Save the document to the user's hard drive
            doc.saveas(file_path)
            QMessageBox.information(self, "Export Success", f"Successfully exported CAD file to:\n{file_path}")
            
        except Exception as e:
            # Full traceback logging if it fails again
            error_trace = traceback.format_exc()
            print("CAD Export Failed:\n", error_trace)
            QMessageBox.critical(
                self, 
                "Export Error", 
                f"Failed to generate DXF file:\n{str(e)}\n\nCheck your terminal for the full traceback details."
            )