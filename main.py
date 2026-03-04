import sys
import os
import ctypes  # <--- NEW IMPORT
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon
from ui.main_window import PDFViewerApp

def main():
    # --- TASKBAR ICON FIX FOR WINDOWS ---
    # This tells Windows to treat this script as a distinct app, 
    # overriding the default python.exe taskbar icon.
    if os.name == 'nt': 
        myappid = 'mycompany.boqviewer.app.1.0' # Arbitrary unique ID string
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
    # ------------------------------------

    app = QApplication(sys.argv)
    
    # Use absolute path to guarantee the icon is found regardless of where you run the script from
    base_dir = os.path.dirname(os.path.abspath(__file__))
    icon_path = os.path.join(base_dir, "resources", "logo.ico")
    
    # Set Global Application Icon
    app.setWindowIcon(QIcon(icon_path))
    
    # Load Stylesheet
    try:
        with open(os.path.join(base_dir, "style.qss"), "r") as f:
            app.setStyleSheet(f.read())
    except FileNotFoundError:
        print("Warning: style.qss not found. Using default style.")

    window = PDFViewerApp()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()