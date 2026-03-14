import json
from PySide6.QtCore import QThread, Signal
from langgraph.graph import StateGraph, START, END
from typing import TypedDict
from langchain_core.messages import SystemMessage, HumanMessage
from .chat import get_llm

class ReportState(TypedDict):
    math_data: str
    report_type: str
    provider: str
    model: str
    result_json: str
    error: str

def generate_report_node(state: ReportState):
    print("\n--- LLM AGENT STARTED ---")
    print(f"Goal: Generate {state['report_type']} (Strict Hierarchical Layout)")
    
    try:
        llm = get_llm(state["provider"], state["model"])
        

        if 'report_type' == "BOQ":
            sys_msg = f"""You are an expert Quantity Surveyor.
    I am providing you with an ordered JSON array of MATHEMATICALLY EXACT quantities.
    The data includes objects marked as "Type": "Header" (The Room) and "Type": "Sub" (The materials/fixtures inside that room).

    CRITICAL FORMATTING RULES:
    1. STRICTLY maintain the exact order of the provided array.
    2. For "Header" objects: Place the 'Heading' value in the 'Heading' column. Leave 'Description' BLANK (""). KEEP the 'Length', 'Width', 'Height', 'Quantity', and 'Unit' EXACTLY as provided. 
    3. For "Sub" objects: Leave 'Heading' BLANK (""). Transform the 'Base_Description' into a highly professional architectural description in the 'Description' column. KEEP all dimensions and quantities EXACTLY as provided.
    4. DO NOT add any labor costs. Have general sundries in a separate section at the end.
    5. Do NOT include the 'Type' or 'Base_Description' or 'Category' keys in your final JSON output.
    6. Output ONLY a raw JSON array of objects. Start directly with [ and end with ].

    Columns REQUIRED: "Heading", "Item_No", "Description", "Unit", "Quantity", "Rate", "Total_Amount", "Markup_Percentage", "Final_Amount"
    """
        elif 'report_type' == "QTO":
            sys_msg = f"""You are an expert Quantity Surveyor.
    I am providing you with an ordered JSON array of MATHEMATICALLY EXACT quantities.
    The data includes objects marked as "Type": "Header" (The Room) and "Type": "Sub" (The materials/fixtures inside that room).

    CRITICAL FORMATTING RULES:
    1. STRICTLY maintain the exact order of the provided array.
    2. For "Header" objects: Place the 'Heading' value in the 'Heading' column. Leave 'Description' BLANK (""). KEEP the 'Length', 'Width', 'Height', 'Quantity', and 'Unit' EXACTLY as provided. 
    3. For "Sub" objects: Leave 'Heading' BLANK (""). Transform the 'Base_Description' into a highly professional architectural description in the 'Description' column. KEEP all dimensions and quantities EXACTLY as provided.
    4. DO NOT add any labor costs or preliminaries. Have general sundries in a separate section at the end.
    5. Do NOT include the 'Type' or 'Base_Description' or 'Category' keys in your final JSON output.
    6. Output ONLY a raw JSON array of objects. Start directly with [ and end with ].

    Columns REQUIRED: "Heading", "Description", "Unit", "Length", "Width", "Height", "Quantity"
    """
        messages = [
            SystemMessage(content=sys_msg),
            HumanMessage(content=state["math_data"])
        ]
        
        print("Waiting for LLM response (this may take a moment)...")
        res = llm.invoke(messages)
        content = res.content.strip()
        
        start_idx = content.find('[')
        end_idx = content.rfind(']')
        
        if start_idx != -1 and end_idx != -1:
            content = content[start_idx:end_idx+1]
            
        print("\n--- LLM RAW RESPONSE ---")
        print(content[:500] + "\n...[truncated]...")
        print("------------------------\n")
            
        state["result_json"] = content
    except Exception as e:
        state["error"] = str(e)
        
    return state

workflow = StateGraph(ReportState)
workflow.add_node("generate_report", generate_report_node)
workflow.add_edge(START, "generate_report")
workflow.add_edge("generate_report", END)
report_graph = workflow.compile()

class ReportWorker(QThread):
    finished = Signal(str, str) 
    error = Signal(str)

    def __init__(self, exact_math_data, report_type, provider, model):
        super().__init__()
        self.exact_math_data = exact_math_data
        self.report_type = report_type
        self.provider = provider
        self.model = model

    def run(self):
        try:
            raw_str = json.dumps(self.exact_math_data, indent=2)
            
            initial_state = {
                "math_data": raw_str,
                "report_type": self.report_type,
                "provider": self.provider,
                "model": self.model,
                "result_json": "",
                "error": ""
            }
            
            result_state = report_graph.invoke(initial_state)
            
            if result_state.get("error"):
                self.error.emit(result_state["error"])
            else:
                self.finished.emit(result_state["result_json"], self.report_type)
        except Exception as e:
            self.error.emit(str(e))