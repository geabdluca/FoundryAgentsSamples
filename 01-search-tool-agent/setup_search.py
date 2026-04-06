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

import argparse
import json
import logging
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
DATA_DIR = Path(__file__).parent / "data"


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
# Step 2: Upload sample documents
# ---------------------------------------------------------------------------

def load_documents_from_disk(data_dir: Path) -> list[dict]:
    """
    Load all .md and .txt files from data_dir as search documents.
    Each file becomes one document:
      - id:      filename without extension
      - title:   first heading (# ...) if present, otherwise the filename
      - content: full file text
      - source:  relative path from data_dir
    """
    documents = []
    paths = sorted(data_dir.glob("*.md")) + sorted(data_dir.glob("*.txt"))
    for i, path in enumerate(paths, start=1):
        text = path.read_text(encoding="utf-8")
        # Extract the first markdown heading as the title, fall back to filename.
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
    parser = argparse.ArgumentParser()
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable Azure SDK HTTP logging")
    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(format="%(levelname)s:%(name)s:%(message)s", level=logging.WARNING)
        logging.getLogger("azure").setLevel(logging.DEBUG)
    else:
        logging.basicConfig(level=logging.WARNING)

    main()
