"""
Sample: Code Interpreter Agent
===============================
Demonstrates an end-to-end flow for:
  1. Uploading a CSV file (diabetes.csv) to the Foundry file store.
  2. Creating a Foundry Agent with CodeInterpreterTool bound to the uploaded file.
  3. Running a single-turn query via the Responses API and printing the response.

Authentication: DefaultAzureCredential (az login for local dev, Managed Identity in prod)
Configuration:  config.json in the same directory as this script

Prerequisites:
  - An Azure AI Foundry project with a gpt-5-mini deployment
  - pip install -r requirements.txt
  - az login (when running locally)
"""

import json
import sys
from pathlib import Path

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
    AutoCodeInterpreterToolParam,
    CodeInterpreterTool,
    PromptAgentDefinition,
)
from azure.identity import DefaultAzureCredential

# ---------------------------------------------------------------------------
# Paths & constants
# ---------------------------------------------------------------------------

CONFIG_PATH = Path(__file__).parent / "config.json"

AGENT_INSTRUCTIONS = """
You are a data analysis assistant specialising in medical datasets.
Use code_interpreter to run Python for statistical analysis of the uploaded CSV.
Always explain your findings in plain language after showing the computed values.
""".strip()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def load_config(path: Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        cfg = json.load(fh)
    required_keys = ["project_endpoint", "agent_name", "agent_model", "user_query"]
    missing = [k for k in required_keys if not cfg.get(k) or str(cfg[k]).startswith("<")]
    if missing:
        print(
            "ERROR: The following config.json values are missing or still contain "
            f"placeholder text:\n  {', '.join(missing)}\n"
            "Please fill in config.json before running this sample."
        )
        sys.exit(1)
    return cfg


def resolve_csv_path(cfg: dict) -> Path:
    csv_relative = cfg.get("csv_file", "data/diabetes.csv")
    csv_path = Path(__file__).parent / csv_relative
    if not csv_path.exists():
        print(f"ERROR: File not found at {csv_path}")
        sys.exit(1)
    return csv_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    cfg = load_config(CONFIG_PATH)
    csv_path = resolve_csv_path(cfg)

    project_client = AIProjectClient(
        endpoint=cfg["project_endpoint"],
        credential=DefaultAzureCredential(),
    )
    openai_client = project_client.get_openai_client()

    # ------------------------------------------------------------------
    # Step 1 – Upload the CSV to the Foundry file store
    # ------------------------------------------------------------------
    print("[1/3] Uploading CSV file ...")
    csv_file = openai_client.files.create(
        purpose="assistants",
        file=open(csv_path, "rb"),
    )
    print(f"      File ID : {csv_file.id}")

    # ------------------------------------------------------------------
    # Step 2 – Create the agent with CodeInterpreterTool bound to the file
    #
    # AutoCodeInterpreterToolParam binds the uploaded file to the code
    # interpreter container so the model can read and execute Python
    # against the raw CSV data.
    # ------------------------------------------------------------------
    print("[2/3] Creating agent ...")
    agent = project_client.agents.create_version(
        agent_name=cfg["agent_name"],
        definition=PromptAgentDefinition(
            model=cfg["agent_model"],
            instructions=AGENT_INSTRUCTIONS,
            tools=[
                CodeInterpreterTool(
                    container=AutoCodeInterpreterToolParam(file_ids=[csv_file.id])
                )
            ],
        ),
    )
    print(f"      Agent '{agent.name}' version '{agent.version}' created.")

    # ------------------------------------------------------------------
    # Step 3 – Run a single-turn query via the Responses API
    # ------------------------------------------------------------------
    print("[3/3] Running query ...")
    print(f"\n[USER] {cfg['user_query']}\n")

    conversation = openai_client.conversations.create()
    response = openai_client.responses.create(
        conversation=conversation.id,
        input=cfg["user_query"],
        extra_body={
            "agent_reference": {
                "name": agent.name,
                "type": "agent_reference",
            }
        },
    )

    print("[AGENT]")
    print("=" * 70)
    print(response.output_text)
    print("=" * 70)
    print(f"\nAgent '{agent.name}' version '{agent.version}' is available in your Foundry project.")


if __name__ == "__main__":
    main()
