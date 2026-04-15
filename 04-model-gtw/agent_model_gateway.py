"""
Sample: Model Gateway Agent
============================
Demonstrates an end-to-end flow for:
  1. Creating a Foundry Agent backed by a ModelGateway connection — the agent
     routes inference through the gateway to a remote AI resource using OAuth2
     client credentials (Entra ID) stored in the connection, not in this script.
  2. Running a single-turn query against the agent and streaming the response.

Authentication: DefaultAzureCredential (az login for local dev, Managed Identity in prod)
                The ModelGateway connection authenticates to the target resource using
                OAuth2 client credentials — no SP secrets required in this script.
Configuration:  config.json in the same directory as this script

Prerequisites:
  - Azure AI Foundry project with a ModelGateway connection already deployed
    -> Deploy the connection first using connection-modelgateway.bicep (see README)
  - pip install -r requirements.txt
  - az login when running locally

Reference:
  https://learn.microsoft.com/en-us/azure/ai-foundry/model-gateway
"""

import json
import sys
from pathlib import Path

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import PromptAgentDefinition
from azure.identity import DefaultAzureCredential

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CONFIG_PATH = Path(__file__).parent / "config.json"

AGENT_INSTRUCTIONS = """
You are a helpful assistant.
Answer the user's questions clearly and concisely.
If you don't know the answer, say so.
""".strip()


def load_config(path: Path) -> dict:
    """Load and validate configuration from config.json."""
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)

    required_keys = [
        "project_endpoint",
        "gateway_connection_name",
        "model_deployment_name",
        "agent_name",
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
# Step 1: Create the agent
# ---------------------------------------------------------------------------

def create_agent(
    project_client: AIProjectClient,
    agent_name: str,
    gateway_connection_name: str,
    model_deployment_name: str,
) -> object:
    """
    Create (or update) a Foundry Agent backed by a ModelGateway connection.

    The model path uses the format  <connection>/<deployment>  which tells Foundry
    to route inference requests through the named ModelGateway connection rather
    than a locally-deployed model. The connection's OAuth2 credentials handle
    authentication to the target resource transparently.
    """
    gateway_backed_model = f"{gateway_connection_name}/{model_deployment_name}"

    agent = project_client.agents.create_version(
        agent_name=agent_name,
        definition=PromptAgentDefinition(
            model=gateway_backed_model,
            instructions=AGENT_INSTRUCTIONS,
        ),
    )

    print(f"[OK] Agent '{agent.name}' version '{agent.version}' created.")
    print(f"     Gateway-backed model: {gateway_backed_model}")
    return agent


# ---------------------------------------------------------------------------
# Step 2: Run a query
# ---------------------------------------------------------------------------

def run_query(project_client: AIProjectClient, agent, user_query: str) -> None:
    """
    Send a user query to the gateway-backed agent and stream the response.
    Foundry routes the inference call through the ModelGateway connection to
    the target resource using the OAuth2 credentials stored in the connection.
    """
    openai_client = project_client.get_openai_client()

    print(f"\n[USER] {user_query}\n")
    print("[AGENT] ", end="", flush=True)

    stream = openai_client.responses.create(
        stream=True,
        input=user_query,
        extra_body={"agent_reference": {"name": agent.name, "type": "agent_reference"}},
    )

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
    gateway_connection_name = cfg["gateway_connection_name"]
    model_deployment_name = cfg["model_deployment_name"]
    agent_name = cfg["agent_name"]
    user_query = cfg["user_query"]

    credential = DefaultAzureCredential()

    project_client = AIProjectClient(
        endpoint=project_endpoint,
        credential=credential,
    )

    # -- Step 1: Create agent --
    print("\n=== Step 1: Creating agent ===")
    agent = create_agent(
        project_client=project_client,
        agent_name=agent_name,
        gateway_connection_name=gateway_connection_name,
        model_deployment_name=model_deployment_name,
    )

    # -- Step 2: Run query --
    print("\n=== Step 2: Running query ===")
    run_query(project_client=project_client, agent=agent, user_query=user_query)

    print("\n=== Done ===")
    print(f"Agent '{agent_name}' remains in your Foundry project for subsequent runs.")


if __name__ == "__main__":
    main()
