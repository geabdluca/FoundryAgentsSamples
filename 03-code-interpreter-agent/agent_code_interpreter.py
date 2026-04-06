"""
Sample: Code Interpreter Agent
===============================
Demonstrates an end-to-end flow for:
  1. Uploading a CSV file (diabetes.csv) to the Azure AI Foundry file store.
  2. Creating a vector store from the description .txt file (required by FileSearchTool).
  3. Creating an agent with TWO tool definitions:
       - CodeInterpreterTool  : executes Python to perform numerical analysis.
       - FileSearchTool       : performs semantic search over file contents.
  4. Creating a thread and posting a user query.
  5. Running the agent — tool_choice forces file_search as the first call;
     system instructions then drive code_interpreter as the second call,
     both within the same single run.
  6. Printing the final agent response.

Note on guaranteeing both tools within one run
-----------------------------------------------
The Agents API tool_choice parameter accepts:
  - "none"                           : no tools allowed
  - "auto"                           : model decides (default)
  - "required"                       : model MUST call at least one tool
  - AgentsNamedToolChoice(type=<T>)  : force one SPECIFIC tool as the FIRST call

Important constraint: tool_choice only governs the FIRST tool call in a run.
After the first tool returns, the model is back in auto mode and chooses
whether to call another tool or produce a final answer.

There is NO single API parameter that forces two specific tools within one run.

The most reliable single-run approach used here:
  1. tool_choice=AgentsNamedToolChoice(FILE_SEARCH)
       → API-guaranteed: file_search is always the first call.
  2. System instructions + user prompt explicitly require code_interpreter next.
       → Highly reliable: the model sees the file_search result in context and
         is instructed to call code_interpreter before answering.

Authentication: DefaultAzureCredential (az login for local dev, Managed Identity in prod)
Configuration:  config.json in the same directory as this script

Prerequisites:
  - An Azure AI Foundry project with a gpt-4.1 deployment
  - pip install -r requirements.txt
  - az login (when running locally)
"""

import json
import sys
from pathlib import Path

from azure.ai.agents import AgentsClient
from azure.ai.agents.models import (
    AgentsNamedToolChoice,
    AgentsNamedToolChoiceType,
    CodeInterpreterTool,
    CodeInterpreterToolResource,
    FilePurpose,
    FileSearchTool,
    FileSearchToolResource,
    MessageRole,
    MessageTextContent,
    RunStatus,
    ToolResources,
)
from azure.identity import DefaultAzureCredential

# ---------------------------------------------------------------------------
# Paths & constants
# ---------------------------------------------------------------------------

CONFIG_PATH = Path(__file__).parent / "config.json"

AGENT_INSTRUCTIONS = """
You are a data analysis assistant specialising in medical datasets.

You have two tools available:
- file_search    : Use this FIRST to describe the dataset columns and their meaning.
- code_interpreter : Use this SECOND to run Python code for statistical analysis.

When the user asks you to analyse the dataset, you MUST:
1. Call file_search to retrieve a description of the dataset structure and columns.
2. Call code_interpreter to compute the requested statistics and present the results.

Always explain your findings in plain language after showing the computed values.
""".strip()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def load_config(path: Path) -> dict:
    """Load and validate configuration from config.json."""
    with open(path, encoding="utf-8") as fh:
        cfg = json.load(fh)

    required_keys = ["project_endpoint", "agent_name", "agent_model", "user_query"]
    missing = [
        k for k in required_keys if not cfg.get(k) or str(cfg[k]).startswith("<")
    ]
    if missing:
        print(
            "ERROR: The following config.json values are missing or still contain "
            f"placeholder text:\n  {', '.join(missing)}\n"
            "Please fill in config.json before running this sample."
        )
        sys.exit(1)
    return cfg


def resolve_data_paths(cfg: dict) -> tuple[Path, Path]:
    """Resolve data file paths relative to the script directory."""
    csv_relative = cfg.get("csv_file", "data/diabetes.csv")
    csv_path = Path(__file__).parent / csv_relative
    desc_path = csv_path.with_name(csv_path.stem + "_description.txt")
    for p in (csv_path, desc_path):
        if not p.exists():
            print(f"ERROR: File not found at {p}")
            sys.exit(1)
    return csv_path, desc_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    cfg = load_config(CONFIG_PATH)
    csv_path, desc_path = resolve_data_paths(cfg)

    client = AgentsClient(
        endpoint=cfg["project_endpoint"],
        credential=DefaultAzureCredential(),
    )

    # Track created resources so cleanup always runs
    csv_file = None
    desc_file = None
    vector_store = None
    agent = None
    thread = None

    try:
        # ------------------------------------------------------------------
        # Step 1 – Upload both files
        #   client.files  →  FilesOperations
        #
        #   CSV  (diabetes.csv)             → bound to CodeInterpreterTool
        #   TXT  (diabetes_description.txt) → indexed in the vector store
        #                                     for FileSearchTool
        #
        #   Note: FileSearch (vector store) does NOT support .csv files.
        #   The description .txt gives FileSearch meaningful content to
        #   search — column names, types, and domain meanings — while the
        #   raw data stays with CodeInterpreter for execution.
        # ------------------------------------------------------------------
        print(f"[1/6] Uploading data files ...")
        csv_file = client.files.upload_and_poll(
            file_path=str(csv_path),
            purpose=FilePurpose.AGENTS,
        )
        print(f"      CSV  file ID  : {csv_file.id}")

        desc_file = client.files.upload_and_poll(
            file_path=str(desc_path),
            purpose=FilePurpose.AGENTS,
        )
        print(f"      DESC file ID  : {desc_file.id}")

        # ------------------------------------------------------------------
        # Step 2 – Create a vector store from the description .txt file
        #   client.vector_stores  →  VectorStoresOperations
        # ------------------------------------------------------------------
        print("[2/6] Creating vector store from description file ...")
        vector_store = client.vector_stores.create_and_poll(
            name="diabetes-vector-store",
            file_ids=[desc_file.id],
        )
        print(f"      Vector store ID : {vector_store.id}")

        # ------------------------------------------------------------------
        # Step 3 – Define the two tools and their resources
        #
        #   CodeInterpreterTool  – csv_file bound so the model can load and
        #                          execute Python against the raw data.
        #   FileSearchTool       – vector store indexed over the description
        #                          txt for semantic column/schema lookup.
        # ------------------------------------------------------------------
        code_interpreter_tool = CodeInterpreterTool()
        file_search_tool = FileSearchTool()

        tool_resources = ToolResources(
            code_interpreter=CodeInterpreterToolResource(
                file_ids=[csv_file.id]
            ),
            file_search=FileSearchToolResource(
                vector_store_ids=[vector_store.id]
            ),
        )

        # ------------------------------------------------------------------
        # Step 4 – Create the agent with both tool definitions
        # ------------------------------------------------------------------
        print("[3/6] Creating agent ...")
        agent = client.create_agent(
            model=cfg["agent_model"],
            name=cfg["agent_name"],
            instructions=AGENT_INSTRUCTIONS,
            tools=code_interpreter_tool.definitions + file_search_tool.definitions,
            tool_resources=tool_resources,
        )
        print(f"      Agent ID : {agent.id}")
        print(f"      Tools    : {[t['type'] for t in agent.tools]}")

        # ------------------------------------------------------------------
        # Step 5 – Create a thread and post the user query
        #   client.threads   →  ThreadsOperations
        #   client.messages  →  MessagesOperations
        # ------------------------------------------------------------------
        print("[4/5] Creating thread and posting user query ...")
        thread = client.threads.create()
        client.messages.create(
            thread_id=thread.id,
            role=MessageRole.USER,
            content=cfg["user_query"],
        )

        # ------------------------------------------------------------------
        # Step 6 – Run the agent (single run, both tools)
        #   client.runs  →  RunsOperations
        #
        #   tool_choice=AgentsNamedToolChoice(FILE_SEARCH)
        #       API-guaranteed: file_search is the first tool call in this run.
        #       After file_search returns its result, the model continues the
        #       run in auto mode. Because the system instructions explicitly
        #       require code_interpreter as the next step, and the file_search
        #       result is now in the thread context, the model reliably calls
        #       code_interpreter before producing its final answer — all within
        #       this single run.
        # ------------------------------------------------------------------
        print("[5/5] Running agent (file_search forced first, code_interpreter driven by instructions) ...")
        run = client.runs.create_and_process(
            thread_id=thread.id,
            agent_id=agent.id,
            tool_choice=AgentsNamedToolChoice(
                type=AgentsNamedToolChoiceType.FILE_SEARCH
            ),
        )
        print(f"      Final run status : {run.status}")

        if run.status != RunStatus.COMPLETED:
            print("\nRun did not complete successfully.")
            if run.last_error:
                print(f"Error code    : {run.last_error.code}")
                print(f"Error message : {run.last_error.message}")
            return

        # ------------------------------------------------------------------
        # Step 7 – Print the final agent response
        #   MessageRole.AGENT is the correct enum value (not ASSISTANT).
        #   get_last_message_text_by_role returns a MessageTextContent or None.
        # ------------------------------------------------------------------
        print("\n[Response]")
        print("=" * 70)
        last_text = client.messages.get_last_message_text_by_role(
            thread_id=thread.id,
            role=MessageRole.AGENT,
        )
        if last_text:
            print(last_text.text.value)
        else:
            print("(no text response found)")
        print("=" * 70)

    finally:
        # ------------------------------------------------------------------
        # Resources are intentionally NOT deleted here so you can review the
        # agent, thread, and run logs in the Azure AI Foundry portal.
        # When you are ready to clean up, call the delete methods below or
        # run a separate cleanup script.
        # ------------------------------------------------------------------
        print("\nResources created (not deleted — review in portal first):")
        if thread is not None:
            print(f"  Thread ID       : {thread.id}")
        if agent is not None:
            print(f"  Agent ID        : {agent.id}")
        if vector_store is not None:
            print(f"  Vector store ID : {vector_store.id}")
        if csv_file is not None:
            print(f"  CSV  file ID    : {csv_file.id}")
        if desc_file is not None:
            print(f"  DESC file ID    : {desc_file.id}")
        print("Done.")


if __name__ == "__main__":
    main()
