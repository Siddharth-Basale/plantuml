import requests
import json
from tabulate import tabulate
from InquirerPy import inquirer

BASE_URL = "http://127.0.0.1:8000"   # FastAPI server
FILE_PATH = "sample.xlsx"            # your input file


def test_upload_csv():
    url = f"{BASE_URL}/upload-csv/"
    files = {"file": open(FILE_PATH, "rb")}
    resp = requests.post(url, files=files)
    print("\n--- /upload-csv/ ---")
    print("Status:", resp.status_code)
    data = resp.json()
    if not data.get("success"):
        print("Upload failed:", data)
        return None
    test_cases = data["test_cases"]

    # Display in table
    table = [(tc["id"], tc["title"], len(tc.get("steps", []))) for tc in test_cases]
    print(tabulate(table, headers=["ID", "Title", "Steps"], tablefmt="grid"))

    return test_cases


def edit_test_cases(test_cases):
    """Minimal CLI editor: pick one test case and modify title or expected."""
    while True:
        # let user pick which test case to edit
        choices = [f"{tc['id']} - {tc['title']}" for tc in test_cases] + ["[Finish editing]"]
        choice = inquirer.select(
            message="Select a test case to edit:",
            choices=choices
        ).execute()

        if choice == "[Finish editing]":
            break

        idx = choices.index(choice)
        tc = test_cases[idx]

        # ask what to edit
        action = inquirer.select(
            message=f"What do you want to edit in {tc['id']}?",
            choices=["Title", "Expected (all steps)", "Skip"]
        ).execute()

        if action == "Title":
            new_title = inquirer.text(message="Enter new title:").execute()
            tc["title"] = new_title
        elif action == "Expected (all steps)":
            new_expected = inquirer.text(message="Enter expected result:").execute()
            for step in tc.get("steps", []):
                step["expected"] = new_expected
            tc["expected"] = new_expected

    return test_cases


def test_generate_diagram(test_cases):
    url = f"{BASE_URL}/generate-diagram/"
    payload = {"test_cases": test_cases}
    resp = requests.post(url, json=payload)
    print("\n--- /generate-diagram/ ---")
    print("Status:", resp.status_code)
    data = resp.json()
    if not data.get("success"):
        print("Diagram generation failed:", data)
        return None

    print("PlantUML code (first 200 chars):")
    print(data["plantuml_code"][:200], "...")
    print("Image URL:", data["plantuml_image"])
    return data


def test_chat_plantuml(plantuml_code):
    url = f"{BASE_URL}/chat-plantuml/"
    payload = {
        "plantuml_code": plantuml_code,
        "message": "Add a database actor and show it saving user data"
    }
    resp = requests.post(url, json=payload)
    print("\n--- /chat-plantuml/ ---")
    print("Status:", resp.status_code)
    data = resp.json()
    if not data.get("success"):
        print("Refinement failed:", data)
        return None

    print("Refined PlantUML code (first 200 chars):")
    print(data["plantuml_code"][:200], "...")
    print("Updated image URL:", data["plantuml_image"])


if __name__ == "__main__":
    # Step 1: Upload CSV/Excel → get test cases
    test_cases = test_upload_csv()
    if not test_cases:
        exit(1)

    # Step 2: Optional edit
    do_edit = inquirer.confirm(message="Do you want to edit test cases?", default=False).execute()
    if do_edit:
        test_cases = edit_test_cases(test_cases)

    # Step 3: Generate diagram
    diagram_result = test_generate_diagram(test_cases)
    if not diagram_result:
        exit(1)

    # Step 4: Refine with chat
    test_chat_plantuml(diagram_result["plantuml_code"])
