# app/services/csv_service.py
import re
import pandas as pd
import tempfile
import os
from pathlib import Path
from phi.agent import Agent
from phi.model.openai import OpenAIChat

from phi.tools.csv_tools import CsvTools
from phi.tools.python import PythonTools

from .plantuml_service import render_plantuml_from_text


def _extract_code_block(text: str, lang_hint: str = None) -> str:
    """Extract triple-backtick fenced block. If lang_hint provided, prefer fence ```lang_hint"""
    if lang_hint:
        pattern = rf"```{lang_hint}\s*([\s\S]*?)```"
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            return m.group(1).strip()

    # fallback to any fenced block
    m = re.search(r"```(?:\w+)?\s*([\s\S]*?)```", text)
    return m.group(1).strip() if m else text.strip()


def process_csv_and_generate(csv_path: str, output_dir: str):
    """Process CSV with Phidata Agent to generate PlantUML diagram from test cases."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, encoding='utf-8') as tmp_file:
        df = pd.read_csv(csv_path)
        df.to_csv(tmp_file.name, index=False)
        tmp_csv_path = tmp_file.name

    try:
        csv_tool = CsvTools(
            csvs=[tmp_csv_path],
            read_csvs=True,
            list_csvs=True,
            read_column_names=True
        )
        py_tool = PythonTools(
            base_dir=Path(output_dir),
            save_and_run=True,
            run_code=True,
        )

        agent = Agent(
            name="Test Case to PlantUML Agent",
            model=OpenAIChat(id="gpt-4o-mini"),
            tools=[csv_tool, py_tool],
            instructions=[
                "You are an expert at analyzing test cases and creating PlantUML sequence diagrams.",
                "First, examine the test case data to identify:",
                "1. All actors involved (users, systems, services, databases, cron jobs, etc.)",
                "2. The sequence of activities/steps in the end-to-end flow",
                "3. Interactions between different components",
                "Then create a PlantUML sequence diagram that visualizes this end-to-end flow.",
                "For PlantUML: return ONLY a fenced code block with ```plantuml.",
                "Do NOT include any explanations or prose outside code blocks.",
                "Make the diagram clear, with proper sequencing and appropriate participant names."
            ],
            markdown=True,
            show_tool_calls=True,
        )

        puml_prompt = (
            "Analyze the test cases and create a PlantUML sequence diagram that represents "
            "the end-to-end flow with all actors and their interactions.\n\n"
            "Rules:\n"
            "1. Identify all participants (users, frontend, backend systems, databases, cron jobs, etc.)\n"
            "2. Map the sequence of activities from the test cases\n"
            "3. Show interactions between participants with clear messages\n"
            "4. Use appropriate PlantUML syntax for sequence diagrams\n"
            "5. Output only a single fenced code block using ```plantuml\n\n"
            "First, examine the CSV data to understand the test cases, then generate the diagram."
        )

        resp = agent.run(puml_prompt)
        puml_text_raw = resp.content if hasattr(resp, "content") else str(resp)
        plantuml_code = _extract_code_block(puml_text_raw, lang_hint="plantuml")

        # Render PlantUML → PNG
        puml_img_path = render_plantuml_from_text(
            plantuml_code, output_dir=output_dir, filename_base="e2e_test_diagram"
        )

        # Extract actors & activities
        actors = _extract_actors_from_plantuml(plantuml_code)
        activities = _extract_activities_from_plantuml(plantuml_code)

        host_prefix = "/static"
        return {
            "success": True,
            "plantuml_code": plantuml_code,
            "plantuml_image": f"{host_prefix}/{Path(puml_img_path).name}",
            "actors": actors,
            "activities": activities
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "plantuml_code": None,
            "plantuml_image": None,
            "actors": [],
            "activities": []
        }

    finally:
        if os.path.exists(tmp_csv_path):
            os.unlink(tmp_csv_path)


def _extract_actors_from_plantuml(plantuml_code: str) -> list:
    """Extract actors/participants from PlantUML code"""
    actors = []
    participant_patterns = [
        r'participant\s+"([^"]+)"', r'participant\s+(\w+)',
        r'actor\s+"([^"]+)"', r'actor\s+(\w+)',
        r'entity\s+"([^"]+)"', r'entity\s+(\w+)',
        r'boundary\s+"([^"]+)"', r'boundary\s+(\w+)',
        r'control\s+"([^"]+)"', r'control\s+(\w+)',
        r'database\s+"([^"]+)"', r'database\s+(\w+)',
        r'collections\s+"([^"]+)"', r'collections\s+(\w+)',
        r'queue\s+"([^"]+)"', r'queue\s+(\w+)'
    ]
    for pattern in participant_patterns:
        matches = re.findall(pattern, plantuml_code, re.IGNORECASE)
        actors.extend(matches)
    return sorted(set(actors))


def _extract_activities_from_plantuml(plantuml_code: str) -> list:
    """Extract activities/interactions (messages) from PlantUML sequence code."""
    return [line.strip() for line in plantuml_code.splitlines() if "->" in line and ":" in line]


def refine_plantuml_code(plantuml_code: str, message: str, output_dir: str):
    """Use AI to refine existing PlantUML code based on user message."""
    from phi.agent import Agent
    from phi.model.openai import OpenAIChat

    try:
        agent = Agent(
            name="PlantUML Refiner",
            model=OpenAIChat(id="gpt-4o-mini"),
            instructions=[
                "You are an expert PlantUML editor.",
                "Take the provided PlantUML code and modify it according to the user's request.",
                "Return ONLY the updated PlantUML code in a fenced code block (```plantuml ... ```).",
                "Do not add explanations or comments outside the code block."
            ],
            markdown=True
        )

        resp = agent.run(
            f"Here is the current PlantUML code:\n```plantuml\n{plantuml_code}\n```\n\n"
            f"User request: {message}\n\n"
            "Please return the updated PlantUML code."
        )

        updated_code = _extract_code_block(resp.content, lang_hint="plantuml")
        img_path = render_plantuml_from_text(updated_code, output_dir=output_dir, filename_base="e2e_test_diagram")

        host_prefix = "/static"
        return {
            "success": True,
            "plantuml_code": updated_code,
            "plantuml_image": f"{host_prefix}/{Path(img_path).name}",
            "actors": _extract_actors_from_plantuml(updated_code),
            "activities": _extract_activities_from_plantuml(updated_code)
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "plantuml_code": None,
            "plantuml_image": None,
            "actors": [],
            "activities": []
        }
