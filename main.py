import sys
from PySide6.QtWidgets import QApplication
from ui.main_window import PDFViewerApp

def main():
    app = QApplication(sys.argv)
    
    # Load Stylesheet
    try:
        with open("style.qss", "r") as f:
            app.setStyleSheet(f.read())
    except FileNotFoundError:
        print("Warning: style.qss not found. Using default style.")

    window = PDFViewerApp()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()