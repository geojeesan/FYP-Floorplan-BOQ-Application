from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QComboBox, 
    QPushButton, QTableView, QMessageBox, QLabel, QFileDialog, QStyledItemDelegate, QStyle
)
from PySide6.QtSql import QSqlDatabase, QSqlTableModel
from PySide6.QtCore import Qt, QByteArray, QSize
from PySide6.QtGui import QPixmap

class ImageDelegate(QStyledItemDelegate):
    """Custom delegate to render BLOB data as image thumbnails."""
    
    def paint(self, painter, option, index):
        # Fetch the data for display
        data = index.data(Qt.DisplayRole)
        
        # 1. Fill the background first to prevent visual artifacts
        if option.state & QStyle.State_Selected:
            painter.fillRect(option.rect, option.palette.highlight())
        else:
            painter.fillRect(option.rect, option.palette.base())
            
        painted_image = False
        
        # 2. Check if there is data and try to parse it as an image
        if data:
            # Handle both QByteArray (Qt) and bytes (Python)
            byte_array = data.data() if isinstance(data, QByteArray) else data
            
            if isinstance(byte_array, bytes):
                pixmap = QPixmap()
                pixmap.loadFromData(byte_array)
                
                if not pixmap.isNull():
                    margin = 4
                    rect = option.rect.adjusted(margin, margin, -margin, -margin)
                    scaled_pixmap = pixmap.scaled(rect.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    
                    x = rect.x() + (rect.width() - scaled_pixmap.width()) // 2
                    y = rect.y() + (rect.height() - scaled_pixmap.height()) // 2
                    
                    painter.drawPixmap(x, y, scaled_pixmap)
                    painted_image = True
        
        # 3. Fallback text if no valid image exists
        if not painted_image:
            painter.save()
            if option.state & QStyle.State_Selected:
                painter.setPen(option.palette.highlightedText().color())
            else:
                painter.setPen(Qt.gray)
            painter.drawText(option.rect, Qt.AlignCenter, "Double-click\nto add image")
            painter.restore()

    def sizeHint(self, option, index):
        # Enforce a minimum size for image cells
        return QSize(100, 100)

    def createEditor(self, parent, option, index):
        # CRITICAL FIX: Return None to prevent the default text box from spawning!
        # This stops the raw binary text from rendering and corrupting the BLOB on click-away.
        return None


class DatabaseEditorDialog(QDialog):
    def __init__(self, db_path="boq_materials.db", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Material Database Editor")
        self.resize(1000, 600)
        
        self.db = QSqlDatabase.addDatabase("QSQLITE")
        self.db.setDatabaseName(db_path)
        if not self.db.open():
            QMessageBox.critical(self, "Database Error", "Could not open database.")
            return
            
        self.layout = QVBoxLayout(self)
        
        # Top Selector
        self.top_layout = QHBoxLayout()
        self.top_layout.addWidget(QLabel("Select Category:"))
        
        self.table_selector = QComboBox()
        self.table_selector.addItems([
            "Floors", "Walls", "Doors", "Windows", "Fixtures", 
            "Electrical Appliances", "Closet", "Toilet", "Sink", 
            "Sauna Bench", "Fire Place", "Bathtub", "Chimney"
        ])
        self.table_selector.currentTextChanged.connect(self.load_table)
        self.top_layout.addWidget(self.table_selector)
        self.top_layout.addStretch()
        self.layout.addLayout(self.top_layout)
        
        # Model and View
        self.model = QSqlTableModel(self, self.db)
        self.model.setEditStrategy(QSqlTableModel.OnManualSubmit)
        
        self.table_view = QTableView()
        self.table_view.setModel(self.model)
        self.table_view.setAlternatingRowColors(True)
        self.table_view.verticalHeader().setDefaultSectionSize(100) 
        
        # Intercept double clicks for file selection
        self.table_view.doubleClicked.connect(self.on_cell_double_clicked)
        
        self.image_delegate = ImageDelegate(self)
        self.layout.addWidget(self.table_view)
        
        # Bottom Buttons
        self.btn_layout = QHBoxLayout()
        self.btn_add = QPushButton("Add Row")
        self.btn_add.clicked.connect(self.add_row)
        
        self.btn_delete = QPushButton("Delete Row")
        self.btn_delete.clicked.connect(self.delete_row)
        
        self.btn_revert = QPushButton("Revert Changes")
        self.btn_revert.clicked.connect(self.model.revertAll)
        
        self.btn_submit = QPushButton("Save to Database")
        self.btn_submit.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold;")
        self.btn_submit.clicked.connect(self.submit_changes)
        
        self.btn_layout.addWidget(self.btn_add)
        self.btn_layout.addWidget(self.btn_delete)
        self.btn_layout.addStretch()
        self.btn_layout.addWidget(self.btn_revert)
        self.btn_layout.addWidget(self.btn_submit)
        
        self.layout.addLayout(self.btn_layout)
        
        self.load_table(self.table_selector.currentText())

    def load_table(self, table_name):
        self.model.setTable(f'"{table_name}"')
        self.model.select()
        self.table_view.hideColumn(0) # Hide ID
        
        # Dynamically apply the ImageDelegate to the appropriate columns
        for i in range(self.model.columnCount()):
            col_name = self.model.headerData(i, Qt.Horizontal)
            if col_name in ["image", "texture_for_3d"]:
                self.table_view.setItemDelegateForColumn(i, self.image_delegate)
                self.table_view.setColumnWidth(i, 120)
            else:
                self.table_view.setItemDelegateForColumn(i, None)

    def on_cell_double_clicked(self, index):
        col_name = self.model.headerData(index.column(), Qt.Horizontal)
        
        # Only trigger the file dialog for the image columns
        if col_name in ["image", "texture_for_3d"]:
            file_path, _ = QFileDialog.getOpenFileName(
                self, f"Select {col_name.replace('_', ' ').title()}", "", "Images (*.png *.jpg *.jpeg *.bmp)"
            )
            if file_path:
                with open(file_path, "rb") as f:
                    data = f.read()
                # Insert the binary data into the model
                self.model.setData(index, QByteArray(data), Qt.EditRole)
                
    def add_row(self):
        row = self.model.rowCount()
        self.model.insertRow(row)
        
    def delete_row(self):
        index = self.table_view.currentIndex()
        if index.isValid():
            self.model.removeRow(index.row())
            
    def submit_changes(self):
        if self.model.submitAll():
            QMessageBox.information(self, "Success", "Database updated successfully.")
        else:
            QMessageBox.warning(self, "Error", self.model.lastError().text())