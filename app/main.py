# app/main.py
import os
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import shutil
import pandas as pd
from dotenv import load_dotenv
from fastapi import Body
from app.services.csv_service import refine_plantuml_code
# main.py
from fastapi.middleware.cors import CORSMiddleware



load_dotenv()

from app.services.csv_service import process_csv_and_generate

BASE_DIR = Path(__file__).resolve().parent.parent
UPLOAD_DIR = BASE_DIR / "uploads"
STATIC_DIR = BASE_DIR / "static"
UPLOAD_DIR.mkdir(exist_ok=True, parents=True)
STATIC_DIR.mkdir(exist_ok=True, parents=True)

app = FastAPI(title="Test Case → PlantUML Generator")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # or ["http://localhost:3000"]
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# serve generated images
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.post("/upload-csv/")
async def upload_csv(file: UploadFile = File(...)):
    filename = file.filename.lower()
    dest = UPLOAD_DIR / file.filename

    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)

    # If Excel, convert to CSV
    if filename.endswith(".xlsx") or filename.endswith(".xls"):
        df = pd.read_excel(dest)
        csv_path = dest.with_suffix(".csv")
        df.to_csv(csv_path, index=False)
        dest = csv_path
    elif not filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV or Excel files allowed")

    # run the phidata agent to produce PlantUML diagram
    result = process_csv_and_generate(str(dest), output_dir=str(STATIC_DIR))
    
    if not result.get("success", False):
        raise HTTPException(status_code=500, detail=result.get("error", "Failed to process test cases"))
    
    return result

@app.get("/")
async def root():
    return {"message": "Test Case to PlantUML Generator API"}

@app.get("/health")
async def health_check():
    return {"status": "healthy"}




@app.post("/chat-plantuml/")
async def chat_plantuml(
    request: dict = Body(...)
):
    plantuml_code = request.get("plantuml_code")
    user_message = request.get("message")
    if not plantuml_code or not user_message:
        raise HTTPException(status_code=400, detail="plantuml_code and message are required")

    result = refine_plantuml_code(
        plantuml_code=plantuml_code,
        message=user_message,
        output_dir=str(STATIC_DIR)
    )

    if not result.get("success", False):
        raise HTTPException(status_code=500, detail=result.get("error", "Failed to refine PlantUML"))

    return result