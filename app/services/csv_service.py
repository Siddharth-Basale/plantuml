# app/services/csv_service.py
import re
import pandas as pd
import tempfile
import os
import csv
import json
from pathlib import Path
from phi.agent import Agent
from phi.model.openai import OpenAIChat
from phi.tools.csv_tools import CsvTools
from .plantuml_service import render_plantuml_from_text


def _extract_code_block(text: str, lang_hint: str = None) -> str:
    if lang_hint:
        pattern = rf"```{lang_hint}\s*([\s\S]*?)```"
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    m = re.search(r"```(?:\w+)?\s*([\s\S]*?)```", text)
    return m.group(1).strip() if m else text.strip()


def construct_test_cases_from_csv(csv_path: str) -> list:
    """
    Build test cases from CSV whether or not it explicitly contains them.
    Returns list of {id, title, description, steps, actors, expected}.
    """
    df = pd.read_csv(csv_path)
    cols_lower_to_actual = {c.lower(): c for c in df.columns}

    # Detect grouping column
    candidate_group_cols = ["test_case_id", "test_case", "scenario", "title", "id"]
    group_col = None
    for cand in candidate_group_cols:
        if cand in cols_lower_to_actual:
            group_col = cols_lower_to_actual[cand]
            break

    test_cases = []
    if group_col:
        grouped = df.groupby(group_col, sort=False)
        for name, group in grouped:
            steps = []
            actor_col = next(
                (cols_lower_to_actual[c] for c in ["actor", "actors"] if c in cols_lower_to_actual), None
            )
            action_col = next(
                (cols_lower_to_actual[c] for c in ["action", "description", "step_action"] if c in cols_lower_to_actual), None
            )
            expected_col = next(
                (cols_lower_to_actual[c] for c in ["expected", "expected_result", "result"] if c in cols_lower_to_actual), None
            )

            for idx, row in group.iterrows():
                steps.append(
                    {
                        "step_number": idx + 1,
                        "actor": row[actor_col] if actor_col else None,
                        "action": row[action_col] if action_col else row.to_dict(),
                        "expected": row[expected_col] if expected_col else "",
                    }
                )

            actors = sorted({s["actor"] for s in steps if s.get("actor")})
            test_cases.append(
                {
                    "id": str(name),
                    "title": str(name),
                    "description": "",
                    "steps": steps,
                    "actors": actors,
                    "expected": "",
                }
            )
    else:
        # No grouping — each row = one test case
        for idx, row in df.iterrows():
            test_cases.append(
                {
                    "id": f"TC_{idx+1}",
                    "title": str(row[df.columns[0]]),
                    "description": "",
                    "steps": [
                        {"step_number": 1, "actor": None, "action": row.to_dict(), "expected": ""}
                    ],
                    "actors": [],
                    "expected": "",
                }
            )

    return test_cases


def _write_test_cases_to_temp_csv(test_cases: list) -> str:
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8", newline="")
    fieldnames = ["test_case_id", "title", "step_number", "actor", "action", "expected"]
    writer = csv.DictWriter(tmp, fieldnames=fieldnames)
    writer.writeheader()

    for i, tc in enumerate(test_cases, start=1):
        tc_id = tc.get("id", f"TC_{i}")
        title = tc.get("title", "")
        for j, step in enumerate(tc.get("steps", []), start=1):
            action = step.get("action")
            if isinstance(action, (dict, list)):
                action = json.dumps(action, default=str)
            writer.writerow(
                {
                    "test_case_id": tc_id,
                    "title": title,
                    "step_number": j,
                    "actor": step.get("actor", ""),
                    "action": action,
                    "expected": step.get("expected", ""),
                }
            )

    tmp.flush()
    tmp.close()
    return tmp.name


def process_csv_and_generate(csv_path: str = None, output_dir: str = ".", test_cases: list = None) -> dict:
    """
    Accepts either csv_path or test_cases list. Writes a temp CSV, then runs AI → PlantUML.
    """
    tmp_csv_path = None
    try:
        if test_cases:
            tmp_csv_path = _write_test_cases_to_temp_csv(test_cases)
        else:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as tmp_file:
                df = pd.read_csv(csv_path)
                df.to_csv(tmp_file.name, index=False)
                tmp_csv_path = tmp_file.name

        csv_tool = CsvTools(csvs=[tmp_csv_path], read_csvs=True, list_csvs=True, read_column_names=True)

        agent = Agent(
            name="Test Case to PlantUML Agent",
            model=OpenAIChat(id="gpt-4o-mini"),
            tools=[csv_tool],
            instructions=[
                "You are an expert at analyzing test cases and creating PlantUML sequence diagrams.",
                "Examine test case data → identify actors, steps, interactions.",
                "Return only ```plantuml fenced code```.",
            ],
            markdown=True,
        )

        resp = agent.run("Analyze the test cases and create a PlantUML sequence diagram.")
        puml_text_raw = resp.content if hasattr(resp, "content") else str(resp)
        plantuml_code = _extract_code_block(puml_text_raw, lang_hint="plantuml")

        img_path = render_plantuml_from_text(plantuml_code, output_dir=output_dir, filename_base="e2e_test_diagram")

        return {
            "success": True,
            "plantuml_code": plantuml_code,
            "plantuml_image": f"/static/{Path(img_path).name}",
            "actors": _extract_actors_from_plantuml(plantuml_code),
            "activities": _extract_activities_from_plantuml(plantuml_code),
        }
    except Exception as e:
        return {"success": False, "error": str(e), "plantuml_code": None, "plantuml_image": None, "actors": [], "activities": []}
    finally:
        if tmp_csv_path and os.path.exists(tmp_csv_path):
            os.unlink(tmp_csv_path)


def _extract_actors_from_plantuml(plantuml_code: str) -> list:
    patterns = [
        r'participant\s+"([^"]+)"', r"participant\s+(\w+)",
        r'actor\s+"([^"]+)"', r"actor\s+(\w+)",
        r'entity\s+"([^"]+)"', r"entity\s+(\w+)",
    ]
    actors = []
    for p in patterns:
        actors.extend(re.findall(p, plantuml_code, re.IGNORECASE))
    return sorted(set(actors))


def _extract_activities_from_plantuml(plantuml_code: str) -> list:
    return [line.strip() for line in plantuml_code.splitlines() if "->" in line and ":" in line]


def refine_plantuml_code(plantuml_code: str, message: str, output_dir: str):
    try:
        agent = Agent(
            name="PlantUML Refiner",
            model=OpenAIChat(id="gpt-4o-mini"),
            instructions=[
                "Modify the provided PlantUML code according to user request.",
                "Return ONLY fenced ```plantuml code```.",
            ],
            markdown=True,
        )
        resp = agent.run(f"```plantuml\n{plantuml_code}\n```\n\nUser request: {message}")
        updated_code = _extract_code_block(resp.content, lang_hint="plantuml")
        img_path = render_plantuml_from_text(updated_code, output_dir=output_dir, filename_base="e2e_test_diagram")

        return {
            "success": True,
            "plantuml_code": updated_code,
            "plantuml_image": f"/static/{Path(img_path).name}",
            "actors": _extract_actors_from_plantuml(updated_code),
            "activities": _extract_activities_from_plantuml(updated_code),
        }
    except Exception as e:
        return {"success": False, "error": str(e), "plantuml_code": None, "plantuml_image": None, "actors": [], "activities": []}
