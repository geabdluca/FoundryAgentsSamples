"""
Sample: Azure AI Search Tool Agent
====================================
Demonstrates an end-to-end flow for:
  1. Optionally creating a CognitiveSearch project connection that points to your
     Azure AI Search service (skip if you already have one in your Foundry project).
  2. Creating (or updating) a Foundry Agent that uses AzureAISearchTool for
     direct index retrieval — no knowledge base required.
  3. Running a single-turn query against the agent and streaming the response
     with inline citations.

Authentication: DefaultAzureCredential (az login for local dev, Managed Identity in prod)
Configuration:  config.json in the same directory as this script

Scenario vs Foundry IQ (02-mcp-tools/foundry-iq):
  - This sample (AzureAISearchTool) queries the index directly. It is simpler to
    set up and does not require a knowledge source or knowledge base object.
  - Foundry IQ (MCPTool) adds an agentic retrieval layer: LLM-based query planning,
    parallel subquery execution, semantic reranking, and answer synthesis. Use it
    when you need richer retrieval orchestration.

Private VNet / endpoint note:
  The connection MUST use RBAC (ProjectManagedIdentity) when your Azure AI Search
  service has public network access disabled. Key-based authentication is not
  supported with private networking.

Prerequisites:
  - An Azure AI Foundry project with an LLM deployment
  - An Azure AI Search service with an index
    -> Run setup_search.py first if you need to create the index and upload sample docs
  - RBAC on the search service for the Foundry project's managed identity:
      Search Index Data Contributor + Search Service Contributor
  - RBAC on the search service for your user identity (only if running setup_search.py):
      Search Service Contributor + Search Index Data Contributor
  - pip install -r requirements.txt
  - az login when running locally

Reference:
  https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/ai-search
"""

import json
import sys
from pathlib import Path

import requests
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
    AISearchIndexResource,
    AzureAISearchQueryType,
    AzureAISearchTool,
    AzureAISearchToolResource,
    PromptAgentDefinition,
)
from azure.identity import DefaultAzureCredential, get_bearer_token_provider

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CONFIG_PATH = Path(__file__).parent / "config.json"

AGENT_INSTRUCTIONS = """
You are a helpful assistant.

Use the Azure AI Search tool to answer user questions based on the indexed content.
If the index does not contain the answer, respond with "I don't know".

When you use information from the index, always include citations to the retrieved
sources using the format: [message_idx:search_idx†source]
""".strip()

ARM_API_VERSION = "2025-10-01-preview"


def load_config(path: Path) -> dict:
    """Load and validate configuration from config.json."""
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)

    required_keys = [
        "project_endpoint",
        "search_service_endpoint",
        "search_connection_name",
        "index_name",
        "agent_name",
        "agent_model",
        "user_query",
    ]
    missing = [k for k in required_keys if not cfg.get(k) or str(cfg[k]).startswith("<")]
    if missing:
        print(
            "ERROR: The following config.json values are missing or still contain "
            f"placeholder text:\n  {', '.join(missing)}\n"
            "Please fill in config.json before running this sample."
        )
        sys.exit(1)

    return cfg


# ---------------------------------------------------------------------------
# Step 1: Create the search connection (optional)
# ---------------------------------------------------------------------------

def create_search_connection(
    credential: DefaultAzureCredential,
    project_resource_id: str,
    search_connection_name: str,
    search_service_endpoint: str,
) -> None:
    """
    Create (or update) a CognitiveSearch project connection via Azure Resource Manager.

    This registers your Azure AI Search service as a named connection in the Foundry
    project. The agent resolves the full connection resource ID from this name at runtime.

    authType: ProjectManagedIdentity
      RBAC-based auth with no stored credentials. Required for private VNet / endpoint
      scenarios where key-based auth is disabled on the search service.
      The Foundry project's managed identity must have:
        - Search Index Data Contributor
        - Search Service Contributor
      on the Azure AI Search service.
    """
    bearer_token_provider = get_bearer_token_provider(
        credential, "https://management.azure.com/.default"
    )
    headers = {
        "Authorization": f"Bearer {bearer_token_provider()}",
        "Content-Type": "application/json",
    }

    url = (
        f"https://management.azure.com{project_resource_id}"
        f"/connections/{search_connection_name}?api-version={ARM_API_VERSION}"
    )

    payload = {
        "name": search_connection_name,
        "type": "Microsoft.MachineLearningServices/workspaces/connections",
        "properties": {
            "authType": "ProjectManagedIdentity",
            "category": "CognitiveSearch",
            "target": search_service_endpoint.rstrip("/"),
            "isSharedToAll": True,
            "metadata": {
                "ApiType": "Azure",
                "audience": "https://search.azure.com/",
            },
        },
    }

    response = requests.put(url, headers=headers, json=payload, timeout=60)
    response.raise_for_status()
    print(f"[OK] Search connection '{search_connection_name}' created/updated.")


# ---------------------------------------------------------------------------
# Step 2: Create the agent
# ---------------------------------------------------------------------------

def create_agent(
    project_client: AIProjectClient,
    agent_name: str,
    agent_model: str,
    search_connection_name: str,
    index_name: str,
) -> object:
    """
    Create (or update) a Foundry Agent that uses AzureAISearchTool for direct
    index retrieval. The connection name is resolved to a full resource ID via the
    Foundry SDK — you only need to provide the name.
    """
    # Resolve the full connection resource ID from the connection name
    connection = project_client.connections.get(search_connection_name)
    connection_id = connection.id

    search_tool = AzureAISearchTool(
        azure_ai_search=AzureAISearchToolResource(
            indexes=[
                AISearchIndexResource(
                    project_connection_id=connection_id,
                    index_name=index_name,
                    # SIMPLE works with text-only indexes (no vector fields required).
                    # Change to VECTOR_SEMANTIC_HYBRID for richer retrieval if your
                    # index has vector fields and a semantic configuration.
                    query_type=AzureAISearchQueryType.SIMPLE,
                )
            ]
        )
    )

    agent = project_client.agents.create_version(
        agent_name=agent_name,
        definition=PromptAgentDefinition(
            model=agent_model,
            instructions=AGENT_INSTRUCTIONS,
            tools=[search_tool],
        ),
    )

    print(f"[OK] Agent '{agent.name}' version '{agent.version}' created.")
    return agent


# ---------------------------------------------------------------------------
# Step 3: Run a query
# ---------------------------------------------------------------------------

def run_query(project_client: AIProjectClient, agent, user_query: str) -> None:
    """
    Send a user query to the agent and stream the response. The agent uses
    AzureAISearchTool to retrieve grounded answers with inline citations.
    """
    openai_client = project_client.get_openai_client()

    print(f"\n[USER] {user_query}\n")

    stream = openai_client.responses.create(
        stream=True,
        tool_choice="required",
        input=user_query,
        extra_body={"agent_reference": {"name": agent.name, "type": "agent_reference"}},
    )

    citations = []

    for event in stream:
        if event.type == "response.output_text.delta":
            print(event.delta, end="", flush=True)
        elif event.type == "response.output_item.done":
            if event.item.type == "message":
                for content in event.item.content:
                    if content.type == "output_text":
                        for annotation in content.annotations:
                            if annotation.type == "url_citation":
                                citations.append(annotation)

    print()  # newline after streamed output

    if citations:
        print("\n[CITATIONS]")
        for c in citations:
            print(f"  {c.url}  (chars {c.start_index}–{c.end_index})")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    cfg = load_config(CONFIG_PATH)

    project_endpoint = cfg["project_endpoint"]
    search_service_endpoint = cfg["search_service_endpoint"].rstrip("/")
    search_connection_name = cfg["search_connection_name"]
    index_name = cfg["index_name"]
    agent_name = cfg["agent_name"]
    agent_model = cfg["agent_model"]
    user_query = cfg["user_query"]

    credential = DefaultAzureCredential()

    # -- Step 1: Create search connection (optional) --
    if cfg.get("create_search_connection", False):
        project_resource_id = cfg.get("project_resource_id", "")
        if not project_resource_id or project_resource_id.startswith("<"):
            print(
                "ERROR: create_search_connection is true but project_resource_id is "
                "missing or still a placeholder in config.json."
            )
            sys.exit(1)
        print("\n=== Step 1: Creating search connection ===")
        create_search_connection(
            credential=credential,
            project_resource_id=project_resource_id,
            search_connection_name=search_connection_name,
            search_service_endpoint=search_service_endpoint,
        )
    else:
        print("\n=== Step 1: Skipped (create_search_connection=false) ===")
        print(f"  Using existing connection: '{search_connection_name}'.")

    project_client = AIProjectClient(
        endpoint=project_endpoint,
        credential=credential,
    )

    # -- Step 2: Create agent --
    print("\n=== Step 2: Creating agent ===")
    agent = create_agent(
        project_client=project_client,
        agent_name=agent_name,
        agent_model=agent_model,
        search_connection_name=search_connection_name,
        index_name=index_name,
    )

    # -- Step 3: Run query --
    print("\n=== Step 3: Running query ===")
    run_query(project_client=project_client, agent=agent, user_query=user_query)

    print("\n=== Done ===")
    print(f"Agent '{agent_name}' remains in your Foundry project for subsequent runs.")


if __name__ == "__main__":
    main()
