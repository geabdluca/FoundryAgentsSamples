"""
setup_search.py — Index Bootstrap Script
=========================================
Run this ONCE to create an Azure AI Search index and upload sample documents.
This is all that is needed for the AzureAISearchTool agent (01-search-tool-agent).

If you already have an existing index, skip this script and set index_name in
config.json to match your existing index.

If you also need the Foundry IQ (knowledge base) setup, see:
  02-mcp-tools/foundry-iq/setup_knowledge_base.py

Authentication: DefaultAzureCredential (az login for local dev, Managed Identity in prod)
Configuration:  config.json in the same directory

Prerequisites:
  - Azure AI Search service on Basic tier or higher (free tier lacks semantic ranker)
  - Your user identity needs "Search Service Contributor" and
    "Search Index Data Contributor" roles on the search service
  - pip install -r requirements.txt
  - az login (local development)

Reference:
  https://learn.microsoft.com/en-us/azure/search/search-get-started-portal-import-vectors
"""

import json
import sys
from pathlib import Path

from azure.identity import DefaultAzureCredential
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    SearchField,
    SearchFieldDataType,
    SearchIndex,
    SemanticConfiguration,
    SemanticField,
    SemanticPrioritizedFields,
    SemanticSearch,
    SimpleField,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CONFIG_PATH = Path(__file__).parent / "config.json"

# Sample documents uploaded to the index on first run.
# Replace or extend these with your own content.
SAMPLE_DOCUMENTS = [
    {
        "id": "1",
        "title": "Azure AI Foundry Overview",
        "content": (
            "Azure AI Foundry is a unified platform for building, evaluating, and deploying AI "
            "models and applications. It brings together Azure OpenAI Service, Azure AI Search, "
            "and other Azure AI services into a single development experience, enabling teams to "
            "build enterprise-grade AI solutions end to end."
        ),
        "source": "azure-ai-foundry-overview",
    },
    {
        "id": "2",
        "title": "Azure AI Search Tool for Foundry Agents",
        "content": (
            "The Azure AI Search tool connects a Foundry agent directly to a search index for "
            "grounded retrieval. The agent queries the index using simple, semantic, or vector "
            "search and returns answers with inline citations. No knowledge base object is "
            "required — the tool targets the index directly via a CognitiveSearch project connection."
        ),
        "source": "azure-ai-search-tool",
    },
    {
        "id": "3",
        "title": "Azure AI Search Semantic Ranking",
        "content": (
            "Semantic ranker in Azure AI Search uses large language models to promote results that "
            "are semantically relevant even when keyword matches are weak. It improves answer quality "
            "for natural language queries. Semantic ranker is available on the Basic pricing tier "
            "and above."
        ),
        "source": "azure-search-semantic-ranking",
    },
    {
        "id": "4",
        "title": "DefaultAzureCredential and Managed Identity",
        "content": (
            "DefaultAzureCredential from the Azure Identity SDK tries a chain of authentication "
            "methods in order: environment variables, workload identity, managed identity, Azure CLI, "
            "and others. For local development, run 'az login' and DefaultAzureCredential will use "
            "your Azure CLI session. In production, assign a managed identity to your resource and "
            "grant it the necessary RBAC roles."
        ),
        "source": "azure-identity-defaultcredential",
    },
    {
        "id": "5",
        "title": "Foundry Agent Service Overview",
        "content": (
            "Foundry Agent Service lets you build AI agents that can reason, plan, and use tools "
            "to complete tasks. Agents are backed by LLM deployments in your Foundry project and "
            "can be connected to Azure AI Search, code interpreters, MCP servers, and other tools. "
            "Agents maintain conversation state and support multi-turn interactions."
        ),
        "source": "foundry-agent-service-overview",
    },
    {
        "id": "6",
        "title": "RBAC and Private Networking for Azure AI Search",
        "content": (
            "When Azure AI Search is deployed in a private virtual network, all connections must "
            "use RBAC (role-based access control) with managed identity authentication. Key-based "
            "authentication is not supported with private networking. The Foundry project's managed "
            "identity must be assigned the Search Index Data Contributor and Search Service "
            "Contributor roles on the search service."
        ),
        "source": "azure-search-private-networking",
    },
]


def load_config(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)

    required_keys = [
        "search_service_endpoint",
        "index_name",
        "semantic_config_name",
    ]
    missing = [k for k in required_keys if not cfg.get(k) or str(cfg[k]).startswith("<")]
    if missing:
        print(
            "ERROR: The following config.json values are missing or still contain "
            f"placeholder text:\n  {', '.join(missing)}\n"
            "Please fill in config.json before running this script."
        )
        sys.exit(1)
    return cfg


# ---------------------------------------------------------------------------
# Step 1: Create the search index
# ---------------------------------------------------------------------------

def create_index(
    index_client: SearchIndexClient,
    index_name: str,
    semantic_config_name: str,
) -> None:
    """
    Create (or update) an Azure AI Search index with:
      - Fields: id (key), title, content, source
      - A semantic configuration for better natural language retrieval

    This schema supports AzureAISearchQueryType.SIMPLE (no vector fields required).
    To enable vector or hybrid search, add Collection(Edm.Single) vector fields and
    configure a vectorizer — then update query_type in agent_search_tool.py accordingly.
    """
    fields = [
        SimpleField(name="id", type=SearchFieldDataType.String, key=True, filterable=True),
        SearchField(name="title", type=SearchFieldDataType.String, searchable=True, retrievable=True),
        SearchField(name="content", type=SearchFieldDataType.String, searchable=True, retrievable=True),
        SimpleField(name="source", type=SearchFieldDataType.String, retrievable=True, filterable=True),
    ]

    semantic_config = SemanticConfiguration(
        name=semantic_config_name,
        prioritized_fields=SemanticPrioritizedFields(
            title_field=SemanticField(field_name="title"),
            content_fields=[SemanticField(field_name="content")],
        ),
    )

    index = SearchIndex(
        name=index_name,
        fields=fields,
        semantic_search=SemanticSearch(configurations=[semantic_config]),
    )

    index_client.create_or_update_index(index)
    print(f"[OK] Index '{index_name}' created/updated with semantic config '{semantic_config_name}'.")


# ---------------------------------------------------------------------------
# Step 2: Upload sample documents
# ---------------------------------------------------------------------------

def upload_documents(
    credential: DefaultAzureCredential,
    search_service_endpoint: str,
    index_name: str,
) -> None:
    """Upload SAMPLE_DOCUMENTS using merge-or-upload (idempotent — safe to re-run)."""
    search_client = SearchClient(
        endpoint=search_service_endpoint,
        index_name=index_name,
        credential=credential,
    )
    result = search_client.merge_or_upload_documents(documents=SAMPLE_DOCUMENTS)
    succeeded = sum(1 for r in result if r.succeeded)
    print(f"[OK] Uploaded {succeeded}/{len(SAMPLE_DOCUMENTS)} documents to '{index_name}'.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    cfg = load_config(CONFIG_PATH)

    search_service_endpoint = cfg["search_service_endpoint"].rstrip("/")
    index_name = cfg["index_name"]
    semantic_config_name = cfg["semantic_config_name"]

    credential = DefaultAzureCredential()
    index_client = SearchIndexClient(endpoint=search_service_endpoint, credential=credential)

    # -- Step 1: Create index --
    print("\n=== Step 1: Creating search index ===")
    create_index(
        index_client=index_client,
        index_name=index_name,
        semantic_config_name=semantic_config_name,
    )

    # -- Step 2: Upload sample documents --
    print("\n=== Step 2: Uploading sample documents ===")
    upload_documents(
        credential=credential,
        search_service_endpoint=search_service_endpoint,
        index_name=index_name,
    )

    print(
        "\n=== Setup complete ===\n"
        f"  Index: {index_name}\n"
        "\nNext step: run agent_search_tool.py to create the Foundry Agent and query the index."
    )


if __name__ == "__main__":
    main()
