"""
setup_knowledge_base.py — Foundry IQ Setup Script
===================================================
Run this ONCE to set up the Azure AI Search infrastructure required by the
Foundry IQ agent sample. It creates:

  1. (Optional) A search index with schema and semantic configuration
  2. (Optional) Sample documents uploaded to the index
  3. A knowledge source that registers the index for agentic retrieval
  4. A knowledge base that orchestrates retrieval (Foundry IQ)

If you already have an existing Azure AI Search index:
  - Set create_search_index to false in config.json
  - Set index_name and semantic_config_name to match your existing index
  - The script will create only the knowledge source and knowledge base

If you also need to create the index:
  - Alternatively, run 01-search-tool-agent/setup_search.py first to create the
    index, then run this script with create_search_index set to false

Authentication: DefaultAzureCredential (az login for local dev, Managed Identity in prod)
Configuration:  config.json in the same directory

Prerequisites:
  - Semantic ranker enabled on the Azure AI Search service (Basic tier or higher)
  - Your user identity needs "Search Service Contributor" and
    "Search Index Data Contributor" roles on the search service
  - pip install -r requirements.txt
  - az login (local development)

Reference:
  https://learn.microsoft.com/en-us/azure/search/agentic-retrieval-how-to-create-knowledge-base
  https://learn.microsoft.com/en-us/azure/search/agentic-knowledge-source-how-to-search-index
"""

import json
import sys
from pathlib import Path

import requests
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
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
DATA_DIR = Path(__file__).parent / "data"
SEARCH_API_VERSION = "2025-11-01-preview"


def load_config(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)

    required_keys = [
        "search_service_endpoint",
        "knowledge_source_name",
        "knowledge_base_name",
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


def get_search_token(credential: DefaultAzureCredential) -> str:
    token_provider = get_bearer_token_provider(credential, "https://search.azure.com/.default")
    return token_provider()


# ---------------------------------------------------------------------------
# Step 1 (optional): Create the search index
# ---------------------------------------------------------------------------

def create_index(
    index_client: SearchIndexClient,
    index_name: str,
    semantic_config_name: str,
) -> None:
    """
    Create (or update) an Azure AI Search index with the schema required
    by the knowledge source. Uses create_or_update_index (idempotent).
    """
    fields = [
        SimpleField(name="id", type=SearchFieldDataType.String, key=True, filterable=True),
        SearchField(name="title", type=SearchFieldDataType.String, searchable=True),
        SearchField(name="content", type=SearchFieldDataType.String, searchable=True),
        SimpleField(name="source", type=SearchFieldDataType.String, filterable=True),
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
# Step 2 (optional): Upload sample documents
# ---------------------------------------------------------------------------

def load_documents_from_disk(data_dir: Path) -> list[dict]:
    """
    Load all .md and .txt files from data_dir as search documents.
    Each file becomes one document:
      - id:      sequential number
      - title:   first heading (# ...) if present, otherwise the filename
      - content: full file text
      - source:  filename
    """
    documents = []
    paths = sorted(data_dir.glob("*.md")) + sorted(data_dir.glob("*.txt"))
    for i, path in enumerate(paths, start=1):
        text = path.read_text(encoding="utf-8")
        title = path.stem.replace("-", " ").replace("_", " ").title()
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("# "):
                title = stripped.lstrip("# ").strip()
                break
        documents.append({
            "id": str(i),
            "title": title,
            "content": text,
            "source": path.name,
        })
    if not documents:
        print(f"WARNING: No .md or .txt files found in '{data_dir}'. Nothing will be uploaded.")
    return documents


def upload_documents(
    credential: DefaultAzureCredential,
    search_service_endpoint: str,
    index_name: str,
) -> None:
    """Load documents from the data/ folder and upload using merge-or-upload (idempotent)."""
    documents = load_documents_from_disk(DATA_DIR)
    if not documents:
        return
    search_client = SearchClient(
        endpoint=search_service_endpoint,
        index_name=index_name,
        credential=credential,
    )
    result = search_client.merge_or_upload_documents(documents=documents)
    succeeded = sum(1 for r in result if r.succeeded)
    print(f"[OK] Uploaded {succeeded}/{len(documents)} documents to '{index_name}'.")


# ---------------------------------------------------------------------------
# Step 3: Create the knowledge source
# ---------------------------------------------------------------------------

def create_knowledge_source(
    search_service_endpoint: str,
    token: str,
    knowledge_source_name: str,
    index_name: str,
    semantic_config_name: str,
) -> None:
    """
    Create (or update) a search index knowledge source via the Azure AI Search
    preview REST API. The knowledge source registers the index as a retrievable
    data source for the knowledge base.
    """
    url = (
        f"{search_service_endpoint.rstrip('/')}/knowledgesources/"
        f"{knowledge_source_name}?api-version={SEARCH_API_VERSION}"
    )
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {
        "name": knowledge_source_name,
        "kind": "searchIndex",
        "searchIndexParameters": {
            "searchIndexName": index_name,
            "semanticConfigurationName": semantic_config_name,
            "sourceDataFields": [
                {"name": "id"},
                {"name": "title"},
                {"name": "source"},
            ],
        },
    }

    response = requests.put(url, headers=headers, json=payload, timeout=60)
    if not response.ok:
        print(f"  Response body: {response.text}")
    response.raise_for_status()
    print(f"[OK] Knowledge source '{knowledge_source_name}' created/updated.")


# ---------------------------------------------------------------------------
# Step 4: Create the knowledge base
# ---------------------------------------------------------------------------

def create_knowledge_base(
    search_service_endpoint: str,
    token: str,
    knowledge_base_name: str,
    knowledge_source_name: str,
    aoai_endpoint: str | None,
    aoai_deployment: str | None,
    aoai_model: str | None,
) -> None:
    """
    Create (or update) a Foundry IQ knowledge base via the Azure AI Search
    preview REST API.

    The knowledge base wires together:
      - Knowledge sources (what to search)
      - An optional Azure OpenAI LLM for LLM-based query planning inside the KB
      - Retrieval settings (reasoning effort, output mode)

    When the knowledge base is called via the Foundry Agent MCP tool, the
    Foundry Agent's own LLM handles final answer synthesis. Configuring the
    'models' field adds LLM-based query decomposition within the knowledge base
    itself, improving multi-hop and complex query handling.

    Leaving aoai_endpoint empty uses minimal retrieval reasoning (no LLM inside
    the KB), which is sufficient for most testing scenarios.
    """
    url = (
        f"{search_service_endpoint.rstrip('/')}/knowledgebases/"
        f"{knowledge_base_name}?api-version={SEARCH_API_VERSION}"
    )
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    has_model = bool(aoai_endpoint and aoai_deployment and aoai_model)

    payload: dict = {
        "name": knowledge_base_name,
        "description": "Foundry IQ knowledge base for agent sample",
        "knowledgeSources": [{"name": knowledge_source_name}],
        "retrievalReasoningEffort": {"kind": "minimal"},
    }

    if has_model:
        payload["retrievalReasoningEffort"] = {"kind": "low"}
        payload["outputMode"] = "answerSynthesis"
        payload["models"] = [
            {
                "kind": "azureOpenAI",
                "azureOpenAI": {
                    "resourceUri": aoai_endpoint.rstrip("/"),
                    "deploymentName": aoai_deployment,
                    "modelName": aoai_model,
                },
            }
        ]
        print(
            f"  Knowledge base will use AOAI model '{aoai_deployment}' "
            f"at '{aoai_endpoint}' for LLM-based query planning and answer synthesis."
        )
    else:
        print(
            "  No AOAI model configured — omitting outputMode and retrievalReasoningEffort "
            "(both require a model). Using API defaults for basic retrieval."
        )

    import json as _json
    print(f"  [VERBOSE] PUT {url}")
    print(f"  [VERBOSE] Payload: {_json.dumps(payload, indent=2)}")

    response = requests.put(url, headers=headers, json=payload, timeout=60)
    print(f"  [VERBOSE] Response status: {response.status_code}")
    if not response.ok:
        print(f"  Response body: {response.text}")
    response.raise_for_status()
    print(f"[OK] Knowledge base '{knowledge_base_name}' created/updated.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    cfg = load_config(CONFIG_PATH)

    search_service_endpoint = cfg["search_service_endpoint"].rstrip("/")
    index_name = cfg["index_name"]
    semantic_config_name = cfg["semantic_config_name"]
    knowledge_source_name = cfg["knowledge_source_name"]
    knowledge_base_name = cfg["knowledge_base_name"]

    # Optional: AOAI LLM for knowledge base query planning
    aoai_endpoint = cfg.get("aoai_endpoint", "")
    aoai_deployment = cfg.get("aoai_deployment", "")
    aoai_model = cfg.get("aoai_model", "")
    # Treat placeholder values as unconfigured
    if aoai_endpoint and aoai_endpoint.startswith("<"):
        aoai_endpoint = ""

    credential = DefaultAzureCredential()

    create_search_index = cfg.get("create_search_index", True)

    if create_search_index:
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
    else:
        print("\n=== Steps 1-2: Skipped (create_search_index=false) ===")
        print(f"  Using existing index: '{index_name}'.")

    token = get_search_token(credential)

    # -- Step 3: Create knowledge source --
    print("\n=== Step 3: Creating knowledge source ===")
    create_knowledge_source(
        search_service_endpoint=search_service_endpoint,
        token=token,
        knowledge_source_name=knowledge_source_name,
        index_name=index_name,
        semantic_config_name=semantic_config_name,
    )

    # -- Step 4: Create knowledge base --
    print("\n=== Step 4: Creating knowledge base ===")
    # Refresh token (long setup may cause expiry)
    token = get_search_token(credential)
    create_knowledge_base(
        search_service_endpoint=search_service_endpoint,
        token=token,
        knowledge_base_name=knowledge_base_name,
        knowledge_source_name=knowledge_source_name,
        aoai_endpoint=aoai_endpoint or None,
        aoai_deployment=aoai_deployment or None,
        aoai_model=aoai_model or None,
    )

    print(
        "\n=== Setup complete ===\n"
        f"  Index:            {index_name}\n"
        f"  Knowledge source: {knowledge_source_name}\n"
        f"  Knowledge base:   {knowledge_base_name}\n"
        "\nNext step: run agent_foundry_iq.py to create the Foundry Agent and query the knowledge base."
    )


if __name__ == "__main__":
    main()
