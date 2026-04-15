# 04 — Model Gateway Agent

This sample shows how to create an Azure AI Foundry agent backed by a **ModelGateway connection**. The agent routes inference through the gateway to a remote AI resource using **OAuth2 client credentials (Entra ID)** — stored in the connection, never in the agent script or `config.json`.

Use this pattern when:
- The target Foundry resource has `disableLocalAuth: true` (API keys disabled by policy)
- Tenant policy restricts SP secret lifetime — create short-lived secrets and rotate them using the idempotent Bicep template

## Architecture

```
Your Foundry Project
    └── ModelGateway connection  ──OAuth2──►  APIM AI Gateway
         (SP client credentials)              └── Managed Identity ──►  Backend AI Resource(s)
                                                  (e.g. gpt-4.1)
```

Foundry acquires an Entra ID bearer token using the SP's client credentials and forwards requests to the **APIM AI Gateway** endpoint. APIM validates the token, then proxies the inference call to the backend AI resource using its own managed identity — the SP never touches the backend resource directly.

---

## Scripts

| Script | When to run |
|---|---|
| `connection-modelgateway.bicep` | **Run once** — deploys the ModelGateway connection to your Foundry project. Re-run to rotate the SP secret. |
| `test_model_gateway_connection.py` | **Optional** — validates the full OAuth2 flow (token acquisition, model listing, live inference) before creating an agent. |
| `agent_model_gateway.py` | **Run to test** — creates the Foundry agent backed by the gateway and sends a streaming query. |

---

## Prerequisites

| Requirement | Notes |
|---|---|
| Python 3.10+ | |
| Azure AI Foundry project | With Owner or Contributor on its resource group |
| APIM AI Gateway | An Azure API Management instance configured as an AI Gateway — this becomes the `targetUrl` for the ModelGateway connection. You can create a new one or use an existing instance. |
| Backend AI resource | The actual Foundry resource or Azure OpenAI resource behind APIM — APIM's managed identity will be granted **Cognitive Services User** on this resource |
| Entra ID permissions | Ability to create app registrations and service principals in your tenant |
| Azure CLI | `az login` for local development |

---

## Setup

### Step 1 — Set subscription context

```bash
az account set --subscription <your-subscription-id>
```

---

### Step 2 — Create the Service Principal

> **Why two steps?** Newer Azure CLI versions removed `--end-date` from `az ad sp create-for-rbac`, and most tenants enforce a maximum secret lifetime of ~1 month. The approach below works reliably: create the app+SP first, then add a short-lived credential separately.

#### 2a — Create the app registration and service principal

```powershell
# Creates the app registration and SP in one shot (no credential yet)
az ad sp create-for-rbac --name "SP-Foundry-Gateway" --skip-assignment `
  --query "{clientId:appId, tenantId:tenant}" -o json
```

Note the `clientId` and `tenantId` from the output.

> If you see _"Found an existing application instance. We will patch it."_ that is fine — it means the SP already exists and will be reused.

#### 2b — Add a short-lived secret within the tenant policy window

```powershell
# Get the app's object ID from the clientId returned above
$appId = "<clientId from 2a>"
$appObjectId = az ad app show --id $appId --query id -o tsv

# Add a secret expiring in 28 days (adjust if your tenant policy is stricter)
$expiry = (Get-Date).AddDays(28).ToString("yyyy-MM-ddTHH:mm:ssZ")
az ad app credential reset --id $appObjectId --end-date $expiry `
  --query "{clientId:appId, clientSecret:password, tenantId:tenant}" -o json
```

**Save the output** — `clientSecret` is shown only once. You will need `clientId`, `clientSecret`, and `tenantId` in the following steps.

---

### Step 3 — Set up the AI Gateway (APIM)

The ModelGateway connection calls the **APIM AI Gateway** endpoint — APIM proxies the request to your backend AI resource using its managed identity. You can create a new instance or use an existing one.

#### 3a — Create or identify your APIM AI Gateway

If you don't already have one, create an API Management service in the Azure portal:
**Create a resource → API Management** — choose the **AI Gateway** tier or configure an existing APIM instance as an AI Gateway. Note the **gateway URL** (e.g. `https://<name>.azure-api.net`) — this becomes the base for `targetUrl` in the parameters file.

> The APIM gateway URL follows the pattern `https://<apim-name>.azure-api.net`. Verify it in **Azure portal → your APIM instance → Overview → Gateway URL**.

**Required APIM API configuration checklist** — before deploying the connection, verify these settings on your APIM API (**APIs → your AI API**):

| Setting | Required value | Where to set it |
|---|---|---|
| **Web service URL** (backend) | `https://<backend-resource>.services.ai.azure.com/` — the backend AI resource APIM proxies to | **Settings tab → Web service URL** — set at the API level, not per-operation |
| **Subscription required** | **Unchecked** — unless you pass the subscription key via `customHeaders` in the Bicep parameters | **Settings tab → Subscription → Subscription required** |
| **Operation URL templates** | `/*` (wildcard) — ensures all subpaths (`/models/chat/completions`, etc.) are forwarded to the backend | **Design tab → each operation → Frontend URL template** |

> **Tip — validate APIM directly before deploying the connection.** Use the APIM Test tab or a quick PowerShell call to confirm APIM can route to the backend before involving the Foundry connection:
> ```powershell
> $token = az account get-access-token --resource https://cognitiveservices.azure.com --query accessToken -o tsv
> Invoke-RestMethod -Method POST `
>   -Uri "https://<apim-name>.azure-api.net/<api-suffix>/models/chat/completions" `
>   -Headers @{ "Authorization" = "Bearer $token"; "Content-Type" = "application/json" } `
>   -Body '{"model":"<deployment-name>","messages":[{"role":"user","content":"say hello"}]}'
> ```
> A successful response here means APIM routing is correct. If this works but the agent still gets a 404, the issue is in the `targetUrl` path (see step 5).

#### 3b — Grant APIM's managed identity access to the backend AI resource

APIM uses its system-assigned managed identity to call the backend AI resource on behalf of the incoming request. Assign **Cognitive Services User** on the backend resource to the APIM managed identity:

```bash
# Get the APIM managed identity's principal ID
APIM_PRINCIPAL_ID=$(az apim show \
  --resource-group <apim-rg> \
  --name <apim-name> \
  --query "identity.principalId" -o tsv)

az role assignment create \
  --assignee $APIM_PRINCIPAL_ID \
  --role "Cognitive Services User" \
  --scope "/subscriptions/<sub-id>/resourceGroups/<backend-rg>/providers/Microsoft.CognitiveServices/accounts/<backend-resource-name>"
```

**PowerShell:**

```powershell
$apimPrincipalId = az apim show `
  --resource-group <apim-rg> --name <apim-name> `
  --query "identity.principalId" -o tsv

az role assignment create `
  --assignee $apimPrincipalId `
  --role "Cognitive Services User" `
  --scope "/subscriptions/<sub-id>/resourceGroups/<backend-rg>/providers/Microsoft.CognitiveServices/accounts/<backend-resource-name>"
```

#### 3c — Configure APIM to accept OAuth2 tokens from the SP

APIM validates the incoming Bearer token using a **JWT validation policy** on the API. Configure the policy to accept tokens issued by Entra ID for your tenant with audience `https://cognitiveservices.azure.com/`:

```xml
<!-- Inbound policy on your APIM AI Gateway API -->
<validate-jwt header-name="Authorization" failed-validation-httpcode="401">
  <openid-config url="https://login.microsoftonline.com/<tenantId>/v2.0/.well-known/openid-configuration" />
  <audiences>
    <audience>https://cognitiveservices.azure.com/</audience>
  </audiences>
</validate-jwt>
```

Add this policy in **Azure portal → your APIM instance → APIs → your AI API → Inbound processing**. The SP's tokens (acquired with scope `https://cognitiveservices.azure.com/.default`) will pass this validation — no explicit RBAC role assignment on the APIM service is required for the SP.

---

### Step 4 — List models available through the APIM AI Gateway

You need the exact model/deployment name(s) to populate `staticModels` in the parameters file. These are the deployment names on the **backend AI resource** that APIM exposes.

```bash
az cognitiveservices account deployment list \
  --resource-group <backend-rg> \
  --name <backend-foundry-account> \
  --query "[].{name:name, model:properties.model.name, version:properties.model.version, format:properties.model.format}" \
  -o table
```

> Alternatively, if your APIM API exposes a `/models` route, you can call it directly after deploying the connection to verify end-to-end routing.

---

### Step 5 — Create the Bicep parameters file

Copy `samples/parameters-oauth2.json.example` to `samples/parameters-<your-env>.json` and fill in your values:

| Parameter | Description |
|---|---|
| `projectResourceId` | Full ARM resource ID of your **source** Foundry project |
| `targetUrl` | **APIM AI Gateway endpoint including the `/models` path** — `https://<apim-name>.azure-api.net/<api-suffix>/models`. Foundry appends `/chat/completions` to this value at runtime, so the full request to APIM becomes `<targetUrl>/chat/completions`. The APIM API suffix and `/models` must both be in this value — e.g. `https://foundrymodelgateway.azure-api.net/MyAPI/models`. |
| `gatewayName` | Short label for the gateway (used to generate the connection name when `connectionName` is omitted) |
| `connectionName` | Name of the connection in your Foundry project (e.g. `mg-mygateway`). Note this value — it goes in `config.json`. |
| `clientId` | `clientId` from step 2 |
| `tokenUrl` | `https://login.microsoftonline.com/<tenantId>/oauth2/v2.0/token` |
| `staticModels` | Deployments to expose through the gateway (from step 4) |

> Files matching `samples/parameters-*.json` are git-ignored. Never commit files that contain real subscription IDs, resource IDs, or `clientId` values.

---

### Step 6 — Deploy the Bicep template

Pass `clientSecret` as a CLI parameter so it is **never written to disk or to the parameters file**.

**Bash:**

```bash
az deployment group create \
  --resource-group <source-rg> \
  --template-file connection-modelgateway.bicep \
  --parameters @samples/parameters-<your-env>.json \
  --parameters clientSecret="<clientSecret from step 2>"
```

**PowerShell:**

```powershell
az deployment group create `
  --resource-group <source-rg> `
  --template-file connection-modelgateway.bicep `
  --parameters "@samples/parameters-<your-env>.json" `
  --parameters clientSecret="<clientSecret from step 2>"
```

A successful deployment outputs `"provisioningState": "Succeeded"` and the `connectionName`. Use that name in `config.json`.

---

### Step 7 — (Optional) Validate the connection

Before creating an agent, validate the full OAuth2 flow — token acquisition, model listing, and a live inference call:

```powershell
python test_model_gateway_connection.py `
  --params samples/parameters-<your-env>.json `
  --client-secret "<clientSecret>" `
  --deployment-name "<deployment-name>"
```

---

### Step 8 — Create a virtual environment and install dependencies

```bash
python -m venv .mgvenv

# Windows
.mgvenv\Scripts\activate

# macOS / Linux
source .mgvenv/bin/activate

pip install -r requirements.txt
```

> **Windows ARM64**: If `pip install` fails building native packages from source, upgrade pip first then rely on the `--prefer-binary` flag already in `requirements.txt`:
> ```bash
> python -m pip install --upgrade pip
> pip install -r requirements.txt
> ```

---

### Step 9 — Fill in `config.json`

Copy `config.json.example` to `config.json` and fill in your values:

| Key | Where to find it |
|---|---|
| `project_endpoint` | Foundry portal → your project → **Overview** → Project details |
| `gateway_connection_name` | The `connectionName` from step 6 (e.g. `mg-mygateway`) |
| `model_deployment_name` | The deployment name in the gateway's `staticModels` list (from step 4 — matches the backend deployment name exposed through APIM) |
| `agent_name` | A name for the agent in your Foundry project |
| `user_query` | The question to send to the agent |

---

### Step 10 — Authenticate

```bash
az login
```

---

## Run

```bash
python agent_model_gateway.py
```

**Expected output:**

```
=== Step 1: Creating agent ===
[OK] Agent 'agent-model-gateway' version '1' created.
     Gateway-backed model: mg-mygateway/gpt-4.1

=== Step 2: Running query ===
[USER] What are the key capabilities of the model you are powered by?

[AGENT] I'm powered by GPT-4.1 ...

=== Done ===
Agent 'agent-model-gateway' remains in your Foundry project for subsequent runs.
```

---

## How it works

The agent's model path is `<gateway_connection_name>/<deployment_name>`. When the agent receives a prompt, Foundry:

1. Looks up the ModelGateway connection in the project
2. Uses the SP's OAuth2 client credentials (stored in the connection) to acquire an Entra ID bearer token
3. Forwards the request to the **APIM AI Gateway** endpoint with that token as the `Authorization: Bearer` header
4. APIM validates the token (JWT validation policy), then proxies the request to the backend AI resource using its **managed identity**

The SP's `clientSecret` is stored as a secure credential inside the connection resource — it never appears in `agent_model_gateway.py`, `config.json`, or any tracked file. The backend AI resource is never exposed directly; all traffic flows through APIM.

---

## Secret rotation

When the SP secret nears expiry, add a new one and re-deploy:

1. Add a new short-lived secret to the existing SP:

```powershell
$appObjectId = az ad app show --id "<clientId>" --query id -o tsv
$expiry = (Get-Date).AddDays(28).ToString("yyyy-MM-ddTHH:mm:ssZ")
az ad app credential reset --id $appObjectId --end-date $expiry `
  --query "{clientSecret:password}" -o json
```

2. Re-deploy the Bicep template with the new secret — idempotent, updates the connection in place:

```powershell
az deployment group create `
  --resource-group <source-rg> `
  --template-file connection-modelgateway.bicep `
  --parameters "@samples/parameters-<your-env>.json" `
  --parameters clientSecret="<new-secret>"
```
