# app/services/plantuml_service.py
import subprocess
from pathlib import Path

PLANTUML_JAR = Path(__file__).resolve().parents[1] / "plantuml.jar"  # backend/plantuml.jar

def render_plantuml_from_text(puml_text: str, output_dir: str, filename_base: str = "plantuml"):
    """
    Write a .puml and call local plantuml.jar to render a PNG.
    Returns the path to the produced PNG.
    """
    outdir = Path(output_dir)
    outdir.mkdir(parents=True, exist_ok=True)
    puml_file = outdir / f"{filename_base}.puml"
    png_file = outdir / f"{filename_base}.png"

    puml_file.write_text(puml_text, encoding="utf-8")

    if not PLANTUML_JAR.exists():
        raise FileNotFoundError(f"plantuml.jar not found at {PLANTUML_JAR}")

    # call PlantUML to generate PNG
    cmd = ["java", "-jar", str(PLANTUML_JAR), "-tpng", str(puml_file), "-charset", "UTF-8"]
    subprocess.run(cmd, check=True, cwd=str(outdir))

    # PlantUML usually writes png alongside the puml file
    if not png_file.exists():
        # PlantUML may name output differently; search for *.png in outdir matching filename_base
        matches = list(outdir.glob(f"{filename_base}*.png"))
        if matches:
            return str(matches[0])
        raise FileNotFoundError("PlantUML did not produce a PNG.")
    return str(png_file)