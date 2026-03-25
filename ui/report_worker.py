import re
import json
import sqlite3
import os
from PySide6.QtCore import QThread, Signal
from langgraph.graph import StateGraph, START, END
from typing import TypedDict
from langchain_core.messages import SystemMessage, HumanMessage
from .chat import get_llm

import statistics
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent

@tool
def calculate_item_total(quantity: float, rate: float) -> float:
    """Calculates the total amount by multiplying the item quantity by the estimated rate."""
    return round(quantity * rate, 2)

class ReportState(TypedDict):
    raw_items: list
    report_type: str
    provider: str
    model: str
    boq_standard: str 
    categorized_items: list  
    estimates: list          
    result_json: str
    error: str

# Removed CESMM4. Updated SMM7 Section N to explicitly include Sanitary appliances
BOQ_STANDARDS = {
    "POMI": {
        "A": "SECTION A - GENERAL REQUIREMENTS",
        "B": "SECTION B - SITEWORK",
        "C": "SECTION C - CONCRETE WORKS",
        "D": "SECTION D - MASONRY",
        "E": "SECTION E - METALWORK",
        "F": "SECTION F - WOODWORK",
        "G": "SECTION G - THERMAL & WATERPROOFING",
        "H": "SECTION H - DOORS & WINDOWS",
        "J": "SECTION J - FINISHES",
        "K": "SECTION K - ACCESSORIES",
        "L": "SECTION L - EQUIPMENT",
        "M": "SECTION M - FURNISHINGS",
        "N": "SECTION N - SPECIAL CONSTRUCTION",
        "O": "SECTION O - MECHANICAL INSTALLATIONS",
        "P": "SECTION P - CONVEYING SYSTEMS",
        "Q": "SECTION Q - ELECTRICAL INSTALLATIONS",
        "R": "SECTION R - EXTERNAL WORKS"
    },
    "NRM 2": {
        "1": "1 - Preliminaries",
        "5": "5 - Excavating and filling",
        "11": "11 - In situ concrete",
        "14": "14 - Masonry",
        "16": "16 - Carpentry",
        "28": "28 - Floor, wall, ceiling and roof finishings",
        "31": "31 - Windows, doors and stairs",
        "32": "32 - Furniture, fittings and equipment",
        "38": "38 - Mechanical services",
        "39": "39 - Electrical services",
        "41": "41 - Builder's work in connection"
    },
    "SMM7": {
        "A": "A - Preliminaries/General conditions",
        "D": "D - Groundwork", "E":
        "E - In situ concrete/Large precast concrete",
        "F": "F - Masonry",
        "G": "G - Structural/Carcassing metal/timber",
        "L": "L - Windows/doors/stairs",
        "M": "M - Surface finishes",
        "N": "N - Furniture/equipment/Sanitary appliances",
        "U": "U - Ventilation/air conditioning",
        "V": "V - Electrical supply/power/lighting"
    }
}

def get_fallback_section(item_no, description, standard):
    """Fallback programmatic categorization based on selected standard."""
    desc = description.lower()
    
    if standard == "POMI":
        if "door" in desc or "window" in desc: return "H"
        if "tile" in desc or "paint" in desc or "floor" in desc or "brick slip" in desc: return "J"
        if "toilet" in desc or "sink" in desc or "washbasin" in desc: return "O"
        if "appliance" in desc or "oven" in desc or "fridge" in desc or "hob" in desc: return "L"
        if "closet" in desc or "wardrobe" in desc: return "M"
        if "wood" in desc or "oak" in desc: return "F"
        return "Z"
        
    elif standard == "NRM 2":
        if "door" in desc or "window" in desc: return "31"
        if "tile" in desc or "paint" in desc or "floor" in desc: return "28"
        if "toilet" in desc or "sink" in desc: return "38"
        if "appliance" in desc or "furniture" in desc: return "32"
        if "wood" in desc or "carpentry" in desc: return "16"
        return "Z"
        
    elif standard == "SMM7":
        if "door" in desc or "window" in desc: return "L"
        if "tile" in desc or "paint" in desc or "floor" in desc: return "M"
        # Fixed SMM7 plumbing mapping to Section N instead of U
        if "toilet" in desc or "sink" in desc or "appliance" in desc or "washbasin" in desc: return "N" 
        if "wood" in desc or "timber" in desc: return "G"
        return "Z"
        
    return "Z"

def extract_clean_json(text):
    if "```json" in text:
        text = text.split("```json")[1]
    if "```" in text:
        text = text.split("```")[0]
        
    start = text.find('[')
    end = text.rfind(']')
    
    if start != -1 and end != -1:
        return text[start:end+1]
    return "[]"

def get_db_price_context():
    ui_dir = os.path.dirname(os.path.abspath(__file__))
    root_dir = os.path.dirname(ui_dir)
    db_path = os.path.join(root_dir, "boq_materials.db")
    context = []
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        tables = [
            "Floors", "Walls", "Doors", "Windows", "Fixtures", 
            "Electrical Appliances", "Closet", "Toilet", "Sink"
        ]
        for t in tables:
            try:
                cursor.execute(f'SELECT cost, unit FROM "{t}" WHERE cost > 0')
                rows = cursor.fetchall()
                if not rows: continue
                
                unit_costs = {}
                for cost, unit in rows:
                    unit_costs.setdefault(unit, []).append(cost)
                    
                for unit, costs in unit_costs.items():
                    if not costs: continue
                    mean_val = round(statistics.mean(costs), 2)
                    median_val = round(statistics.median(costs), 2)
                    try: mode_val = round(statistics.mode(costs), 2)
                    except statistics.StatisticsError: mode_val = median_val 
                    context.append(f"- {t} ({unit}): Mean=£{mean_val}, Median=£{median_val}, Mode=£{mode_val}")
            except sqlite3.OperationalError:
                pass 
        conn.close()
    except Exception as e:
        print(f"DB Context Error: {e}")
        
    if not context:
        return "No database averages available. Use standard industry estimates."
    return "\n".join(context)

def estimate_qto_unassigned(data, provider, model, progress_signal=None):
    unassigned = [item for item in data if item.get("Type") == "Sub" and float(item.get("Rate", 0.0)) == 0.0]
    
    if not unassigned:
        return data
        
    print(f"\n--- QTO AI ESTIMATOR: Found {len(unassigned)} unassigned items ---")
    if progress_signal:
        progress_signal.emit(f"AI estimating rates for {len(unassigned)} items...")
        
    db_context = get_db_price_context()
    
    try:
        llm = get_llm(provider, model)
        
        sys_msg = f"""You are a Lead Quantity Surveyor. You have a list of extracted project items with NO ASSIGNED COST (Rate = 0).
        
YOUR CRITICAL TASK:
1. Determine a realistic 'Rate' for each item using the statistical database context below.
2. Prepend "[AI Estimate] - " to the beginning of the 'Base_Description'.

DATABASE STATISTICS (Mean, Median, Mode):
{db_context}

Output ONLY a valid JSON array. 
You MUST use strict DOUBLE QUOTES ("") for all property names and string values. Never use single quotes.
Do not output markdown code blocks. 
Do NOT calculate the Total_Amount. Only update the 'Rate' and 'Base_Description'.
"""
        messages = [
            SystemMessage(content=sys_msg), 
            HumanMessage(content=json.dumps(unassigned, indent=2))
        ]
        
        res = llm.invoke(messages).content.strip()
        json_str = extract_clean_json(res)
        fixed_items = json.loads(json_str)
        
        fixed_map = {item.get("Item_No"): item for item in fixed_items if "Item_No" in item}
        
        for i in range(len(data)):
            if data[i].get("Type") == "Sub" and data[i].get("Item_No") in fixed_map:
                est_item = fixed_map[data[i]["Item_No"]]
                
                new_rate = float(est_item.get("Rate", 0.0))
                data[i]["Rate"] = new_rate
                data[i]["Base_Description"] = str(est_item.get("Base_Description", data[i]["Base_Description"]))
                
                qty = float(data[i].get("Quantity", 0.0))
                total = round(qty * new_rate, 2)
                
                data[i]["Total_Amount"] = total
                data[i]["Markup_Percentage"] = 0.0
                data[i]["Final_Amount"] = total
                    
    except Exception as e:
        print(f"QTO AI Estimator Error: {e}")
        
    return data

def generate_qto_programmatically(data):
    final_rows = []
    current_room_items = {}
    current_header = None
    
    def flush_room():
        if current_header:
            final_rows.append(current_header)
            for item in current_room_items.values():
                final_rows.append(item)
        current_room_items.clear()
        
    for item in data:
        if item.get("Type") == "Header":
            flush_room()
            current_header = {
                "Heading": item.get("Heading", ""),
                "Description": "",
                "Unit": item.get("Unit", ""),
                "Length": item.get("Length", ""),
                "Width": item.get("Width", ""),
                "Height": item.get("Height", ""),
                "Quantity": item.get("Quantity", ""),
                "Rate": item.get("Rate", ""),
                "Total_Amount": ""
            }
        elif item.get("Type") == "Sub":
            raw_desc = item.get("Base_Description", "")
            clean_desc = raw_desc.split(',')[0].strip() if raw_desc else ""
            
            unit = item.get("Unit", "")
            length = item.get("Length", "")
            width = item.get("Width", "")
            height = item.get("Height", "")
            rate = item.get("Rate", 0.0)
            
            try: qty = float(item.get("Quantity", 1.0))
            except (ValueError, TypeError): qty = 1.0
                
            agg_key = (clean_desc, unit, length, width, height, rate)
            
            if agg_key in current_room_items:
                current_room_items[agg_key]["Quantity"] += qty
                if rate:
                    current_room_items[agg_key]["Total_Amount"] = round(current_room_items[agg_key]["Quantity"] * float(rate), 2)
            else:
                total_amt = round(qty * float(rate), 2) if rate else ""
                current_room_items[agg_key] = {
                    "Heading": "",
                    "Description": clean_desc,
                    "Unit": unit,
                    "Length": length,
                    "Width": width,
                    "Height": height,
                    "Quantity": qty,
                    "Rate": rate if rate else "",
                    "Total_Amount": total_amt
                }
                
    flush_room()
    return json.dumps(final_rows)

def pre_aggregate_boq_data(data):
    aggregated = {}
    current_room = ""

    for item in data:
        if item.get("Type") == "Header":
            current_room = item.get("Heading", "Unknown Location")
        elif item.get("Type") == "Sub":
            item_no = item.get("Item_No", "")
            base_desc = item.get("Base_Description", "")
            unit = item.get("Unit", "")
            rate = item.get("Rate", 0.0)
            markup = item.get("Markup_Percentage", 0.0)

            try: qty = float(item.get("Quantity", 0.0))
            except: qty = 0.0
            try: tot = float(item.get("Total_Amount", 0.0))
            except: tot = 0.0
            try: fin = float(item.get("Final_Amount", 0.0))
            except: fin = 0.0

            key = (item_no, base_desc, unit, rate, markup)

            if key not in aggregated:
                aggregated[key] = {
                    "Item_No": item_no,
                    "Base_Description": base_desc,
                    "Locations": set(),
                    "Unit": unit,
                    "Quantity": 0.0,
                    "Rate": rate,
                    "Total_Amount": 0.0,
                    "Markup_Percentage": markup,
                    "Final_Amount": 0.0
                }

            aggregated[key]["Quantity"] += qty
            aggregated[key]["Total_Amount"] += tot
            aggregated[key]["Final_Amount"] += fin
            if current_room:
                aggregated[key]["Locations"].add(current_room)

    final_list = []
    for v in aggregated.values():
        locs = ", ".join(sorted(list(v["Locations"])))
        final_list.append({
            "Item_No": v["Item_No"],
            "Base_Description": v["Base_Description"],
            "Location": locs,
            "Unit": v["Unit"],
            "Quantity": round(v["Quantity"], 2),
            "Rate": v["Rate"],
            "Total_Amount": round(v["Total_Amount"], 2),
            "Markup_Percentage": v["Markup_Percentage"],
            "Final_Amount": round(v["Final_Amount"], 2)
        })
        
    return final_list

def categorize_hybrid_node(state: ReportState):
    if "BOQ" not in state["report_type"]: return state
    categorized = []
    unknowns = []
    
    standard = state.get("boq_standard", "POMI")
    sections_dict = BOQ_STANDARDS.get(standard, BOQ_STANDARDS["POMI"])
    
    for item in state["raw_items"]:
        code = get_fallback_section(item["Item_No"], item["Base_Description"], standard)
        item_copy = item.copy()
        item_copy["Description"] = f"{item['Base_Description']} (Location: {item['Location']})"
        
        if code == "Z": unknowns.append(item_copy)
        else:
            item_copy["Section_Code"] = code
            item_copy["Section_Name"] = sections_dict[code]
            categorized.append(item_copy)
            
    if unknowns:
        try:
            llm = get_llm(state["provider"], state["model"])
            sections_str = ", ".join([f"{k} - {v}" for k, v in sections_dict.items()])
            
            sys_msg = f"""You are a master Quantity Surveyor. Categorize the provided list of unknown items into a single {standard} section code.
{standard} SECTIONS: {sections_str}

Output ONLY a JSON array mapping the Item_No to the correct Section_Code.
Example: [{{"Item_No": "123", "Section_Code": "{list(sections_dict.keys())[0]}"}}]"""

            messages = [SystemMessage(content=sys_msg), HumanMessage(content=json.dumps(unknowns, indent=2))]
            res = llm.invoke(messages).content.strip()
            
            json_str = extract_clean_json(res)
            llm_results = json.loads(json_str)
            
            for unk in unknowns:
                match = next((x for x in llm_results if x.get("Item_No") == unk["Item_No"]), None)
                code = match.get("Section_Code", list(sections_dict.keys())[0]) if match else list(sections_dict.keys())[0]
                code = str(code).upper() if str(code).upper() in sections_dict else list(sections_dict.keys())[0]
                
                unk["Section_Code"] = code
                unk["Section_Name"] = sections_dict.get(code, list(sections_dict.values())[0])
                categorized.append(unk)
        except Exception as e:
            for unk in unknowns:
                code = list(sections_dict.keys())[0]
                unk["Section_Code"] = code
                unk["Section_Name"] = sections_dict[code]
                categorized.append(unk)
                
    state["categorized_items"] = categorized
    return state

def estimate_unassigned_items_node(state: ReportState):
    if "BOQ" not in state["report_type"]: return state
    categorized = state.get("categorized_items", [])
    unassigned = [item for item in categorized if float(item.get("Rate", 0.0)) == 0.0]
    assigned = [item for item in categorized if float(item.get("Rate", 0.0)) > 0.0]
    
    if not unassigned: return state
        
    db_context = get_db_price_context()
    try:
        llm = get_llm(state["provider"], state["model"])
        tools = [calculate_item_total]
        agent = create_react_agent(llm, tools)
        
        sys_msg = f"""You are a Lead Quantity Surveyor. You have a list of extracted project items with NO ASSIGNED COST (Rate = 0).
        
YOUR CRITICAL TASK:
1. Determine a realistic 'Rate' for each item using the statistical database context below. 
   - *Advice: The Median or Mode is usually safer than the Mean to avoid luxury outliers.*
2. YOU MUST USE THE `calculate_item_total` TOOL to calculate the 'Total_Amount' for EVERY item. Do not do the math in your head.
3. Set 'Markup_Percentage' to 0.0. Set 'Final_Amount' equal to 'Total_Amount'.
4. Prepend "[AI Estimate] - " to the beginning of the 'Description'.

DATABASE STATISTICS (Mean, Median, Mode):
{db_context}

Output ONLY a JSON array of the updated objects. Maintain the exact same keys:
"Item_No", "Section_Code", "Section_Name", "Description", "Unit", "Quantity", "Rate", "Total_Amount", "Markup_Percentage", "Final_Amount"."""
        messages = [SystemMessage(content=sys_msg), HumanMessage(content=json.dumps(unassigned, indent=2))]
        res = agent.invoke({"messages": messages})
        content = res["messages"][-1].content.strip()
        
        json_str = extract_clean_json(content)
        fixed_items = json.loads(json_str)
        state["categorized_items"] = assigned + fixed_items
    except Exception as e:
        print(f"Unassigned Estimator Error: {e}")
        
    return state

def generate_estimates_node(state: ReportState):
    if "BOQ" not in state["report_type"]: return state
    try:
        llm = get_llm(state["provider"], state["model"])
        standard = state.get("boq_standard", "POMI")
        sections_dict = BOQ_STANDARDS.get(standard, BOQ_STANDARDS["POMI"])
        
        target_codes = list(sections_dict.keys())[:3]
        target_reqs = "\n".join([f"- Section {c} ({sections_dict[c]})" for c in target_codes])
        valid_codes_str = ", ".join([f'"{c}"' for c in target_codes])

        sys_msg = f"""You are a Lead Estimator. Generate missing standard preliminary estimates for a building. 
You MUST generate exactly one or more items for each of these {standard} sections:
{target_reqs}

CRITICAL RULES:
1. "Section_Code" must be {valid_codes_str}.
2. "Section_Name" must be EXACTLY matched to the code (e.g., "{sections_dict[target_codes[0]]}").
3. Description must start with "[AI Estimate] - ".
4. Provide REALISTIC numerical values for Rate, Total_Amount, and Final_Amount. Do not use 0.0 for totals.

Output ONLY a JSON array of these objects. Start with [ and end with ]."""

        messages = [SystemMessage(content=sys_msg), HumanMessage(content="Generate the estimates now.")]
        res = llm.invoke(messages).content.strip()
        json_str = extract_clean_json(res)
        state["estimates"] = json.loads(json_str)
    except Exception as e:
        state["estimates"] = []
    return state

def compile_json_node(state: ReportState):
    if "BOQ" not in state["report_type"]: return state
    try:
        final_rows = []
        grouped_sections = {}
        standard = state.get("boq_standard", "POMI")
        sections_dict = BOQ_STANDARDS.get(standard, BOQ_STANDARDS["POMI"])
        
        for item in state.get("categorized_items", []):
            code = str(item["Section_Code"])
            if code not in grouped_sections: grouped_sections[code] = {"name": item["Section_Name"], "items": []}
            grouped_sections[code]["items"].append({
                "Heading": "", "Item_No": item["Item_No"], "Description": item["Description"],
                "Unit": item["Unit"], "Quantity": item["Quantity"], "Rate": item["Rate"],
                "Total_Amount": item["Total_Amount"], "Markup_Percentage": item["Markup_Percentage"],
                "Final_Amount": item["Final_Amount"]
            })
            
        for est in state.get("estimates", []):
            code = str(est.get("Section_Code", list(sections_dict.keys())[0]))
            code = code if code in sections_dict else list(sections_dict.keys())[0]
            name = sections_dict[code]
            
            if code not in grouped_sections: grouped_sections[code] = {"name": name, "items": []}
            grouped_sections[code]["items"].append({
                "Heading": "", "Item_No": "", "Description": est.get("Description", "[AI Estimate] - Item"),
                "Unit": est.get("Unit", "Sum"), "Quantity": est.get("Quantity", 1.0), "Rate": est.get("Rate", 0.0),
                "Total_Amount": est.get("Total_Amount", 0.0), "Markup_Percentage": est.get("Markup_Percentage", 0.0),
                "Final_Amount": est.get("Final_Amount", 0.0)
            })
            
        # Custom sort key: if the code is all digits (like NRM 2), sort it as an integer.
        def section_sort_key(code):
            text = str(code)
            return (0, int(text)) if text.isdigit() else (1, text)

        for code in sorted(grouped_sections.keys(), key=section_sort_key):
            section = grouped_sections[code]
            final_rows.append({
                "Heading": section["name"], "Item_No": "", "Description": "", "Unit": "",
                "Quantity": "", "Rate": "", "Total_Amount": "", "Markup_Percentage": "", "Final_Amount": ""
            })
            for item in section["items"]: final_rows.append(item)
                
        state["result_json"] = json.dumps(final_rows)
    except Exception as e:
        state["error"] = f"Compiler Error: {str(e)}"
    return state

workflow = StateGraph(ReportState)
workflow.add_node("categorize", categorize_hybrid_node)
workflow.add_node("estimate_unassigned", estimate_unassigned_items_node)
workflow.add_node("estimate_preliminaries", generate_estimates_node)     
workflow.add_node("compile", compile_json_node)

workflow.add_edge(START, "categorize")
workflow.add_edge("categorize", "estimate_unassigned")                 
workflow.add_edge("estimate_unassigned", "estimate_preliminaries")     
workflow.add_edge("estimate_preliminaries", "compile")
workflow.add_edge("compile", END)

report_graph = workflow.compile()


class ReportWorker(QThread):
    finished = Signal(str, str) 
    error = Signal(str)
    progress = Signal(str) 

    def __init__(self, exact_math_data, report_type, provider, model, boq_standard="POMI"):
        super().__init__()
        self.exact_math_data = exact_math_data
        self.report_type = report_type
        self.provider = provider
        self.model = model
        self.boq_standard = boq_standard 

    def run(self):
        try:
            # QTO Logic
            if "QTO" in self.report_type or "Take-off" in self.report_type:
                self.progress.emit("Reviewing Measurement Sheet items for missing costs...")
                estimated_data = estimate_qto_unassigned(self.exact_math_data, self.provider, self.model, self.progress)
                self.progress.emit("Structuring final Measurement Sheet rows...")
                json_output = generate_qto_programmatically(estimated_data)
                
                self.progress.emit("Formatting complete!")
                self.finished.emit(json_output, self.report_type)
                return

            # BOQ Logic
            self.progress.emit("Aggregating room data...")
            aggregated_list = pre_aggregate_boq_data(self.exact_math_data)
            
            initial_state = {
                "raw_items": aggregated_list,
                "report_type": self.report_type,
                "provider": self.provider,
                "model": self.model,
                "boq_standard": self.boq_standard, 
                "categorized_items": [],
                "estimates": [],
                "result_json": "",
                "error": ""
            }
            
            self.progress.emit("Starting AI Pipeline Workflow...")
            current_state = initial_state.copy()
            
            for event in report_graph.stream(initial_state):
                for node_name, state_update in event.items():
                    current_state.update(state_update) 
                    
                    if node_name == "categorize":
                        self.progress.emit(f"Categorizing items into {self.boq_standard} Industry Sections...")
                    elif node_name == "estimate_unassigned":
                        self.progress.emit("Agent calculating costs for unassigned items...")
                    elif node_name == "estimate_preliminaries":
                        self.progress.emit(f"Generating standard preliminary estimates for {self.boq_standard}...")
                    elif node_name == "compile":
                        self.progress.emit("Compiling final JSON report format...")
            
            if current_state.get("error"):
                self.error.emit(current_state["error"])
            else:
                self.finished.emit(current_state["result_json"], self.report_type)
                
        except Exception as e:
            self.error.emit(str(e))