# Foundry IQ Agent (MCP Tool)

This sample shows how to connect an Azure AI Foundry agent to a **Foundry IQ knowledge base** (Azure AI Search) via the [Model Context Protocol (MCP)](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/foundry-iq-connect), enabling agentic retrieval: LLM-based query planning, parallel subquery execution, semantic reranking, and grounded answer synthesis with citations.

## What is Foundry IQ?

Foundry IQ is Azure AI Search's **agentic retrieval** capability exposed to Foundry Agent Service via MCP. The hierarchy is:

```
Azure AI Search Index  (your documents)
    └── Knowledge Source  (registers the index for retrieval — created on the search service)
        └── Knowledge Base  (orchestrates: query planning, parallel search, semantic reranking, answer synthesis)
            └── Foundry Project Connection  (RemoteTool — registers the KB MCP endpoint on your Foundry project)
                └── Foundry Agent  (uses the connection as an MCPTool)
```

When a user asks a question, the agent calls the MCP tool, which triggers the knowledge base to decompose the query, run multi-mode search, rerank results, and return a grounded answer with citations.

## This sample vs Azure AI Search Tool (01-search-tool-agent)

| | This sample — Foundry IQ (`MCPTool`) | Search Tool (`AzureAISearchTool`) |
|---|---|---|
| **Retrieval** | Agentic pipeline: query planning, parallel subqueries, reranking, answer synthesis | Direct index query |
| **Setup** | Index + knowledge source + knowledge base | Index only |
| **Connection type** | `RemoteTool` (MCP endpoint) | `CognitiveSearch` |
| **Best for** | Complex queries, multi-source retrieval, richer citations | Simpler grounding, single index |

## Scripts

| Script | When to run |
|---|---|
| `setup_knowledge_base.py` | **Run once** to create the search index (optional), knowledge source, and knowledge base. Safe to re-run (idempotent). |
| `agent_foundry_iq.py` | **Run to test** — creates the Foundry project connection (optional) and agent, sends a query. |

## Prerequisites

| Requirement | Notes |
|---|---|
| Python 3.10+ | |
| Azure AI Foundry project | With an LLM deployment |
| Azure AI Search service | Basic tier or higher (semantic ranker required) |
| RBAC: **Search Service Contributor** + **Search Index Data Contributor** | On the AI Search service — for your **user identity** (running `setup_knowledge_base.py`) |
| RBAC: **Search Index Data Reader** | On the AI Search service — assigned to the **Foundry project's managed identity** (for agent MCP calls) |
| RBAC: ARM write permissions | Only if `create_project_connection: true` — your user identity needs `Contributor` (or `connections/write`) on the Foundry project |
| Azure CLI | `az login` for local development |

> **Required RBAC — Foundry project managed identity**: The Foundry project's managed identity **must** have the **Search Index Data Reader** role on the AI Search service before running `agent_foundry_iq.py`. Without it, the agent's MCP call to the knowledge base returns `403 Forbidden`. Assign this role in the Azure portal: AI Search service → **Access control (IAM)** → **Add role assignment** → Select **Search Index Data Reader** → Assign to your Foundry project's managed identity.

> **Private VNet / endpoint**: The RemoteTool connection uses `ProjectManagedIdentity` (RBAC-based, no stored credentials), which is required when the search service has public network access disabled.

## Setup

### 1. Create a virtual environment and install dependencies

```bash
# Create and activate a virtual environment
python -m venv foundryiqvenv

# Windows
foundryiqvenv\Scripts\activate

# macOS / Linux
source foundryiqvenv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Fill in `config.json`

**Azure AI Foundry**

| Key | Where to find it |
|---|---|
| `project_endpoint` | Foundry portal → your project → **Overview** → Project details |
| `project_resource_id` | Azure portal → your Foundry project → **Properties** → Resource ID. This is the ARM resource path used when creating the project connection via the REST API. Only needed if `create_project_connection: true`. |

**Azure AI Search**

| Key | Where to find it |
|---|---|
| `search_service_endpoint` | Azure portal → your AI Search service → **Overview** → URL |

**Index setup (`setup_knowledge_base.py`)**

| Key | Description |
|---|---|
| `create_search_index` | `true` to create the index and upload sample documents. `false` to use an existing index — set `index_name` to match. |
| `index_name` | Name of the search index |
| `semantic_config_name` | Name of the semantic configuration in the index |
| `knowledge_source_name` | Name for the knowledge source object |

**Knowledge base**

| Key | Description |
|---|---|
| `knowledge_base_name` | Name for the knowledge base object |
| `aoai_endpoint` | *(Optional)* Azure OpenAI endpoint for LLM-based query planning *inside* the knowledge base. Enables richer multi-hop query decomposition. Leave empty to skip — the Foundry Agent's LLM still handles answer synthesis. |
| `aoai_deployment` | *(Optional)* LLM deployment name on the AOAI resource above |
| `aoai_model` | *(Optional)* LLM model name (e.g. `gpt-4.1-mini`) |

**Foundry Agent**

| Key | Description |
|---|---|
| `create_project_connection` | `false` (default) to use an existing RemoteTool connection. `true` to create/update it via ARM — requires `project_resource_id` and ARM write permissions. The connection target is the knowledge base MCP endpoint. If `true` and the connection already exists, the ARM PUT is a safe upsert. |
| `project_connection_name` | The name of the RemoteTool connection in your Foundry project. Must match an existing connection when `create_project_connection: false`. |
| `agent_name` | A name of your choice for the agent |
| `agent_model` | Your LLM deployment name in the Foundry project |

### 3. Authenticate

```bash
az login
```

## Run

### Option A — Create index + knowledge base from scratch

```bash
# Step 1: Create the index, knowledge source, and knowledge base (run once — safe to re-run)
python setup_knowledge_base.py

# Step 2: Create the Foundry Agent and send a query
python agent_foundry_iq.py
```

### Option B — You already have an Azure AI Search index

Set `create_search_index: false` and `index_name` to your existing index in `config.json`, then run:

```bash
# Creates only the knowledge source and knowledge base on top of your existing index
python setup_knowledge_base.py

python agent_foundry_iq.py
```

### Option C — You already have a knowledge base and project connection

Set both `create_search_index: false` and `create_project_connection: false` in `config.json`, then run only:

```bash
python agent_foundry_iq.py
```

## How it works

```
[config.json]
    │
    ├── setup_knowledge_base.py
    │     ├─ (optional) Creates search index with semantic config
    │     ├─ (optional) Uploads sample documents
    │     ├─ Creates knowledge source → registers index for retrieval
    │     └─ Creates knowledge base  → orchestrates retrieval pipeline (+ optional AOAI LLM)
    │
    └── agent_foundry_iq.py
          ├─ (optional) Creates RemoteTool project connection → MCP endpoint on the knowledge base
          ├─ Creates Foundry Agent with MCPTool (knowledge_base_retrieve)
          ├─ Sends user_query via Conversations + Responses API
          └─ Prints grounded answer with citations
```

## Troubleshooting

| Error | Likely cause |
|---|---|
| `403` from Azure AI Search (`setup_knowledge_base.py`) | User identity missing **Search Service Contributor** or **Search Index Data Contributor** roles |
| `403` from Azure AI Search (agent query) | Foundry project managed identity missing **Search Index Data Reader** role |
| `403` from ARM | Account lacks write permissions on the Foundry project |
| `404` on MCP endpoint | `search_service_endpoint` or `knowledge_base_name` is wrong, or `2025-11-01-preview` API version not available in your region |
| Semantic ranker error during index creation | Upgrade to Basic tier or higher |
| Agent doesn't use the knowledge base | Check `allowed_tools` includes `knowledge_base_retrieve` and review agent instructions |

## References

- [Connect a Foundry IQ knowledge base to Foundry Agent Service](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/foundry-iq-connect)
- [Create a knowledge base in Azure AI Search](https://learn.microsoft.com/en-us/azure/search/agentic-retrieval-how-to-create-knowledge-base)
- [Create a search index knowledge source](https://learn.microsoft.com/en-us/azure/search/agentic-knowledge-source-how-to-search-index)
- [azure-ai-projects SDK reference](https://learn.microsoft.com/en-us/python/api/overview/azure/ai-projects-readme)
