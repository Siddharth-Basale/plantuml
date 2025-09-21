# app/main.py
import os
import shutil
import json
from pathlib import Path
import pandas as pd
from fastapi import FastAPI, UploadFile, File, HTTPException, Body
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from app.services.csv_service import (
    construct_test_cases_from_csv,
    process_csv_and_generate,
    refine_plantuml_code,
)

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
UPLOAD_DIR = BASE_DIR / "uploads"
STATIC_DIR = BASE_DIR / "static"
UPLOAD_DIR.mkdir(exist_ok=True, parents=True)
STATIC_DIR.mkdir(exist_ok=True, parents=True)

app = FastAPI(title="Test Case → PlantUML Generator")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # or restrict e.g. ["http://localhost:3000"]
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve generated images
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def root():
    return {"message": "Test Case to PlantUML Generator API"}


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


@app.post("/upload-csv/")
async def upload_csv(file: UploadFile = File(...)):
    """
    Upload CSV/Excel → construct test cases (even if missing) → return JSON
    for frontend editing. No PlantUML is generated yet.
    """
    filename = file.filename.lower()
    dest = UPLOAD_DIR / file.filename

    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)

    # Convert Excel → CSV
    if filename.endswith(".xlsx") or filename.endswith(".xls"):
        df = pd.read_excel(dest)
        csv_path = dest.with_suffix(".csv")
        df.to_csv(csv_path, index=False)
        dest = csv_path
    elif not filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV or Excel files allowed")

    try:
        test_cases = construct_test_cases_from_csv(str(dest))

        # Serialize safely for frontend
        def _serialize(tc_list):
            out = []
            for tc in tc_list:
                tc_copy = dict(tc)
                steps = []
                for s in tc_copy.get("steps", []):
                    s_copy = dict(s)
                    if isinstance(s_copy.get("action"), (dict, list)):
                        s_copy["action"] = json.dumps(s_copy["action"], default=str)
                    steps.append(s_copy)
                tc_copy["steps"] = steps
                out.append(tc_copy)
            return out

        return {"success": True, "test_cases": _serialize(test_cases)}

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to parse CSV and construct test cases: {e}"
        )


@app.post("/generate-diagram/")
async def generate_diagram(request: dict = Body(...)):
    """
    Accept edited test_cases JSON from frontend and resume PlantUML pipeline.
    """
    test_cases = request.get("test_cases")
    if not test_cases or not isinstance(test_cases, list):
        raise HTTPException(status_code=400, detail="No test_cases provided")

    result = process_csv_and_generate(
        csv_path=None, output_dir=str(STATIC_DIR), test_cases=test_cases
    )

    if not result.get("success", False):
        raise HTTPException(
            status_code=500,
            detail=result.get("error", "Failed to process test cases"),
        )

    return result


@app.post("/chat-plantuml/")
async def chat_plantuml(request: dict = Body(...)):
    plantuml_code = request.get("plantuml_code")
    user_message = request.get("message")
    if not plantuml_code or not user_message:
        raise HTTPException(
            status_code=400, detail="plantuml_code and message are required"
        )

    result = refine_plantuml_code(
        plantuml_code=plantuml_code, message=user_message, output_dir=str(STATIC_DIR)
    )

    if not result.get("success", False):
        raise HTTPException(
            status_code=500,
            detail=result.get("error", "Failed to refine PlantUML"),
        )

    return result
