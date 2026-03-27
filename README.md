<div align="center">
    <img src="resources/logo.png" alt="Logo" width="200"/>
    <h1 align="center">Application for Automated Bill of Quantities Generation & Extraction of Architectural Elements from 2D Floor Plans</h1>
    <h5 align="center">Geo Noel Jeesan | 2509624 | gnj224@student.bham.ac.uk</h5>
</div>

## Overview
This project is a desktop application designed for quantity surveyors, estimators, and architects. It automates the extraction of architectural features from 2D floor plans (PDFs or Images) to rapidly generate a Bill of Quantities (BOQ). The software combines deep learning for image segmentation, Optical Character Recognition (OCR) for text extraction, 3D visualization, and an AI Chatbot for assisted analysis.

## Problem Statement
Quantity surveyors and estimators spend a significant amount of time manually taking measurements, calculating areas, and counting items from 2D floor plans to generate a Bill of Quantities. This manual takeoff process is tedious, time consuming, and prone to error. Furthermore, visualizing the spatial layout requires mental effort or separate, complex CAD software. There is a need for an automated solution that bridges the gap between 2D architectural drawings and actionable cost estimations.

## Objectives
- **Automated Takeoff:** Automate the extraction of room areas, walls, doors, windows, and architectural fixtures from 2D floor plans.
- **Text Extraction:** Extract textual information (e.g., room names, dimensions) from floor plans using robust multi-directional OCR.
- **Automated BOQ Generation:** Link extracted spatial data to a built in materials and pricing database to generate accurate cost estimates.
- **Interactive 3D Visualization:** Allow users to instantly visualize 2D floor plans into interactive 3D models.
- **AI Assistance:** Provide an integrated AI Chatbot to assist users with BOQ queries, material selection, and software usage.

## Methodology
The application is built using a modern technology stack to ensure performance, accuracy, and a user-friendly experience:
1. **User Interface:** Built with **PySide6**, featuring a modern, responsive design, dark mode, custom splash screens, and Windows Mica effect support.
2. **AI Semantic Segmentation:** Utilizes a **PyTorch**-based deep learning model (`hg_furukawa_original`) trained on the CubiCasa5k dataset. The model segments floor plans into distinct layers for rooms, walls, and icons (doors, windows, fixtures), extracting polygons and areas.
3. **Optical Character Recognition (OCR):** Integrates **EasyOCR** with a custom multi-directional scanning approach (0°, 90°, 180°, 270°) and Non-Maximum Suppression (NMS) to accurately capture rotated text commonly found in architectural blueprints.
4. **Database Integration:** A local **SQLite** database (`boq_materials.db`) stores materials, pricing, and fixtures (e.g., Floors, Walls, Doors, Plumbing), enabling real-time cost lookups.
5. **3D Visualization:** Uses **PyOpenGL** and 3D rendering libraries to extrude 2D polygons into an interactive 3D scene based on user defined parameters (e.g., wall heights).
6. **LLM Chatbot Integration:** Uses **LangChain** to connect with various Large Language Models (Ollama for local inference, OpenAI, Google GenAI, Anthropic, OpenRouter) to provide an intelligent assistant directly within the application.

## Results
The **PDF BOQ Viewer** significantly reduces the time required for manual takeoff. By combining spatial segmentation with OCR, the application accurately identifies rooms and calculates their areas, subsequently generating detailed, scaled BOQ estimates. The built-in 3D modeler gives estimators an immediate spatial understanding of the project without needing external CAD tools, and the AI chatbot provides contextual assistance on demand.

## Demo

https://www.youtube.com/watch?v=ADBbxf-RhVI

## Running

### Note
It is highly recommended to run this on Windows. Although theoretically it can run on Linux and macOS, it has not been tested in other Operating Systems.

### Prerequisites
- Python 3.10 or higher.
- A compatible GPU is recommended for faster AI model inference (PyTorch with CUDA), though it can run on a CPU.

### Installation Steps

1. **Clone the Repository:**
   Ensure you have all the project files in your local directory.

2. **Create a Virtual Environment (Optional but recommended):**
   ```bash
   python -m venv .venv
   # Windows:
   .venv\Scripts\activate
   # macOS/Linux:
   source .venv/bin/activate
   ```

3. **Install Dependencies:**
   Install all required Python packages listed in `requirements.txt`:
   ```bash
   pip install -r requirements.txt
   ```

4. **Ensure the AI Model is Present:**
   Make sure the `model_best_val_loss_var.pkl` file is in the root directory. This is the pre-trained weights file required for the CubiCasa segmentation model.

5. **Run the Application:**
   Start the application by running the main entry script:
   ```bash
   python main.py
   ```

### Configuration
- **Settings & API Keys:** You can configure API keys for the AI Chatbot (OpenAI, Google, Anthropic, etc.) directly within the application via the **Settings** menu (gear icon). This will save your configurations to a `.env` file automatically. Running models locally using Ollama is also supported and is the default. You need to set atleast one of these to get the chatbot and QTO/BOQ generation to work.
