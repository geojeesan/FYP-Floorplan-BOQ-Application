import sys
import subprocess
import threading
import re
from collections import Counter

import fitz  # PyMuPDF
from PIL import Image
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QScrollArea, QLabel, QFileDialog, QTabWidget, QSplitter,
    QFrame, QTabBar, QPushButton, QTextEdit, QLineEdit, QMessageBox
)
from PySide6.QtGui import QPixmap, QImage, QIcon, QWheelEvent
from PySide6.QtCore import Qt, QEvent

import easyocr
try:
    # Initialize the reader once. This will download models on first run.
    print("Loading EasyOCR model...")
    EASYOCR_READER = easyocr.Reader(['en'])
    _HAS_EASYOCR = True
    print("EasyOCR loaded successfully.")
except Exception as e:
    EASYOCR_READER = None
    _HAS_EASYOCR = False
    print(f"Failed to load EasyOCR. OCR will be disabled: {e}")

# ----------------- Utility functions for RAG -----------------

def extract_text_from_pdf(path):
    """Extracts text from every page of the PDF and returns as a single string."""
    try:
        doc = fitz.open(path)
        texts = []
        for i in range(len(doc)):
            page = doc.load_page(i)
            t = page.get_text("text")
            texts.append(t)
        return "\n\n".join(texts)
    except Exception as e:
        return "" 


def ocr_image(path):
    """Attempts OCR using EasyOCR if available."""
    if not _HAS_EASYOCR:
        return ""
    try:
        results = EASYOCR_READER.readtext(path) 
        
        # easyocr returns [bbox, text, prob] Extracting only text
        text_list = [item[1] for item in results]
        
        return "\n".join(text_list)
    except Exception as e:
        print(f"Error occurred during EasyOCR: {e}")
        return ""


def chunk_text(text, max_chars=1500, overlap=200):
    """Split text into chunks with overlap. Returns list of chunks."""
    if not text:
        return []
    text = text.replace('\r', '')
    start = 0
    chunks = []
    while start < len(text):
        end = start + max_chars
        chunk = text[start:end]
        chunks.append(chunk.strip())
        start = end - overlap
        if start < 0:
            start = 0
    return chunks


def score_chunk_by_query(chunk, query):
    """A naive relevance score by keyword overlap (case-insensitive)."""
    q_toks = re.findall(r"\w+", query.lower())
    if not q_toks:
        return 0
    chunk_toks = re.findall(r"\w+", chunk.lower())
    if not chunk_toks:
        return 0
    counter = Counter(chunk_toks)
    score = sum(counter[t] for t in q_toks)
    return score


def retrieve_top_chunks(chunks, query, top_k=3):
    """Return top_k chunks by naive score."""
    scored = [(score_chunk_by_query(c, query), i, c) for i, c in enumerate(chunks)]
    scored.sort(reverse=True)
    top = [c for s, i, c in scored[:top_k] if s > 0]
    return top


# ----------------- Ollama interaction -----------------

def call_ollama_llava(prompt, image_path=None, timeout=60):
    """
    Call ollama llava in non-interactive mode.
    If image_path is provided, it passes the image to the model.
    """
    try:
        # Standard command: ollama run <model> <prompt> [image_path]
        cmd = ["ollama", "run", "llava", prompt]
        
        if image_path:
            cmd.append(image_path)
            
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
        out = proc.stdout.decode("utf-8", errors="ignore")
        if not out:
            return proc.stderr.decode("utf-8", errors="ignore")
        return out
    except FileNotFoundError:
        return "Error: `ollama` CLI not found. Please install ollama and ensure it's on your PATH."
    except subprocess.TimeoutExpired:
        return "Error: ollama (llava) call timed out."
    except Exception as e:
        return f"Error calling ollama: {e}"



# ----------------- Main Application Window -----------------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Document Viewer with Chatbot")
        self.setGeometry(100, 100, 1400, 900)
        self.setWindowIcon(self._create_default_icon())

        self.tab_widget = QTabWidget()
        self.tab_widget.setTabsClosable(True)
        self.tab_widget.setMovable(True)
        self.tab_widget.tabCloseRequested.connect(self.close_tab)
        self.setCentralWidget(self.tab_widget)

        add_button = QPushButton("+")
        add_button.setFixedSize(26, 26)
        add_button.setStyleSheet("""
            QPushButton { font-size: 18px; font-weight: bold; border-radius: 2px; }
            QPushButton:hover { background-color: #2b2c37; }
        """)
        add_button.clicked.connect(self.open_file)
        button_container = QWidget()
        button_layout = QHBoxLayout(button_container)
        button_layout.setContentsMargins(0, 0, 0, 0)
        button_layout.addWidget(add_button); button_layout.addStretch()
        self.tab_widget.setCornerWidget(button_container, Qt.TopRightCorner)

        self.show_welcome_tab()

    def _create_default_icon(self):
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


# ----------------- Document Viewer + Chatbot per-tab -----------------
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

        # RAG related
        self.indexed_chunks = []
        self.indexed = False

        main_layout = QHBoxLayout(self); main_layout.setContentsMargins(0, 0, 0, 0)
        splitter = QSplitter(Qt.Horizontal); main_layout.addWidget(splitter)

        # Left: thumbnails
        self.thumbnail_scroll_area = QScrollArea(); self.thumbnail_scroll_area.setWidgetResizable(True)
        self.thumbnail_scroll_area.setObjectName("thumbnailScrollArea")
        self.thumbnail_widget = QWidget(); self.thumbnail_layout = QVBoxLayout(self.thumbnail_widget)
        self.thumbnail_layout.setAlignment(Qt.AlignTop); self.thumbnail_scroll_area.setWidget(self.thumbnail_widget)
        self.thumbnail_scroll_area.setMinimumWidth(150); self.thumbnail_scroll_area.setMaximumWidth(250)

        # Center: main view
        self.main_view_scroll_area = QScrollArea(); self.main_view_scroll_area.setObjectName("mainViewScrollArea")
        self.main_view_label = QLabel(); self.main_view_label.setAlignment(Qt.AlignCenter)
        self.main_view_scroll_area.setWidget(self.main_view_label)
        self.main_view_scroll_area.viewport().installEventFilter(self)

        center_container = QWidget(); center_layout = QVBoxLayout(center_container)
        center_layout.addWidget(self.main_view_scroll_area)

        # Right: chatbot
        self.chat_widget = self._create_chat_widget()
        self.chat_widget.setMinimumWidth(360); self.chat_widget.setMaximumWidth(520)

        splitter.addWidget(self.thumbnail_scroll_area)
        splitter.addWidget(center_container)
        splitter.addWidget(self.chat_widget)
        splitter.setSizes([150, 900, 350])

        self.load_document()

    def _create_chat_widget(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(8, 8, 8, 8)
        title = QLabel("Document Chatbot (Llava)")
        title.setStyleSheet("font-weight: bold; font-size: 16px;")
        layout.addWidget(title)

        # Indexing button
        index_btn = QPushButton("Index Document (for RAG)")
        index_btn.clicked.connect(self.index_document)
        layout.addWidget(index_btn)

        # Chat history
        self.chat_history = QTextEdit(); self.chat_history.setReadOnly(True)
        layout.addWidget(self.chat_history, 1)

        # Input + send
        h = QHBoxLayout()
        self.chat_input = QLineEdit(); self.chat_input.setPlaceholderText("Ask a question about the document...")
        send_btn = QPushButton("Send")
        send_btn.clicked.connect(self.on_send_clicked)
        h.addWidget(self.chat_input); h.addWidget(send_btn)
        layout.addLayout(h)

        return w

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not self._initial_fit_done:
            self.fit_to_width()
            self._initial_fit_done = True

    def eventFilter(self, source, event):
        if source == self.main_view_scroll_area.viewport() and event.type() == QEvent.Type.Wheel:
            if isinstance(event, QWheelEvent):
                if QApplication.keyboardModifiers() == Qt.KeyboardModifier.ControlModifier:
                    mouse_pos_viewport = event.position()
                    h_bar = self.main_view_scroll_area.horizontalScrollBar()
                    v_bar = self.main_view_scroll_area.verticalScrollBar()
                    scene_x = (h_bar.value() + mouse_pos_viewport.x()) / self.zoom_level
                    scene_y = (v_bar.value() + mouse_pos_viewport.y()) / self.zoom_level
                    angle = event.angleDelta().y()
                    zoom_factor = 1.001 ** angle
                    self.zoom_level *= zoom_factor
                    self.update_display()
                    new_pixel_x = scene_x * self.zoom_level
                    new_pixel_y = scene_y * self.zoom_level
                    h_bar.setValue(int(new_pixel_x - mouse_pos_viewport.x()))
                    v_bar.setValue(int(new_pixel_y - mouse_pos_viewport.y()))
                    return True
        return super().eventFilter(source, event)

    def fit_to_width(self):
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
        if self.pdf_document:
            self.show_page(self.current_page)
        elif self.image_item:
            self.display_image()

    def load_document(self):
        if self.file_path.lower().endswith('.pdf'):
            self.load_pdf()
        else:
            self.load_image()

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
        except Exception as e:
            self.main_view_label.setText(f"Error loading PDF: {e}")

    def load_image(self):
        try:
            self.image_item = Image.open(self.file_path)
            thumb_pixmap = QPixmap(self.file_path).scaledToWidth(120, Qt.TransformationMode.SmoothTransformation)
            thumb_label = QLabel(); thumb_label.setPixmap(thumb_pixmap)
            thumb_label.setFrameShape(QFrame.Shape.StyledPanel)
            self.thumbnail_layout.addWidget(thumb_label); self.thumbnail_labels.append(thumb_label)
            self.display_image()
        except Exception as e:
            self.main_view_label.setText(f"Error loading image: {e}")

    def display_image(self):
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
        self.main_view_label.resize(pixmap.size())
        self.highlight_thumbnail(page_num)

    def highlight_thumbnail(self, index):
        for i, label in enumerate(self.thumbnail_labels):
            if i == index: label.setStyleSheet("border: 2px solid #0078d4;")
            else: label.setStyleSheet("")

    # ----------------- RAG: indexing -----------------
    def index_document(self):
        """Extracts text from the opened document and chunks it for retrieval."""
        self.chat_history.append("[System] Indexing document...")
        if self.file_path.lower().endswith('.pdf'):
            text = extract_text_from_pdf(self.file_path)
        else:
            text = ocr_image(self.file_path)
            if text:
                self.chat_history.append(f"[System] OCR extracted text (truncated): {text[:200]}...")
            else:
                self.chat_history.append("[System] OCR (pytesseract) found no text.")
                
            if not text:
                text = f"(No OCR available) File: {self.file_path}\n" + ""
        
        if not text.strip() or text.startswith("(No OCR available)"):
            self.chat_history.append("[System] No text could be extracted or indexed.")
            self.indexed_chunks = []
            self.indexed = False
            return
        chunks = chunk_text(text, max_chars=1400, overlap=200)
        self.indexed_chunks = chunks
        self.indexed = True
        self.chat_history.append(f"[System] Document indexed into {len(chunks)} chunks.")

    # ----------------- Chat interaction -----------------
    def on_send_clicked(self):
        q = self.chat_input.text().strip()
        if not q:
            return
        self.chat_input.clear()
        self.chat_history.append(f"You: {q}")
        # Run retrieval + model call in a separate thread to keep UI responsive
        thread = threading.Thread(target=self._process_question, args=(q,))
        thread.start()

    def _process_question(self, question):
        is_pdf = self.file_path.lower().endswith('.pdf')
        
        if is_pdf:
            # --- RAG Logic for PDFs ---
            
            # If not indexed, attempt to index automatically
            if not self.indexed:
                self.chat_history.append("[System] Document not indexed yet — attempting automatic indexing...")
                self.index_document()
                if not self.indexed:
                    self.chat_history.append("[System] Indexing failed. Cannot answer from document.")
                    return

            # Retrieve top chunks
            top = retrieve_top_chunks(self.indexed_chunks, question, top_k=4)
            if not top:
                # No matches — still call llava but warn user
                context = ""
                self.chat_history.append("[System] No strongly relevant passages found; answering without document context.")
            else:
                context = "\n\n---\n\n".join(top)

            # Build a prompt that instructs the model to use the context.
            prompt = (
                "You are a helpful assistant. Use the provided document context to answer the question.\n"
                "If the answer is not contained in the context, say you don't know instead of making up facts.\n\n"
                "Context:\n" + context + "\n\nQuestion: " + question + "\n\nAnswer:"
            )

            self.chat_history.append("[System] Sending prompt to llava (ollama)...")
            # Call llava WITHOUT an image path (text-only RAG)
            response = call_ollama_llava(prompt, timeout=60)
            
        else:
            # --- VQA Logic for Images ---
            # We bypass RAG and send the image path directly to llava
            
            prompt = (
                "You are a helpful visual assistant. Look at the image and answer the question.\n\n"
                "Question: " + question + "\n\nAnswer:"
            )

            self.chat_history.append(f"[System] Sending prompt and image to llava (ollama)...")
            # Call llava WITH the image path
            response = call_ollama_llava(prompt, image_path=self.file_path, timeout=60)

        # Append the model's response
        self.chat_history.append(f"llava: {response}")


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