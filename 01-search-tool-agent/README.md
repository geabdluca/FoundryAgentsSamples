# 01 — Azure AI Search Tool Agent

This sample shows how to connect an Azure AI Foundry agent directly to an **Azure AI Search index** using the [`AzureAISearchTool`](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/ai-search). The agent queries the index and returns grounded answers with inline citations — no knowledge base required.

## Search Tool vs Foundry IQ (MCP)

| | This sample (`AzureAISearchTool`) | Foundry IQ (`MCPTool`) — see `02-mcp-tools/foundry-iq` |
|---|---|---|
| **Retrieval** | Direct index query | Agentic pipeline: query planning, parallel subqueries, semantic reranking, answer synthesis |
| **Setup** | Index only | Index + knowledge source + knowledge base |
| **Connection type** | `CognitiveSearch` | `RemoteTool` (MCP endpoint) |
| **Best for** | Simpler grounding, single index | Complex queries, multi-source retrieval, richer citations |

## Scripts

| Script | When to run |
|---|---|
| `setup_search.py` | **Run once** to create the search index and upload sample documents. Skip if you already have an index. |
| `agent_search_tool.py` | **Run to test** — creates the Foundry agent with the search tool and sends a query. |

## Prerequisites

| Requirement | Notes |
|---|---|
| Python 3.10+ | |
| Azure AI Foundry project | With an LLM deployment **already deployed** — the script will not create one. Deploy a model first in the Foundry portal: your project → **Models + endpoints** → **Deploy model**. Note the exact deployment name — that is what goes in `agent_model` in `config.json`. |
| Azure AI Search service | Basic tier or higher |
| RBAC: **Search Service Contributor** + **Search Index Data Contributor** | On the AI Search service — for your **user identity** (running `setup_search.py`) |
| RBAC: **Search Index Data Contributor** + **Search Service Contributor** | On the AI Search service — assigned to the **Foundry project's managed identity** (for agent queries) |
| Azure CLI | `az login` for local development |

> **Required RBAC — Foundry project managed identity**: The Foundry project's managed identity **must** have **Search Index Data Contributor** and **Search Service Contributor** on the AI Search service. Without these, the agent's search tool calls return `401/403`. Assign them in the Azure portal: AI Search service → **Access control (IAM)** → **Add role assignment**.

> **Private VNet / endpoint**: The search connection **must** use RBAC (`ProjectManagedIdentity`). Key-based authentication is not supported when public network access is disabled on the search service.

## Setup

### 1. Create a virtual environment and install dependencies

```bash
# Create and activate a virtual environment
python -m venv .searchvenv

# Windows
.searchvenv\Scripts\activate

# macOS / Linux
source .searchvenv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Fill in `config.json`

| Key | Where to find it / Description |
|---|---|
| `project_endpoint` | Foundry portal → your project → **Overview** → Project details |
| `project_resource_id` | Azure portal → your Foundry project → **Properties** → Resource ID. Only needed if `create_search_connection` is `true`. |
| `search_service_endpoint` | Azure portal → your AI Search service → **Overview** → URL |
| `create_search_connection` | `false` (default) to use an existing Foundry project connection. `true` to create one via ARM — requires `project_resource_id` and write permissions on the Foundry project. |
| `search_connection_name` | The name of the Azure AI Search connection in your Foundry project. Create it once in the Foundry portal (**Project → Admin → Add connection → Azure AI Search**) or set `create_search_connection: true` to create it via the script. |
| `index_name` | Name of your search index. Run `setup_search.py` to create one, or use an existing index name. |
| `agent_model` | Your LLM deployment name **exactly as it appears** in the Foundry portal under **Models + endpoints**. The script does not create deployments — if the name doesn't match an existing deployment, agent creation will fail. |

> **Using an existing index**: Set `index_name` to your existing index name and skip `setup_search.py` entirely.

> **`create_search_connection` behaviour**:
> - **`false` (recommended):** No ARM call is made. The script resolves the connection ID from the name using the Foundry SDK. The connection must already exist in your project.
> - **`true`:** Issues an ARM `PUT` to create or update the connection with `ProjectManagedIdentity` auth. Safe to re-run (upsert). Requires `project_resource_id` and ARM write (`Contributor` or `connections/write`) on the Foundry project.

### 3. Authenticate

```bash
az login
```

## Run

### Option A — You need to create the index from scratch

```bash
# Step 1: Create the search index and upload sample documents (run once — safe to re-run)
python setup_search.py

# Step 2: Create the agent and send a query
python agent_search_tool.py
```

### Option B — You already have an Azure AI Search index

Set `index_name` in `config.json` to your existing index name, then run only:

```bash
python agent_search_tool.py
```

## How it works

```
[config.json]
    │
    ├── setup_search.py
    │     ├─ Creates search index (with semantic config)
    │     └─ Uploads sample documents
    │
    └── agent_search_tool.py
          ├─ Optionally creates CognitiveSearch project connection → ARM PUT
          ├─ Resolves connection resource ID from connection name (Foundry SDK)
          ├─ Creates Foundry Agent with AzureAISearchTool
          ├─ Streams user_query response with url_citation annotations
          └─ Prints grounded answer with inline citations
```

## Troubleshooting

| Error | Likely cause |
|---|---|
| `401/403` on search queries | Foundry project managed identity missing **Search Index Data Contributor** or **Search Service Contributor** role |
| `403` from ARM when creating connection | User identity missing write permissions on the Foundry project |
| `connection not found` | `search_connection_name` does not match an existing connection in your Foundry project |
| Index not found | `index_name` mismatch — check case-sensitive name in Azure AI Search |
| No citations in response | Update agent instructions to explicitly request citations; verify the index has a retrievable `source` field |
| DNS resolution error with private endpoint | Search connection is using key-based auth — switch to `ProjectManagedIdentity` (RBAC) |

## References

- [Connect an Azure AI Search index to Foundry agents](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/ai-search?pivots=python)
- [Add a new connection to your project](https://learn.microsoft.com/en-us/azure/foundry/how-to/connections-add)
- [azure-ai-projects SDK reference](https://learn.microsoft.com/en-us/python/api/overview/azure/ai-projects-readme)
