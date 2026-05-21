# 05 — OpenAPI Tool Agent (Azure API Management)

This sample shows how to connect an Azure AI Foundry agent to any HTTP API exposed through **Azure API Management** using the [`OpenApiTool`](https://learn.microsoft.com/en-us/azure/ai-services/agents/how-to/tools/openapi-spec). The APIM subscription key is stored as a **Foundry CustomKeys connection** and injected automatically at runtime — it never appears in agent code or logs.

The sample ships with a **Contoso IT Helpdesk** mock API. A `return-response` policy in APIM returns a canned JSON answer so no real backend is required. Swap the policy for a real backend when you have one.

## How it works

```
User query
    │
    ▼
Foundry Agent  ──(OpenApiTool)──►  APIM  ──►  (mock policy / real backend)
    │                              ▲
    │             Ocp-Apim-Subscription-Key
    │             injected from CustomKeys connection
    ▼
Streamed answer
```

1. The agent receives a natural-language question.
2. The `OpenApiTool` POSTs a structured request to the APIM endpoint (`POST /contoso/itdesk/query`).
3. APIM authenticates the call using the subscription key injected from the Foundry connection.
4. APIM returns a JSON `{"answer": "..."}` response (mock or real backend).
5. The agent streams the plain-text answer back to the caller.

## Comparison with other samples

| | This sample (`OpenApiTool`) | 01 (`AzureAISearchTool`) | 02 (`MCPTool` / Foundry IQ) |
|---|---|---|---|
| **What it calls** | Any HTTP API via OpenAPI spec | Azure AI Search index directly | Knowledge base via MCP endpoint |
| **Auth** | APIM subscription key (CustomKeys connection) | RBAC (ProjectManagedIdentity) | RBAC (ProjectManagedIdentity) |
| **Best for** | Calling backend services, line-of-business APIs, or multi-tier agentic architectures | Focused document search | Multi-document reasoning with semantic reranking |

## Scripts

| Script | When to run |
|---|---|
| `setup_apim_api.py` | **Run once** to create the Contoso IT Helpdesk API on APIM and register the subscription key as a Foundry project connection. |
| `agent_openapi_apim.py` | **Run to test** — creates the Foundry agent with the OpenApiTool and sends a query. |

## Prerequisites

| Requirement | Notes |
|---|---|
| Python 3.10+ | |
| Azure AI Foundry project | With an LLM deployment already deployed. Deploy a model in the Foundry portal: **Models + endpoints → Deploy model**. Note the exact deployment name for `agent_model` in `config.json`. |
| Azure API Management instance | Consumption, Developer, or Standard tier. The `costagaAPIM` instance in `testopenapitool` is pre-configured in `config.json`. |
| RBAC: **API Management Service Contributor** | On the APIM resource — for your **user identity** running `setup_apim_api.py`. Only needed when `create_apim_api: true`. |
| RBAC: **Contributor** (or `connections/write`) | On the Foundry project — for your **user identity** running `setup_apim_api.py`. Only needed when `create_foundry_connection: true`. |
| Azure CLI | `az login` for local development. |

> **No RBAC required on APIM for the agent**: The OpenApiTool authenticates with the APIM subscription key stored in the Foundry CustomKeys connection. The Foundry project's managed identity does not need any role on the APIM resource.

## Setup

### 1. Create a virtual environment and install dependencies

```bash
python -m venv .apimvenv

# Windows
.apimvenv\Scripts\activate

# macOS / Linux
source .apimvenv/bin/activate

pip install -r requirements.txt
```

> **Windows ARM64**: If `pip install` fails building native packages from source, upgrade pip first:
> ```bash
> python -m pip install --upgrade pip
> pip install -r requirements.txt
> ```

### 2. Fill in `config.json`

Copy `config.json.example` to `config.json` and fill in your values. A pre-filled `config.json` is already present for the `testopenapitool` resource group — the only field you must add is `agent_model`.

| Key | Where to find it |
|---|---|
| `project_endpoint` | Foundry portal → your project → **Overview** → Project endpoint |
| `project_resource_id` | Azure portal → your Foundry project → **Properties** → Resource ID. Required when `create_foundry_connection: true`. |
| `agent_model` | Your LLM deployment name **exactly as shown** in the Foundry portal under **Models + endpoints**. |
| `apim_service_name` | Azure resource name of your APIM instance (e.g. `costagaAPIM`). The gateway URL is derived as `{name.lower()}.azure-api.net`. |
| `apim_api_path` | URL suffix for the API within APIM (e.g. `contoso/itdesk`). The full endpoint becomes `https://{apim}.azure-api.net/{api_path}/query`. |
| `apim_connection_name` | Name to give (or look up) the CustomKeys connection in your Foundry project. |
| `create_apim_api` | `true` to have `setup_apim_api.py` create the mock API. `false` if the API already exists. |
| `create_foundry_connection` | `true` to have `setup_apim_api.py` create the Foundry connection. `false` if it already exists. |
| `azure_subscription_id` | Azure subscription ID — only needed when `create_apim_api: true`. |
| `apim_resource_group` | Resource group containing the APIM instance — only needed when `create_apim_api: true`. |

> **`project_resource_id` format for newer Foundry projects**: If your Foundry project is based on `Microsoft.CognitiveServices/accounts` (the newer format), the resource ID path ends in `.../accounts/{account}/projects/{project}`. This differs from the older `Microsoft.MachineLearningServices/workspaces` format used in other samples.

### 3. Authenticate

```bash
az login
```

### 4. Run setup (once)

```bash
python setup_apim_api.py
```

This will:
- Create the `contoso/itdesk/query` API on APIM with a mock `return-response` policy.
- Create a product and subscription, and retrieve the subscription key.
- Register a `CustomKeys` connection in your Foundry project that stores the key under `Ocp-Apim-Subscription-Key`.

Both steps are gated by `create_apim_api` and `create_foundry_connection` in `config.json` and are safe to re-run (idempotent).

> **If `create_apim_api: false` and `create_foundry_connection: true`**: The setup script will prompt you to enter the APIM subscription key interactively so it can create the Foundry connection.

### 5. Run the agent

```bash
python agent_openapi_apim.py
```

This will:
- Resolve the Foundry connection and build the OpenApiTool with connection-based auth.
- Create (or version) the agent with the tool attached.
- Send the `user_query` from `config.json` to the agent and stream the response.

## Replacing the mock with a real backend

The mock `return-response` policy always returns the same canned answer. To connect a real backend:

1. In the Azure portal, open your APIM instance → **APIs → Contoso IT Helpdesk Agent**.
2. Go to **Design → All operations → Backend**.
3. Replace the `return-response` policy with a real backend URL and any required transformation policies.

No changes to the agent code or OpenAPI spec are needed — the `OpenApiTool` calls the same APIM endpoint regardless of what is behind it.

## Files

```
05-openapi-tool/apim/
├── openapi_spec.json        OpenAPI 3.0 spec for the Contoso IT Helpdesk API
├── config.json.example      Template — copy to config.json and fill in values
├── config.json              Your real values (git-ignored)
├── setup_apim_api.py        Creates APIM API + Foundry connection (run once)
├── agent_openapi_apim.py    Creates the agent and runs a query
└── requirements.txt
```
