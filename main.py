import sys
import os
import ctypes
import time
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QFrame, QLabel, QProgressBar
)
from PySide6.QtGui import QPixmap, QIcon
from PySide6.QtCore import Qt

class AcrylicSplashScreen(QWidget):
    """Custom Splash Screen with a rounded, semi-transparent background."""
    def __init__(self, logo_path):
        super().__init__()
        
        # 1. Window setup for frameless, transparent background
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.SplashScreen)
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        # Main layout (invisible, just holds the styled container)
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        
        # 2. The Background Container
        self.container = QFrame(self)
        self.container.setObjectName("BackgroundContainer")

        self.container.setStyleSheet("""
            #BackgroundContainer {
                background-color: rgba(30, 30, 30, 200); /* Dark semi-transparent */
                border-radius: 20px; /* Rounded edges */
                border: 1px solid rgba(255, 255, 255, 40); /* Subtle light rim */
            }
        """)
        
        # Layout inside the container
        container_layout = QVBoxLayout(self.container)
        container_layout.setContentsMargins(50, 50, 50, 40)
        container_layout.setSpacing(35) # THIS IS THE GAP between logo and progress bar
        
        # 3. Logo
        self.logo_label = QLabel()
        pixmap = QPixmap(logo_path)
        if not pixmap.isNull():
            # Scale logo to reasonable size
            pixmap = pixmap.scaled(400, 300, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        else:
            pixmap = QPixmap(400, 150)
            pixmap.fill(Qt.transparent)
            
        self.logo_label.setPixmap(pixmap)
        self.logo_label.setAlignment(Qt.AlignCenter)
        
        # 4. Progress Bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(12) # Slim, modern progress bar
        self.progress_bar.setTextVisible(False) # Hide the text inside the bar
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                background-color: rgba(255, 255, 255, 30);
                border-radius: 6px;
                border: none;
            }
            QProgressBar::chunk {
                background-color: #fb9a44; /* Your brand orange */
                border-radius: 6px;
            }
        """)
        
        # 5. Status Message Label
        self.message_label = QLabel("Starting up...")
        self.message_label.setAlignment(Qt.AlignCenter)
        self.message_label.setStyleSheet("color: rgba(255, 255, 255, 200); font-size: 13px; font-weight: bold;")
        
        # Add widgets to container
        container_layout.addWidget(self.logo_label)
        container_layout.addWidget(self.progress_bar)
        container_layout.addWidget(self.message_label)
        
        main_layout.addWidget(self.container)

    def set_progress(self, value, message):
        """Helper to update the bar and text easily."""
        self.progress_bar.setValue(value)
        self.message_label.setText(message)

def main():
    if os.name == 'nt': 
        myappid = 'geojeesan.boqviewer.app.1.0' 
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)

    # Initialize the app immediately
    app = QApplication(sys.argv)
    base_dir = os.path.dirname(os.path.abspath(__file__))
    
    # 1. Setup and Show Custom Splash Screen
    logo_path = os.path.join(base_dir, "resources", "logo.png")
    splash = AcrylicSplashScreen(logo_path)
    splash.show()
    app.processEvents() # Force draw the splash screen

    # 2. Deferred Heavy Imports
    splash.set_progress(15, "Loading core UI components...")
    app.processEvents()
    
    # IMPORT HERE: Freezes happen here, but the splash is already on screen
    from ui.main_window import PDFViewerApp
    
    splash.set_progress(50, "Initializing modules and database...")
    app.processEvents()
    
    # Small sleep just to make the splash visually perceptible if imports are fast
    time.sleep(0.3) 
    
    splash.set_progress(80, "Preparing workspace...")
    app.processEvents()

    # 3. Global Application Icon & Stylesheet
    icon_path = os.path.join(base_dir, "resources", "logo.png")
    app.setWindowIcon(QIcon(icon_path))
    
    try:
        with open(os.path.join(base_dir, "style.qss"), "r") as f:
            app.setStyleSheet(f.read())
    except FileNotFoundError:
        pass

    # 4. Show Main Window and Close Splash
    window = PDFViewerApp()
    
    splash.set_progress(100, "Ready!")
    app.processEvents()
    time.sleep(0.2) # Let the user see it hit 100%
    
    window.show()
    splash.close() # Close our custom widget
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()