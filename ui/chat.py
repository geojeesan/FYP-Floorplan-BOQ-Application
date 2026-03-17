import os
import json
import sqlite3
from shapely.geometry import Polygon
from dotenv import load_dotenv

import langchain
langchain.debug = True

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit, QLineEdit, QComboBox
)
from PySide6.QtGui import QTextCursor
from PySide6.QtCore import QThread, Signal, Qt

# LangChain & LangGraph Imports
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langchain_core.tools import tool
from langchain.agents import create_agent
from langchain_core.callbacks import StreamingStdOutCallbackHandler

from PySide6.QtWidgets import QScrollArea
from PySide6.QtCore import QTimer

# Load environment variables (API Keys) from .env file
load_dotenv()

@tool
def query_materials_database(table_name: str) -> str:
    """
    Retrieves all available materials and pricing for a specific category.
    Use this to find costs or brand options to answer user questions about materials.
    
    CRITICAL RULES FOR THE AGENT:
    1. You must provide ONLY the exact table name from the list below. Do NOT write SQL.
    2. Available table_name options: 
       'Floors', 'Walls', 'Doors', 'Windows', 'Fixtures', 'Electrical Appliances', 
       'Closet', 'Toilet', 'Sink', 'Sauna Bench', 'Fire Place', 'Bathtub', 'Chimney'
    """
    # 1. Validate input strictly to prevent SQL injection and LLM hallucinations
    valid_tables = [
        "Floors", "Walls", "Doors", "Windows", "Fixtures", "Electrical Appliances", 
        "Closet", "Toilet", "Sink", "Sauna Bench", "Fire Place", "Bathtub", "Chimney"
    ]
    
    # Strip any accidental quotes the LLM might add
    clean_table_name = table_name.strip("'\"")
    
    if clean_table_name not in valid_tables:
        return f"Error: '{clean_table_name}' is not a valid category. You must choose exactly from the allowed list. Do not write SQL."

    try:
        db_path = 'boq_materials.db' 
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # 2. Programmatically execute the query safely
        # We wrap the table name in brackets [ ] in case of spaces like "Electrical Appliances"
        # We explicitly select only the text/number columns, ignoring any heavy image BLOB columns if they exist
        query = f"SELECT item_no, item_name, brand_name, cost, unit, markup_percentage FROM [{clean_table_name}]"
        
        cursor.execute(query)
        raw_results = cursor.fetchall()
        
        # Grab the column headers so the LLM knows what the data means
        headers = [description[0] for description in cursor.description]
        
        conn.close()

        if not raw_results:
            return f"No materials found in the {clean_table_name} category. Tell the user in natural language that this category is currently empty in the database."

        # 3. Sanitize the results (safety net for binary data)
        # We put the headers as the first item in the list so the LLM has context
        clean_results = [tuple(headers)] 
        for row in raw_results:
            clean_row = tuple("[IMAGE DATA]" if isinstance(col, bytes) else col for col in row)
            clean_results.append(clean_row)

        print(f"Tool run - Fetched table: {clean_table_name} | Returned {len(raw_results)} items.")  
        
        return str(clean_results)
        
    except Exception as e:
        return f"Database query error: {str(e)}. Tell the user you encountered an error reading the database."

@tool
def convert_units(value: float, from_unit: str, to_unit: str) -> str:
    """
    Converts architectural measurements between different units.
    Supported units: 'sqm', 'sqft', 'm', 'ft', 'mm', 'cm'.
    """
    conversions = {
        ("sqm", "sqft"): 10.7639,
        ("sqft", "sqm"): 0.092903,
        ("m", "ft"): 3.28084,
        ("ft", "m"): 0.3048,
        ("mm", "m"): 0.001,
        ("cm", "m"): 0.01,
        ("m", "mm"): 1000.0,
    }
    
    try:
        key = (from_unit.lower().strip(), to_unit.lower().strip())
        if key in conversions:
            converted_value = value * conversions[key]
            print(f"Tool run - Converted {value} {from_unit} to {converted_value} {to_unit}")
            return f"{converted_value:.4f}"
        return f"Error: Conversion from '{from_unit}' to '{to_unit}' is not supported."
    except Exception as e:
        return f"Error converting units: {e}"

@tool
def calculate(expression: str) -> str:
    """
    Evaluates a mathematical expression. Use this tool whenever you need to perform calculations
    related to dimensions, areas, costs, or any other numbers in the floorplan data.
    """
    try:
        allowed_names = {"__builtins__": None}
        result = eval(expression, allowed_names, {})
        print(f"Tool run - Calculated expression: {expression} = {result}")
        return str(result)
    except Exception as e:
        return f"Error calculating: {e}"

# LLM Factory
def get_llm(provider: str, model_name: str):
    """Initializes the LLM based on the selected provider."""
    # Ensure variables are freshly loaded in case they were updated in Settings
    load_dotenv(override=True) 

    stream_callback = [StreamingStdOutCallbackHandler()]
    
    if provider == "OpenAI":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=model_name, temperature=0, streaming=True, callbacks=stream_callback)
        
    elif provider == "Google":
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(model=model_name, temperature=0, streaming=True, callbacks=stream_callback)
        
    elif provider == "Anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(model=model_name, temperature=0, streaming=True, callbacks=stream_callback)
        
    elif provider == "OpenRouter":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            openai_api_base="https://openrouter.ai/api/v1",
            openai_api_key=os.environ.get("OPENROUTER_API_KEY", ""),
            model_name=model_name,
            temperature=0,
            max_retries=1,
            timeout=30,
            streaming=True,
            callbacks=stream_callback
        )
        
    else:
        # Default to Ollama
        from langchain_ollama import ChatOllama
        return ChatOllama(model=model_name, temperature=0, streaming=True, callbacks=stream_callback)


class ChatWorker(QThread):
    finished = Signal(str)
    error = Signal(str)

    def __init__(self, prompt, context_data, history, provider="Ollama", model="phi4-mini"):
        super().__init__()
        self.prompt = prompt
        self.context_data = context_data
        self.history = history
        self.provider = provider
        self.model = model

    def run(self):
        try:
            llm = get_llm(self.provider, self.model)

            ratio = 1.0
            if self.context_data and "calibration_info" in self.context_data:
                ratio = self.context_data["calibration_info"].get("pixel_to_unit_ratio", 1.0)

            # 2. Define the tool dynamically inside this thread so it inherits the 'ratio' variable
            @tool
            def calculate_perimeter(points: list[list[float]]) -> str:
                """
                Calculates the real-world perimeter of a room.
                Args:
                    points: A list of [x, y] coordinate pairs representing the room's polygon.
                Returns:
                    The calculated real-world perimeter as a string.
                """
                try:
                    if not points or len(points) < 3:
                        return "Error: A polygon must have at least 3 points."
                    
                    from shapely.geometry import Polygon
                    poly = Polygon(points)
                    # The tool automatically applies the correct scale from the viewer!
                    perimeter = poly.length * ratio
                    print (f"Tool run - Calculated perimeter: {perimeter} (using ratio: {ratio})")  # Debug print
                    return f"{perimeter:.2f}"
                except Exception as e:
                    return f"Error calculating perimeter: {e}"

            tools = [calculate, query_materials_database, convert_units, calculate_perimeter]
            agent_executor = create_agent(llm, tools)

            context_str = json.dumps(self.context_data, indent=2)
            base_system_prompt = (
                    "You are an expert architectural and floorplan assistant. "
                    "CRITICAL RULES: \n"
                    "1. MATH: You MUST use the 'calculate' tool for EVERY single mathematical operation (addition, multiplication, division, etc.). Never attempt to calculate numbers yourself.\n"
                    "2. GEOMETRY: Use the 'calculate_perimeter' tool if asked about wall lengths, skirting, or perimeters. You only need to pass the room's points; the scale is handled automatically.\n"
                    "3. MATERIALS: Use the 'query_materials_database' tool to retrieve cost information for materials. Do not use this for getting information about the floorplan itself.\n"
                    "4. UNITS: Use the 'convert_units' tool to convert measurements between different units.\n"
                    "5. CURRENCY: Always format costs and prices using the British Pound symbol (£) unless the user specifically asks for another currency.\n\n"
                    f"Floorplan Context Data:\n{context_str}\n\n"
                    "Answer the user's questions based on this data. Keep answers concise."
                )

            messages = [SystemMessage(content=base_system_prompt)]

            for role, text in self.history:
                if role == "You":
                    messages.append(HumanMessage(content=text))
                elif role == "AI":
                    messages.append(AIMessage(content=text))
            
            messages.append(HumanMessage(content=self.prompt))

            max_retries = 2
            final_answer = ""

            for attempt in range(max_retries):
                result = agent_executor.invoke({"messages": messages})
                final_answer = result["messages"][-1].content.strip()

                # 3. Intercept the JSON leak
                if final_answer.startswith('{"') or final_answer.startswith('```json'):
                    print(f"Worker - Caught JSON leak on attempt {attempt + 1}. Wiping memory and retrying...")
                    
                    # Update the system prompt to be explicitly aggressive about the failure
                    strict_system_prompt = base_system_prompt + "\n\nCRITICAL ERROR: YOU JUST ATTEMPTED TO OUTPUT RAW JSON TO THE USER. THIS IS FORBIDDEN. YOU MUST RESPOND IN NATURAL LANGUAGE."
                    messages[0] = SystemMessage(content=strict_system_prompt)
                    continue
                else:
                    break

            # 4. Emit the final answer
            self.finished.emit(final_answer)

        except Exception as e:
            self.error.emit(f"Execution Error: {str(e)}")


class AIChatPanel(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        
        # Header & Settings Layout
        header_layout = QHBoxLayout()
        header_lbl = QLabel("<b>Model:</b>")
        
        # Provider & Model Selection
        self.provider_combo = QComboBox()
        self.provider_combo.setToolTip("Select AI Provider")
        self.model_combo = QComboBox()
        self.model_combo.setToolTip("Select Model")
        
        self.provider_combo.currentTextChanged.connect(self.update_model_dropdown)
        
        header_layout.addWidget(header_lbl)
        header_layout.addStretch()
        header_layout.addWidget(self.provider_combo)
        header_layout.addWidget(self.model_combo)
        layout.addLayout(header_layout)

        # Chat History Area (Replaced QTextEdit with QScrollArea)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet("background: transparent; border: none;")
        
        # Container to hold all the individual chat bubble widgets
        self.chat_container = QWidget()
        self.chat_container.setStyleSheet("background: transparent;")
        self.chat_layout = QVBoxLayout(self.chat_container)
        self.chat_layout.setAlignment(Qt.AlignTop) # Stack messages from the top
        self.chat_layout.setSpacing(10)
        
        self.scroll_area.setWidget(self.chat_container)
        layout.addWidget(self.scroll_area)
        
        # Input Field
        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("Ask about the floorplan...")
        self.input_field.returnPressed.connect(self.send_message)
        layout.addWidget(self.input_field)
        
        # Buttons Layout
        btn_layout = QHBoxLayout()
        
        self.send_btn = QPushButton("Ask")
        self.send_btn.clicked.connect(self.send_message)
        self.send_btn.setStyleSheet("background-color: #fb9a44; color: white; font-weight: bold;")
        
        self.clear_btn = QPushButton("Clear Chat")
        self.clear_btn.clicked.connect(self.clear_current_chat)
        self.clear_btn.setStyleSheet("background-color: rgba(255, 255, 255, 20); color: white;")
        
        btn_layout.addWidget(self.send_btn, stretch=3)
        btn_layout.addWidget(self.clear_btn, stretch=1)
        
        layout.addLayout(btn_layout)
        
        self.current_viewer = None
        self.worker = None
        
        # Initialize the dropdowns
        self.refresh_providers()

    def append_bubble(self, role, text, is_thinking=False):
        bubble_layout = QHBoxLayout()
        bubble_layout.setContentsMargins(0, 0, 0, 0)
        
        # Create the widget for the message
        label = QLabel(text)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextSelectableByMouse) # Let users copy text
        
        # Prevent the bubble from stretching across the whole screen
        label.setMaximumWidth(int(self.scroll_area.width() * 0.85))

        if role == "You":
            # User styling (Green, Right-aligned)
            label.setStyleSheet("""
                background-color: #dcf8c6; 
                color: black; 
                border-radius: 10px; 
                padding: 10px; 
                font-size: 13px;
            """)
            bubble_layout.addStretch()  # Pushes the label to the right
            bubble_layout.addWidget(label)
        else:
            # AI styling (Gray, Left-aligned)
            label.setStyleSheet("""
                background-color: #e5e5ea; 
                color: black; 
                border-radius: 10px; 
                padding: 10px; 
                font-size: 13px;
            """)
            bubble_layout.addWidget(label)
            bubble_layout.addStretch()  # Pushes the label to the left

        # Add the horizontal layout (the bubble) to the main vertical chat layout
        self.chat_layout.addLayout(bubble_layout)

        # Scroll to the bottom slightly after the widget is rendered
        QTimer.singleShot(10, self.scroll_to_bottom)

    def scroll_to_bottom(self):
        scrollbar = self.scroll_area.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def refresh_providers(self):
        """Reads enabled providers from settings and refreshes the dropdown."""
        load_dotenv(override=True)
        current_selection = self.provider_combo.currentText()
        
        self.provider_combo.blockSignals(True)
        self.provider_combo.clear()
        
        providers = [
            ("Ollama", "OLLAMA"),
            ("OpenAI", "OPENAI"),
            ("Google", "GOOGLE"),
            ("Anthropic", "ANTHROPIC"),
            ("OpenRouter", "OPENROUTER")
        ]
        
        enabled_list = []
        for name, prefix in providers:
            # Default Ollama to True, others to False if missing
            default_state = "True" if name == "Ollama" else "False"
            if os.getenv(f"{prefix}_ENABLED", default_state).lower() == "true":
                enabled_list.append(name)
                
        if not enabled_list:
            enabled_list = ["Ollama"] # Fallback if user unchecks everything
            
        self.provider_combo.addItems(enabled_list)
        
        if current_selection in enabled_list:
            self.provider_combo.setCurrentText(current_selection)
            
        self.provider_combo.blockSignals(False)
        self.update_model_dropdown(self.provider_combo.currentText())

    def update_model_dropdown(self, provider):
        """Updates the available models based on the selected provider."""
        self.model_combo.clear()
        if not provider: return
        
        models = []
        if provider == "Ollama":
            models_str = os.getenv("OLLAMA_MODELS", "phi4-mini, llama3, mistral, gemma")
            models = [m.strip() for m in models_str.split(",") if m.strip()]
        elif provider == "OpenRouter":
            models_str = os.getenv("OPENROUTER_MODELS", "meta-llama/llama-3.1-8b-instruct, anthropic/claude-3.5-sonnet")
            models = [m.strip() for m in models_str.split(",") if m.strip()]
        else:
            # Fixed models for providers where custom endpoints aren't strictly required
            default_models = {
                "OpenAI": ["gpt-4o-mini", "gpt-4o", "gpt-3.5-turbo"],
                "Google": ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-1.5-flash"],
                "Anthropic": ["claude-3-5-sonnet-latest", "claude-3-haiku-20240307", "claude-3-opus-20240229"],
            }
            models = default_models.get(provider, [])
            
        self.model_combo.addItems(models)

    def set_active_viewer(self, viewer):
        self.current_viewer = viewer
        self.refresh_display()

    def clear_current_chat(self):
        if self.current_viewer:
            self.current_viewer.chat_log = []
        self.refresh_display()

    def refresh_display(self):
        # Clear existing bubbles
        while self.chat_layout.count():
            item = self.chat_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
            else:
                # If it's a layout (like our bubble_layout), we need to clear its items too
                sub_layout = item.layout()
                while sub_layout.count():
                    sub_item = sub_layout.takeAt(0)
                    if sub_item.widget():
                        sub_item.widget().deleteLater()
        
        if not self.current_viewer:
            self.input_field.setEnabled(False)
            self.send_btn.setEnabled(False)
            self.clear_btn.setEnabled(False)
            # Add a placeholder label
            placeholder = QLabel("<i>No active document.</i>")
            placeholder.setStyleSheet("color: gray;")
            placeholder.setAlignment(Qt.AlignCenter)
            self.chat_layout.addWidget(placeholder)
            return
        
        self.input_field.setEnabled(True)
        self.send_btn.setEnabled(True)
        self.clear_btn.setEnabled(True)
        
        if hasattr(self.current_viewer, 'chat_log'):
            for role, text in self.current_viewer.chat_log:
                self.append_bubble(role, text)

    def send_message(self):
        user_text = self.input_field.text()
        if not user_text or not self.current_viewer: 
            return

        self.append_bubble("You", user_text)
        self.append_bubble("AI", "<i>Thinking (Agent is running)...</i>")
        
        self.input_field.clear()
        self.input_field.setEnabled(False) 
        self.send_btn.setEnabled(False)

        if hasattr(self.current_viewer, 'chat_log'):
            self.current_viewer.chat_log.append(("You", user_text))

        context_data = {}
        if hasattr(self.current_viewer, 'has_analysis_data') and self.current_viewer.has_analysis_data:
            context_data = self.current_viewer.get_scaled_boq_data()
        
        history = []
        if hasattr(self.current_viewer, 'chat_log'):
            history = self.current_viewer.chat_log[:-1]

        provider = self.provider_combo.currentText()
        selected_model = self.model_combo.currentText()

        self.worker = ChatWorker(
            prompt=user_text, 
            context_data=context_data, 
            history=history,
            provider=provider,
            model=selected_model
        )
        self.worker.finished.connect(self.on_worker_finished)
        self.worker.error.connect(self.on_worker_error)
        self.worker.start()

    def on_worker_finished(self, answer):
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