import requests
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton, QTextEdit, QLineEdit
)
from .viewer import DocumentViewer

class AIChatPanel(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedWidth(300)
        layout = QVBoxLayout(self)
        
        layout.addWidget(QLabel("<b>Floorplan Assistant</b>"))
        
        self.chat_history = QTextEdit()
        self.chat_history.setReadOnly(True)
        layout.addWidget(self.chat_history)
        
        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("Ask about the floorplan...")
        self.input_field.returnPressed.connect(self.send_message)
        layout.addWidget(self.input_field)
        
        self.send_btn = QPushButton("Ask")
        self.send_btn.clicked.connect(self.send_message)
        layout.addWidget(self.send_btn)

    def send_message(self):
        user_text = self.input_field.text()
        if not user_text: return
        
        self.chat_history.append(f"<b>You:</b> {user_text}")
        self.input_field.clear()
        
        # Get data from active tab
        main_win = self.window()
        viewer = main_win.tabs.currentWidget()
        
        context_data = {}
        if isinstance(viewer, DocumentViewer) and viewer.has_analysis_data:
            context_data = viewer.get_scaled_boq_data()
        
        prompt = f"""
        You are an architectural assistant. Use the following floorplan data to answer:
        Data: {context_data}
        User Question: {user_text}
        Keep answers concise. If areas are available, mention them.
        """
        
        try:
            response = requests.post("http://localhost:11434/api/generate", 
                json={
                    "model": "phi4-mini",
                    "prompt": prompt,
                    "stream": False
                }, timeout=50)
            
            if response.status_code == 200:
                answer = response.json().get("response", "No response.")
                self.chat_history.append(f"<b>AI:</b> {answer}")
            else:
                self.chat_history.append("<b>Error:</b> Could not reach Ollama.")
        except Exception as e:
            self.chat_history.append(f"<b>Error:</b> {str(e)}")