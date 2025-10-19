import sys
import fitz  # PyMuPDF
from PIL import Image
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QScrollArea, QLabel, QFileDialog, QTabWidget, QSplitter,
    QFrame, QTabBar, QPushButton
)
from PySide6.QtGui import QPixmap, QImage, QIcon, QWheelEvent
from PySide6.QtCore import Qt, QEvent

# --- Main Application Window ---
class MainWindow(QMainWindow):
    """The main window of the application that holds the tabbed document viewers."""
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Document Viewer")
        self.setGeometry(100, 100, 1200, 800)
        self.setWindowIcon(self._create_default_icon())

        # Central widget to hold everything
        self.tab_widget = QTabWidget()
        self.tab_widget.setTabsClosable(True)
        self.tab_widget.setMovable(True)
        self.tab_widget.tabCloseRequested.connect(self.close_tab)
        self.setCentralWidget(self.tab_widget)

        add_button = QPushButton("+")
        add_button.setFixedSize(26, 26)
        add_button.setStyleSheet("""
            QPushButton {
                font-size: 18px;
                font-weight: bold;
                border-radius: 2px;
            }
            QPushButton:hover { background-color: #2b2c37; }
            QPushButton:pressed { background-color: #2b2c37; }
        """)
        add_button.clicked.connect(self.open_file)
        # Container for the add button to control its position
        button_container = QWidget()
        button_layout = QHBoxLayout(button_container)
        button_layout.setContentsMargins(0, 0, 0, 0)
        button_layout.addWidget(add_button)
        button_layout.addStretch()

        self.tab_widget.setCornerWidget(button_container, Qt.TopRightCorner)

        # Placeholder welcome tab
        self.show_welcome_tab()

    def _create_default_icon(self):
        """Creates a simple default icon to avoid needing an external file."""
        pixmap = QPixmap(16, 16)
        pixmap.fill(Qt.transparent)
        from PySide6.QtGui import QPainter, QColor
        painter = QPainter(pixmap)
        painter.setBrush(QColor("lightblue")); painter.setPen(Qt.NoPen)
        painter.drawRect(3, 1, 10, 14)
        painter.setBrush(QColor("white")); painter.drawRect(5, 3, 6, 4)
        painter.setBrush(QColor("lightgrey")); painter.drawRect(5, 9, 6, 1)
        painter.drawRect(5, 11, 6, 1); painter.end()
        return QIcon(pixmap)

    def open_file(self):
        """Open a file dialog and load the selected file in a new tab."""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Open File", "",
            "All Supported Files (*.pdf *.png *.jpg *.jpeg *.bmp *.gif);;PDF Files (*.pdf);;Image Files (*.png *.jpg *.jpeg *.bmp *.gif)"
        )
        if file_path:
            if self.tab_widget.count() == 1 and self.tab_widget.widget(0).objectName() == "welcome_tab":
                self.tab_widget.removeTab(0)

            viewer = DocumentViewer(file_path)
            file_name = file_path.split('/')[-1]
            self.tab_widget.addTab(viewer, file_name)
            self.tab_widget.setCurrentWidget(viewer)

    def close_tab(self, index):
        widget = self.tab_widget.widget(index)
        if widget is not None:
            widget.deleteLater()
        self.tab_widget.removeTab(index)
        if self.tab_widget.count() == 0:
            self.show_welcome_tab()

    def show_welcome_tab(self):
        welcome_widget = QWidget()
        welcome_widget.setObjectName("welcome_tab")
        layout = QVBoxLayout(welcome_widget); layout.setAlignment(Qt.AlignCenter)
        title = QLabel("Document Viewer"); title.setStyleSheet("font-size: 32px; font-weight: bold;")
        subtitle = QLabel("Press the <b>+</b> button to load a PDF or image.")
        subtitle.setStyleSheet("font-size: 16px;")
        layout.addWidget(title); layout.addWidget(subtitle)
        self.tab_widget.addTab(welcome_widget, "Welcome")
        self.tab_widget.tabBar().setTabButton(0, QTabBar.RightSide, None)


# --- Document Viewer Widget (for each tab) ---
class DocumentViewer(QWidget):
    def __init__(self, file_path):
        super().__init__()
        self.file_path = file_path
        self.pdf_document = None
        self.image_item = None
        self.thumbnail_labels = []
        self.current_page = 0
        self.zoom_level = 1.0
        self._initial_fit_done = False

        main_layout = QHBoxLayout(self); main_layout.setContentsMargins(0, 0, 0, 0)
        splitter = QSplitter(Qt.Horizontal); main_layout.addWidget(splitter)

        self.thumbnail_scroll_area = QScrollArea(); self.thumbnail_scroll_area.setWidgetResizable(True)
        self.thumbnail_scroll_area.setObjectName("thumbnailScrollArea")
        self.thumbnail_widget = QWidget(); self.thumbnail_layout = QVBoxLayout(self.thumbnail_widget)
        self.thumbnail_layout.setAlignment(Qt.AlignTop); self.thumbnail_scroll_area.setWidget(self.thumbnail_widget)
        self.thumbnail_scroll_area.setMinimumWidth(150); self.thumbnail_scroll_area.setMaximumWidth(250)

        self.main_view_scroll_area = QScrollArea()
        self.main_view_scroll_area.setObjectName("mainViewScrollArea")
        self.main_view_label = QLabel(); self.main_view_label.setAlignment(Qt.AlignCenter)
        self.main_view_scroll_area.setWidget(self.main_view_label)

        # --- Zoom Feature: Capture wheel events for zooming ---
        self.main_view_scroll_area.viewport().installEventFilter(self)

        splitter.addWidget(self.thumbnail_scroll_area); splitter.addWidget(self.main_view_scroll_area)
        splitter.setSizes([150, 1050])

        self.load_document()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not self._initial_fit_done:
            self.fit_to_width()
            self._initial_fit_done = True

    # --- Zoom Feature: Intercept wheel events on the viewport for zooming ---
    def eventFilter(self, source, event):
        if source == self.main_view_scroll_area.viewport() and event.type() == QEvent.Type.Wheel:
            # We must check the instance type to access specific event attributes safely.
            if isinstance(event, QWheelEvent):
                if QApplication.keyboardModifiers() == Qt.KeyboardModifier.ControlModifier:
                    # Get the position of the mouse cursor relative to the viewport
                    mouse_pos_viewport = event.position()

                    # Get the current scrollbar positions
                    h_bar = self.main_view_scroll_area.horizontalScrollBar()
                    v_bar = self.main_view_scroll_area.verticalScrollBar()

                    # Calculate the scene position (the point on the unscaled image) under the cursor
                    scene_x = (h_bar.value() + mouse_pos_viewport.x()) / self.zoom_level
                    scene_y = (v_bar.value() + mouse_pos_viewport.y()) / self.zoom_level

                    # --- Smooth Zoom Calculation ---
                    angle = event.angleDelta().y()
                    zoom_factor = 1.001 ** angle # Exponential for smoothness

                    self.zoom_level *= zoom_factor

                    # --- Update the display with the new zoom level ---
                    self.update_display()

                    # --- Center zoom on cursor ---
                    # Calculate the new pixel position of the scene point
                    new_pixel_x = scene_x * self.zoom_level
                    new_pixel_y = scene_y * self.zoom_level

                    # Set the scrollbars to keep the scene point under the cursor
                    h_bar.setValue(int(new_pixel_x - mouse_pos_viewport.x()))
                    v_bar.setValue(int(new_pixel_y - mouse_pos_viewport.y()))

                    return True  # Event was handled
        return super().eventFilter(source, event)

    def fit_to_width(self):
        """Adjust zoom level so the document width fits the viewport."""
        viewport_width = self.main_view_scroll_area.viewport().width()
        if viewport_width <= 0: return

        if self.pdf_document and len(self.pdf_document) > 0:
            page = self.pdf_document.load_page(self.current_page)
            if page.rect.width > 0:
                self.zoom_level = viewport_width / page.rect.width
                self.update_display()
        elif self.image_item:
            if self.image_item.width > 0:
                self.zoom_level = viewport_width / self.image_item.width
                self.update_display()

    def update_display(self):
        """Re-renders the current view based on the current zoom level."""
        if self.pdf_document:
            self.show_page(self.current_page)
        elif self.image_item:
            self.display_image()

    def load_document(self):
        if self.file_path.lower().endswith('.pdf'): self.load_pdf()
        else: self.load_image()

    def load_pdf(self):
        try:
            self.pdf_document = fitz.open(self.file_path)
            for page_num in range(len(self.pdf_document)):
                page = self.pdf_document.load_page(page_num)
                pix = page.get_pixmap(dpi=36)
                q_image = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888)
                thumb_label = QLabel()
                thumb_label.setPixmap(QPixmap.fromImage(q_image).scaledToWidth(120, Qt.TransformationMode.SmoothTransformation))
                thumb_label.setFrameShape(QFrame.Shape.StyledPanel)
                thumb_label.mousePressEvent = lambda event, p=page_num: self.show_page(p)
                self.thumbnail_layout.addWidget(thumb_label); self.thumbnail_labels.append(thumb_label)
            if len(self.pdf_document) > 0: self.show_page(0)
        except Exception as e: self.main_view_label.setText(f"Error loading PDF: {e}")

    def load_image(self):
        try:
            self.image_item = Image.open(self.file_path)
            # Create a single thumbnail for the image
            thumb_pixmap = QPixmap(self.file_path).scaledToWidth(120, Qt.TransformationMode.SmoothTransformation)
            thumb_label = QLabel(); thumb_label.setPixmap(thumb_pixmap)
            thumb_label.setFrameShape(QFrame.Shape.StyledPanel)
            self.thumbnail_layout.addWidget(thumb_label); self.thumbnail_labels.append(thumb_label)
            self.display_image() # Display the main image
        except Exception as e: self.main_view_label.setText(f"Error loading image: {e}")

    def display_image(self):
        """Displays the loaded image, scaled by the current zoom level."""
        if not self.image_item: return
        pixmap = QPixmap(self.file_path)
        new_width = int(pixmap.width() * self.zoom_level)
        scaled_pixmap = pixmap.scaledToWidth(new_width, Qt.TransformationMode.SmoothTransformation)
        self.main_view_label.setPixmap(scaled_pixmap)
        self.main_view_label.resize(scaled_pixmap.size())
        self.highlight_thumbnail(0)

    def show_page(self, page_num):
        if not self.pdf_document: return
        self.current_page = page_num
        page = self.pdf_document.load_page(page_num)
        matrix = fitz.Matrix(self.zoom_level, self.zoom_level)
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        q_image = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888)
        pixmap = QPixmap.fromImage(q_image)
        self.main_view_label.setPixmap(pixmap)
        self.main_view_label.resize(pixmap.size()) # Resize label to fit pixmap
        self.highlight_thumbnail(page_num)

    def highlight_thumbnail(self, index):
        for i, label in enumerate(self.thumbnail_labels):
            if i == index: label.setStyleSheet("border: 2px solid #0078d4;")
            else: label.setStyleSheet("")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    try:
        with open("style.qss", "r") as f:
            app.setStyleSheet(f.read())
    except FileNotFoundError:
        print("Stylesheet file 'style.qss' not found. Using default styles.")

    main_win = MainWindow()
    main_win.show()
    sys.exit(app.exec())

