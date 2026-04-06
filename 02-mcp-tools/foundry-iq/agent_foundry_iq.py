"""
Sample: Foundry IQ Agent (MCP Tool)
=====================================
Demonstrates an end-to-end flow for:
  1. Optionally creating a RemoteTool project connection that registers the Foundry IQ
     knowledge base MCP endpoint in your Foundry project.
  2. Creating (or updating) a Foundry Agent that uses MCPTool to call the knowledge base.
  3. Running a single-turn query against the agent and printing the grounded response.

Authentication: DefaultAzureCredential (az login for local dev, Managed Identity in prod)
Configuration:  config.json in the same directory as this script

How this differs from the AzureAISearchTool (01-search-tool-agent):
  - This sample uses the Foundry IQ agentic retrieval pipeline: the knowledge base
    decomposes the user query into subqueries, runs them in parallel using keyword /
    vector / hybrid search, applies semantic reranking, and synthesizes a grounded answer.
  - The knowledge base is exposed as an MCP server. The agent calls it via MCPTool.
  - Requires: search index + knowledge source + knowledge base (run setup_knowledge_base.py)
    plus a RemoteTool connection pointing to the knowledge base MCP endpoint.

Private VNet / endpoint note:
  The RemoteTool connection uses ProjectManagedIdentity (RBAC-based, no stored credentials),
  which is required when the search service has public network access disabled.
  The Foundry project's managed identity must have the Search Index Data Reader role
  on the Azure AI Search service.

Prerequisites:
  - An Azure AI Foundry project with an LLM deployment
  - An Azure AI Search service with a Foundry IQ knowledge base
    -> Run setup_knowledge_base.py first if you need to create the index, knowledge
       source, and knowledge base.
  - RBAC: Foundry project managed identity needs Search Index Data Reader on the search service
  - RBAC: Your user identity needs ARM write (Contributor or connections/write) on the
    Foundry project to create the RemoteTool connection (only if create_project_connection=true)
  - pip install -r requirements.txt
  - az login when running locally

Reference:
  https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/foundry-iq-connect
"""

import json
import sys
from pathlib import Path

import requests
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import MCPTool, PromptAgentDefinition
from azure.identity import DefaultAzureCredential, get_bearer_token_provider

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CONFIG_PATH = Path(__file__).parent / "config.json"

AGENT_INSTRUCTIONS = """
You are a helpful assistant.

Use the knowledge base tool to answer user questions.
If the knowledge base doesn't contain the answer, respond with "I don't know".

When you use information from the knowledge base, always include citations to the
retrieved sources using the format: 【message_idx:search_idx†source_name】
""".strip()

ARM_API_VERSION = "2025-10-01-preview"
SEARCH_MCP_API_VERSION = "2025-11-01-preview"


def load_config(path: Path) -> dict:
    """Load and validate configuration from config.json."""
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)

    required_keys = [
        "project_endpoint",
        "search_service_endpoint",
        "knowledge_base_name",
        "project_connection_name",
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
# Step 1: Create the RemoteTool project connection (optional)
# ---------------------------------------------------------------------------

def create_project_connection(
    credential: DefaultAzureCredential,
    project_resource_id: str,
    project_connection_name: str,
    kb_mcp_endpoint: str,
) -> None:
    """
    Create (or update) a RemoteTool project connection via Azure Resource Manager.

    The connection target is the knowledge base MCP endpoint on the Azure AI Search
    service. Foundry uses this connection to route agent tool calls to the knowledge
    base and authenticate with the search service via the project's managed identity.

    authType: ProjectManagedIdentity
      RBAC-based auth with no stored credentials. Required for private VNet / endpoint
      scenarios where key-based auth is disabled on the search service.
      The Foundry project's managed identity must have:
        - Search Index Data Reader
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
        f"/connections/{project_connection_name}?api-version={ARM_API_VERSION}"
    )

    payload = {
        "name": project_connection_name,
        "type": "Microsoft.MachineLearningServices/workspaces/connections",
        "properties": {
            "authType": "ProjectManagedIdentity",
            "category": "RemoteTool",
            # The target is the knowledge base MCP endpoint — Foundry routes agent
            # tool calls to this URL and authenticates via project managed identity.
            "target": kb_mcp_endpoint,
            "isSharedToAll": True,
            "metadata": {
                "ApiType": "Azure",
                "audience": "https://search.azure.com/",
            },
        },
    }

    response = requests.put(url, headers=headers, json=payload, timeout=60)
    response.raise_for_status()
    print(f"[OK] Project connection '{project_connection_name}' created/updated.")


# ---------------------------------------------------------------------------
# Step 2: Create the agent
# ---------------------------------------------------------------------------

def create_agent(
    project_client: AIProjectClient,
    agent_name: str,
    agent_model: str,
    kb_mcp_endpoint: str,
    project_connection_name: str,
) -> object:
    """
    Create (or update) a Foundry Agent that uses the Foundry IQ knowledge base
    as an MCP tool for agentic retrieval.
    """
    mcp_kb_tool = MCPTool(
        server_label="knowledge-base",
        server_url=kb_mcp_endpoint,
        require_approval="never",
        # knowledge_base_retrieve is the only MCP tool currently supported
        # by Azure AI Search knowledge bases for Foundry Agent Service.
        allowed_tools=["knowledge_base_retrieve"],
        project_connection_id=project_connection_name,
    )

    agent = project_client.agents.create_version(
        agent_name=agent_name,
        definition=PromptAgentDefinition(
            model=agent_model,
            instructions=AGENT_INSTRUCTIONS,
            tools=[mcp_kb_tool],
        ),
    )

    print(f"[OK] Agent '{agent.name}' version '{agent.version}' created.")
    return agent


# ---------------------------------------------------------------------------
# Step 3: Run a query
# ---------------------------------------------------------------------------

def run_query(project_client: AIProjectClient, agent, user_query: str) -> None:
    """
    Open a conversation session and send a user query to the agent.
    The agent calls the Foundry IQ MCP tool to retrieve grounded answers.
    """
    openai_client = project_client.get_openai_client()

    print(f"\n[USER] {user_query}\n")

    conversation = openai_client.conversations.create()

    response = openai_client.responses.create(
        conversation=conversation.id,
        input=user_query,
        extra_body={
            "agent_reference": {
                "name": agent.name,
                "type": "agent_reference",
            }
        },
    )

    print(f"[AGENT] {response.output_text}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    cfg = load_config(CONFIG_PATH)

    project_endpoint = cfg["project_endpoint"]
    search_service_endpoint = cfg["search_service_endpoint"].rstrip("/")
    knowledge_base_name = cfg["knowledge_base_name"]
    project_connection_name = cfg["project_connection_name"]
    agent_name = cfg["agent_name"]
    agent_model = cfg["agent_model"]
    user_query = cfg["user_query"]

    # MCP endpoint for the Foundry IQ knowledge base
    kb_mcp_endpoint = (
        f"{search_service_endpoint}/knowledgebases/{knowledge_base_name}"
        f"/mcp?api-version={SEARCH_MCP_API_VERSION}"
    )

    credential = DefaultAzureCredential()

    # -- Step 1: Create project connection (optional) --
    if cfg.get("create_project_connection", False):
        project_resource_id = cfg.get("project_resource_id", "")
        if not project_resource_id or project_resource_id.startswith("<"):
            print(
                "ERROR: create_project_connection is true but project_resource_id is "
                "missing or still a placeholder in config.json."
            )
            sys.exit(1)
        print("\n=== Step 1: Creating project connection ===")
        create_project_connection(
            credential=credential,
            project_resource_id=project_resource_id,
            project_connection_name=project_connection_name,
            kb_mcp_endpoint=kb_mcp_endpoint,
        )
    else:
        print("\n=== Step 1: Skipped (create_project_connection=false) ===")
        print(f"  Using existing connection: '{project_connection_name}'.")

    # -- Step 2: Create agent --
    print("\n=== Step 2: Creating agent ===")
    project_client = AIProjectClient(
        endpoint=project_endpoint,
        credential=credential,
    )
    agent = create_agent(
        project_client=project_client,
        agent_name=agent_name,
        agent_model=agent_model,
        kb_mcp_endpoint=kb_mcp_endpoint,
        project_connection_name=project_connection_name,
    )

    # -- Step 3: Run query --
    print("\n=== Step 3: Running query ===")
    run_query(project_client=project_client, agent=agent, user_query=user_query)

    print("\n=== Done ===")
    print(f"Agent '{agent_name}' remains in your Foundry project for subsequent runs.")


if __name__ == "__main__":
    main()
