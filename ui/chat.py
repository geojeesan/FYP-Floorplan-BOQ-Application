import os
import json
import sqlite3
from shapely.geometry import Polygon
from dotenv import load_dotenv
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit, QLineEdit, QComboBox
)
from PySide6.QtGui import QTextCursor
from PySide6.QtCore import QThread, Signal, Qt

# LangChain & LangGraph Imports
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langchain_core.tools import tool
from langchain.agents import create_agent

# Load environment variables (API Keys) from .env file
load_dotenv()

@tool
def query_materials_database(query: str) -> str:
    """
    Executes a SELECT SQL query on the materials database to retrieve cost or specification data.
    Use this to find pricing or brand name not found in the floorplan JSON context. DO NOT use this for getting information about the floorplan itself, only for external data about materials.
    Available tables: Floors, Walls, Doors, Windows, Fixtures, Electrical Appliances, Closet, Toilet, Sink, Sauna Bench, Fire Place, Bathtub, Chimney
    Each table has columns: item_no, item_name, brand_name, cost, unit, markup_percentage
    """
    try:
        db_path = 'boq_materials.db' 
        
        # Safety check: Prevent destructive queries
        if not query.strip().upper().startswith("SELECT"):
            return "Error: Only SELECT queries are allowed for safety."
            
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(query)
        results = cursor.fetchall()
        conn.close()

        print(f"Tool run - Executed query: {query} | Results: {results}")  
        
        if not results:
            return "No results found in the database."
        return str(results)
    except Exception as e:
        return f"Database query error: {e}"

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
    
    if provider == "OpenAI":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=model_name, temperature=0)
        
    elif provider == "Google":
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(model=model_name, temperature=0)
        
    elif provider == "Anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(model=model_name, temperature=0)
        
    elif provider == "OpenRouter":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            openai_api_base="https://openrouter.ai/api/v1",
            openai_api_key=os.environ.get("OPENROUTER_API_KEY", ""),
            model_name=model_name,
            temperature=0
        )
        
    else:
        # Default to Ollama
        from langchain_ollama import ChatOllama
        return ChatOllama(model=model_name, temperature=0)


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
            messages = [
                SystemMessage(content=(
                    "You are an expert architectural and floorplan assistant. "
                    "CRITICAL RULES: \n"
                    "1. MATH: You MUST use the 'calculate' tool for EVERY single mathematical operation (addition, multiplication, division, etc.). Never attempt to calculate numbers yourself.\n"
                    "2. GEOMETRY: Use the 'calculate_perimeter' tool if asked about wall lengths, skirting, or perimeters. You only need to pass the room's points; the scale is handled automatically.\n"
                    "3. MATERIALS: Use the 'query_materials_database' tool to retrieve cost information for materials. Do not use this for getting information about the floorplan itself.\n"
                    "4. UNITS: Use the 'convert_units' tool to convert measurements between different units.\n"
                    "5. CURRENCY: Always format costs and prices using the British Pound symbol (£) unless the user specifically asks for another currency.\n\n"
                    f"Floorplan Context Data:\n{context_str}\n\n"
                    "Answer the user's questions based on this data. Keep answers concise."
                ))
            ]

            for role, text in self.history:
                if role == "You":
                    messages.append(HumanMessage(content=text))
                elif role == "AI":
                    messages.append(AIMessage(content=text))
            
            messages.append(HumanMessage(content=self.prompt))

            result = agent_executor.invoke({"messages": messages})
            final_answer = result["messages"][-1].content
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
        header_lbl = QLabel("<b>Floorplan Assistant</b>")
        
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
        
        # Chat History Area
        self.chat_history = QTextEdit()
        self.chat_history.setReadOnly(True)
        layout.addWidget(self.chat_history)
        
        # Input Field
        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("Ask about the floorplan...")
        self.input_field.returnPressed.connect(self.send_message)
        layout.addWidget(self.input_field)
        
        # Buttons Layout
        btn_layout = QHBoxLayout()
        
        self.send_btn = QPushButton("Ask")
        self.send_btn.clicked.connect(self.send_message)
        self.send_btn.setStyleSheet("background-color: #0078d7; color: white; font-weight: bold;")
        
        self.clear_btn = QPushButton("Clear Chat")
        self.clear_btn.clicked.connect(self.clear_current_chat)
        self.clear_btn.setStyleSheet("background-color: #f0f0f0; color: #333;")
        
        btn_layout.addWidget(self.send_btn, stretch=3)
        btn_layout.addWidget(self.clear_btn, stretch=1)
        
        layout.addLayout(btn_layout)
        
        self.current_viewer = None
        self.worker = None
        
        # Initialize the dropdowns
        self.refresh_providers()

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

    def append_bubble(self, role, text, is_thinking=False):
        if role == "You":
            color, align, margin = "#dcf8c6", "right", "margin-left: 50px;"
        else:
            color, align, margin = "#e5e5ea", "left", "margin-right: 50px;"

        formatted_text = f"""
        <div align="{align}">
            <table style="background-color: {color}; border-radius: 10px; {margin}">
                <tr>
                    <td style="padding: 10px; color: black; font-size: 13px;">
                        {text}
                    </td>
                </tr>
            </table>
        </div>
        <br>
        """
        cursor = self.chat_history.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.chat_history.setTextCursor(cursor)
        self.chat_history.insertHtml(formatted_text)
        self.chat_history.moveCursor(QTextCursor.End)

    def refresh_display(self):
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