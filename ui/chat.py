import requests
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit, QLineEdit
)
from PySide6.QtGui import QTextCursor
from PySide6.QtCore import QThread, Signal, Qt
from .viewer import DocumentViewer

class ChatWorker(QThread):
    finished = Signal(str)
    error = Signal(str)

    def __init__(self, prompt, model="phi4-mini"):
        super().__init__()
        self.prompt = prompt
        self.model = model

    def run(self):
        try:
            response = requests.post("http://localhost:11434/api/generate", 
                json={
                    "model": self.model,
                    "prompt": self.prompt,
                    "stream": False
                }, timeout=60)
            
            if response.status_code == 200:
                answer = response.json().get("response", "No response.")
                self.finished.emit(answer)
            else:
                self.error.emit(f"Error {response.status_code}: Could not reach Ollama.")
        except Exception as e:
            self.error.emit(f"Connection Error: {str(e)}")

class AIChatPanel(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        
        # Header
        header_lbl = QLabel("<b>Floorplan Assistant</b>")
        header_lbl.setAlignment(Qt.AlignCenter)
        layout.addWidget(header_lbl)
        
        # Chat History Area
        self.chat_history = QTextEdit()
        self.chat_history.setReadOnly(True)
        # Remove default border to make it look cleaner
        layout.addWidget(self.chat_history)
        
        # Input Field
        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("Ask about the floorplan...")
        self.input_field.returnPressed.connect(self.send_message)
        layout.addWidget(self.input_field)
        
        # Buttons Layout (Ask + Clear)
        btn_layout = QHBoxLayout()
        
        self.send_btn = QPushButton("Ask")
        self.send_btn.clicked.connect(self.send_message)
        # Make the Ask button prominent
        self.send_btn.setStyleSheet("background-color: #0078d7; color: white; font-weight: bold;")
        
        self.clear_btn = QPushButton("Clear Chat")
        self.clear_btn.clicked.connect(self.clear_current_chat)
        self.clear_btn.setStyleSheet("background-color: #f0f0f0; color: #333;")
        
        btn_layout.addWidget(self.send_btn, stretch=3)
        btn_layout.addWidget(self.clear_btn, stretch=1)
        
        layout.addLayout(btn_layout)
        
        self.current_viewer = None
        self.worker = None

    def set_active_viewer(self, viewer):
        """Called when the tab switches. Loads the specific history for this tab."""
        self.current_viewer = viewer
        self.refresh_display()

    def clear_current_chat(self):
        """Clears the history for the active tab."""
        if self.current_viewer:
            self.current_viewer.chat_log = []
        self.refresh_display()

    def append_bubble(self, role, text, is_thinking=False):
        """
        Formats the message as an HTML bubble.
        Qt's rich text engine is limited, so we use tables for layout/backgrounds.
        """
        if role == "You":
            # Right aligned, Blue bubble
            color = "#dcf8c6" # Light Green/Blueish
            align = "right"
            text_color = "black"
            # Add some non-breaking spaces for padding visual
            formatted_text = f"""
            <div align="{align}">
                <table style="background-color: {color}; border-radius: 10px; margin-left: 50px;">
                    <tr>
                        <td style="padding: 10px; color: {text_color}; font-size: 13px;">
                            {text}
                        </td>
                    </tr>
                </table>
            </div>
            <br>
            """
        else:
            # Left aligned, Gray bubble
            color = "#e5e5ea" # iOS Gray
            align = "left"
            text_color = "black"
            formatted_text = f"""
            <div align="{align}">
                <table style="background-color: {color}; border-radius: 10px; margin-right: 50px;">
                    <tr>
                        <td style="padding: 10px; color: {text_color}; font-size: 13px;">
                            {text}
                        </td>
                    </tr>
                </table>
            </div>
            <br>
            """

        # Append to the text edit
        cursor = self.chat_history.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.chat_history.setTextCursor(cursor)
        self.chat_history.insertHtml(formatted_text)
        self.chat_history.moveCursor(QTextCursor.End)

    def refresh_display(self):
        """Clears and rebuilds the chat window from the viewer's log."""
        self.chat_history.clear()
        if not self.current_viewer:
            self.chat_history.setHtml("<i style='color:gray'>No active document.</i>")
            self.input_field.setEnabled(False)
            self.send_btn.setEnabled(False)
            self.clear_btn.setEnabled(False)
            return
        
        self.input_field.setEnabled(True)
        self.send_btn.setEnabled(True)
        self.clear_btn.setEnabled(True)
        
        # Reload history
        if hasattr(self.current_viewer, 'chat_log'):
            for role, text in self.current_viewer.chat_log:
                self.append_bubble(role, text)

    def send_message(self):
        user_text = self.input_field.text()
        if not user_text: return
        
        if not self.current_viewer: return

        # 1. Update UI Immediately
        self.append_bubble("You", user_text)
        
        # Show a temporary "Thinking..." bubble
        self.append_bubble("AI", "<i>Thinking...</i>")
        
        self.input_field.clear()
        self.input_field.setEnabled(False) 
        self.send_btn.setEnabled(False)

        # 2. Save User Message to History
        if hasattr(self.current_viewer, 'chat_log'):
            self.current_viewer.chat_log.append(("You", user_text))

        # 3. Prepare Context & History for the AI
        context_data = {}
        if isinstance(self.current_viewer, DocumentViewer) and self.current_viewer.has_analysis_data:
            context_data = self.current_viewer.get_scaled_boq_data()
        
        history_str = ""
        if hasattr(self.current_viewer, 'chat_log'):
            # Send history excluding the current query (to avoid duplication in prompt logic)
            for role, text in self.current_viewer.chat_log[:-1]:
                history_str += f"{role}: {text}\n"

        prompt = f"""
        You are an architectural assistant. 
        Context Data: {context_data}
        
        Conversation History:
        {history_str}
        
        Current User Question: {user_text}
        
        Please answer the Current User Question based on the Data and History. Keep answers concise.
        """
        
        # 4. Start Thread
        self.worker = ChatWorker(prompt)
        self.worker.finished.connect(self.on_worker_finished)
        self.worker.error.connect(self.on_worker_error)
        self.worker.start()

    def on_worker_finished(self, answer):
        # Remove the temporary "Thinking..." (Simplest way is to refresh from log + new msg)
        # But since we haven't saved "Thinking..." to the log, we can just save the REAL answer
        # and refresh.
        
        if self.current_viewer:
            self.current_viewer.chat_log.append(("AI", answer))
        
        self.refresh_display()
        
        self.input_field.setEnabled(True)
        self.send_btn.setEnabled(True)
        self.input_field.setFocus()

    def on_worker_error(self, err_msg):
        if self.current_viewer:
             self.current_viewer.chat_log.append(("AI", f"[Error] {err_msg}"))
        
        self.refresh_display()
        self.input_field.setEnabled(True)
        self.send_btn.setEnabled(True)