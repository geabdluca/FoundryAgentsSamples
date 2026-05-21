"""
Sample: OpenAPI Tool Agent (Azure API Management)
==================================================
Demonstrates an end-to-end flow for:
  1. Creating a Foundry Agent that uses OpenApiTool to call an Azure API Management
     endpoint. The agent forwards natural-language questions to the APIM-hosted API
     and returns the plain-text answer.
  2. Running a single-turn query against the agent and streaming the response.

Authentication:
  - Azure AI Foundry: DefaultAzureCredential (az login locally, Managed Identity in prod)
  - APIM endpoint:    Subscription key stored as a Foundry CustomKeys connection.
                      The OpenApiTool runtime injects the key header automatically —
                      no credentials appear in agent code or config.

Configuration:  config.json in the same directory as this script

How this compares to other samples in this repo:
  - 01-search-tool-agent (AzureAISearchTool): queries an AI Search index directly.
  - 02-mcp-tools/foundry-iq (MCPTool): calls a knowledge base via MCP for agentic
    retrieval with query planning and semantic reranking.
  - This sample (OpenApiTool): gives the agent the ability to call any HTTP API
    described by an OpenAPI spec. APIM acts as the gateway with subscription-key auth.

Prerequisites:
  - An Azure AI Foundry project with an LLM deployment
  - An APIM instance with the Contoso IT Helpdesk API deployed
    -> Run setup_apim_api.py first to create the API and the Foundry connection
  - The Foundry project must have a CustomKeys connection named <apim_connection_name>
    containing the APIM subscription key (created by setup_apim_api.py)
  - pip install -r requirements.txt
  - az login when running locally

Reference:
  https://learn.microsoft.com/en-us/azure/ai-services/agents/how-to/tools/openapi-spec
"""

import json
import sys
from pathlib import Path

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
    OpenApiFunctionDefinition,
    OpenApiProjectConnectionAuthDetails,
    OpenApiProjectConnectionSecurityScheme,
    OpenApiTool,
    PromptAgentDefinition,
)
from azure.identity import DefaultAzureCredential

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CONFIG_PATH = Path(__file__).parent / "config.json"
SPEC_PATH = Path(__file__).parent / "openapi_spec.json"

AGENT_INSTRUCTIONS = """
You are a Contoso IT support assistant.

When the user asks about IT incidents, service requests, outages, or any IT helpdesk
topic, use the queryContosoITHelpdesk tool to retrieve an answer.

Return the answer from the tool directly to the user. If the tool call fails or
returns no useful answer, say "I was unable to retrieve that information right now."
""".strip()


def load_config(path: Path) -> dict:
    """Load and validate configuration from config.json."""
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)

    required_keys = [
        "project_endpoint",
        "apim_service_name",
        "apim_api_path",
        "apim_connection_name",
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


def load_spec(spec_path: Path, service_name: str, api_path: str) -> dict:
    """
    Load openapi_spec.json and patch servers[0].url to the real APIM gateway URL.

    The spec is embedded in the agent definition at creation time, so the URL must
    be correct before the agent is created.
    """
    with open(spec_path, encoding="utf-8") as f:
        spec = json.load(f)

    # APIM default gateway URLs are always lowercase regardless of the resource name casing
    spec["servers"][0]["url"] = f"https://{service_name.lower()}.azure-api.net/{api_path}"
    return spec


# ---------------------------------------------------------------------------
# Step 1: Create the agent
# ---------------------------------------------------------------------------

def create_agent(
    project_client: AIProjectClient,
    agent_name: str,
    agent_model: str,
    connection_name: str,
    spec: dict,
) -> object:
    """
    Create (or version) a Foundry Agent that uses OpenApiTool to call the APIM endpoint.

    Auth flow:
      - The Foundry project has a CustomKeys connection (<apim_connection_name>) that
        stores the APIM subscription key under 'Ocp-Apim-Subscription-Key'.
      - OpenApiConnectionAuthDetails tells the Foundry runtime to look up that connection
        and inject the key as a request header when the agent calls the tool.
      - The subscription key never appears in agent code, config, or logs.
    """
    # Resolve the full connection resource ID from the human-readable connection name
    connection = project_client.connections.get(connection_name)

    openapi_tool = OpenApiTool(
        openapi=OpenApiFunctionDefinition(
            name="contoso_itdesk",
            spec=spec,
            description=(
                "Query the Contoso IT Helpdesk agent for information about IT incidents, "
                "service requests, outages, and IT policies."
            ),
            auth=OpenApiProjectConnectionAuthDetails(
                security_scheme=OpenApiProjectConnectionSecurityScheme(
                    project_connection_id=connection.id
                )
            ),
        )
    )

    agent = project_client.agents.create_version(
        agent_name=agent_name,
        definition=PromptAgentDefinition(
            model=agent_model,
            instructions=AGENT_INSTRUCTIONS,
            tools=[openapi_tool],
        ),
    )

    print(f"[OK] Agent '{agent.name}' version '{agent.version}' created.")
    return agent


# ---------------------------------------------------------------------------
# Step 2: Run a query
# ---------------------------------------------------------------------------

def run_query(project_client: AIProjectClient, agent, user_query: str) -> None:
    """
    Send a user query to the agent and stream the response.

    The agent calls queryContosoITHelpdesk via the OpenApiTool, which POSTs to the
    APIM endpoint with the subscription key injected from the Foundry connection.
    """
    openai_client = project_client.get_openai_client()

    print(f"\n[USER] {user_query}\n")

    stream = openai_client.responses.create(
        stream=True,
        tool_choice="required",
        input=user_query,
        extra_body={"agent_reference": {"name": agent.name, "type": "agent_reference"}},
    )

    print("[AGENT] ", end="", flush=True)
    for event in stream:
        if event.type == "response.output_text.delta":
            print(event.delta, end="", flush=True)
    print()  # newline after streamed output


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    cfg = load_config(CONFIG_PATH)

    project_endpoint = cfg["project_endpoint"]
    service_name = cfg["apim_service_name"]
    api_path = cfg["apim_api_path"]
    connection_name = cfg["apim_connection_name"]
    agent_name = cfg["agent_name"]
    agent_model = cfg["agent_model"]
    user_query = cfg["user_query"]

    credential = DefaultAzureCredential()

    spec = load_spec(SPEC_PATH, service_name, api_path)

    project_client = AIProjectClient(
        endpoint=project_endpoint,
        credential=credential,
    )

    # -- Step 1: Create agent --
    print("\n=== Step 1: Creating agent ===")
    agent = create_agent(
        project_client=project_client,
        agent_name=agent_name,
        agent_model=agent_model,
        connection_name=connection_name,
        spec=spec,
    )

    # -- Step 2: Run query --
    print("\n=== Step 2: Running query ===")
    run_query(project_client=project_client, agent=agent, user_query=user_query)

    print("\n=== Done ===")
    print(f"Agent '{agent_name}' remains in your Foundry project for subsequent runs.")


if __name__ == "__main__":
    main()
