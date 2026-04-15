# ModelGateway Connection Troubleshooting Guide

## Contents
- [How and When to Use This Guide](#how-and-when-to-use-this-guide)
- [Issue Description / Symptoms](#issue-description--symptoms)
- [When Does This TSG Not Apply](#when-does-this-tsg-not-apply)
- [Diagnosis](#diagnosis)
- [Questions to Ask the Customer](#questions-to-ask-the-customer)
- [Cause](#cause)
- [Mitigation or Resolution](#mitigation-or-resolution)
- [Related Information](#related-information)
- [Tags or Prompts](#tags-or-prompts)

---

## How and When to Use This Guide

This guide covers troubleshooting for Azure AI Foundry agents that use a **ModelGateway connection** to route inference calls through an external gateway (such as APIM AI Gateway or a custom AI gateway). Use this guide when a customer has a ModelGateway connection deployed but their agent is returning 400, 404, or authentication errors.

The most common root cause is an incorrectly configured `targetUrl` — specifically, a path mismatch between what the customer's gateway expects and what Foundry actually sends. Secondary causes include OAuth2 scope misconfiguration and missing RBAC role assignments.

**Who:** Internal CSS/CSE engineers supporting Azure AI Foundry agent customers.

**What:** Errors on agent inference calls routed through a ModelGateway connection.

**Where:** Issues can occur via Azure AI Foundry portal, SDK, or direct API calls when the agent uses a ModelGateway connection.

**When:** Issues typically appear after initial connection deployment or after the customer changes their gateway configuration.

---

## Issue Description / Symptoms

- Agent runs fail with HTTP 400, 404, or authentication errors
- The agent is created successfully but fails at inference time
- Customer can call their gateway directly (e.g. via curl or Invoke-RestMethod) with a bearer token and receive a successful response, but the agent call fails
- Errors may not include a clear message — the response body may simply indicate a bad request or not found from the backend gateway

---

## When Does This TSG Not Apply

- Customers not using a ModelGateway connection type (e.g. using AzureAISearch, MCP, or direct Azure OpenAI connections)
- Errors occurring during agent creation or connection deployment (Bicep/ARM failures) — those are infrastructure issues, not inference routing issues
- Customers using ApiKey auth where the key itself is invalid — verify the key is correct before proceeding

---

## Diagnosis

### Step 1 — Identify the time window and search backend logs by gateway name

Use the first part of the customer's `targetUrl` as the search term (e.g. if `targetUrl` is `https://my-gateway.example.com/path/...`, search for `my-gateway`).

Run this query in [Azure Data Explorer (ADX)](https://dataexplorer.azure.com/clusters/aoaiagents1.westus/databases/prod):

```kusto
let _startTime = datetime('YYYY-MM-DD HH:MM:SS');  // replace with approximate start of issue
let _endTime   = datetime('YYYY-MM-DD HH:MM:SS');  // replace with approximate end of issue
Log
| where TIMESTAMP between (_startTime .. _endTime)
| where * contains "<gateway-hostname>"             // e.g. "my-gateway" or "foundrymodelgateway"
| project TIMESTAMP, env_dt_traceId, agent_id, body, severityText, run_id, thread_id, request_id, env_dt_spanId, exception
```

Look for log entries showing `Proxying to <url>`. The proxied URL reveals exactly what path Foundry is sending to the gateway. Examples:

- **Correct:** `Proxying to https://my-gateway.example.com/path/to/deployment/chat/completions`
- **Incorrect:** `Proxying to https://my-gateway.example.com/chat/completions`

Note the `env_dt_traceId` value from any matching row.

### Step 2 — Get the full trace for that request

Paste the `env_dt_traceId` into the query below to see the complete call chain including the gateway response:

```kusto
Log
| where TIMESTAMP >= ago(8d)
| where env_dt_traceId == "<trace-id-from-step-1>"
| project TIMESTAMP, env_dt_traceId, agent_id, body, severityText, run_id, thread_id, request_id, env_dt_spanId, exception
```

The log entries will show the outbound call to the gateway and the response received. You should see the error status and any response body returned by the gateway.

### Step 3 — Compare the proxied path to the customer's working direct call

Ask the customer for a working direct call to their gateway (curl or PowerShell). Compare:

| | URL |
|---|---|
| Customer's working direct call | `https://my-gateway.example.com/v0/r0/openai/deployments/my-model/chat/completions` |
| What Foundry is sending (from logs) | `https://my-gateway.example.com/v0/r0/chat/completions` |
| Customer's `targetUrl` in the connection | `https://my-gateway.example.com/v0/r0` |

If the paths don't match, proceed to [Mitigation or Resolution](#mitigation-or-resolution).

---

## Questions to Ask the Customer

1. What is the full URL of a **successful direct call** to your gateway (curl or PowerShell)? Include the complete path and any query parameters such as `?api-version=`.
2. What is the exact `targetUrl` value set in your ModelGateway connection?
3. What auth type is the connection using — ApiKey or OAuth2?
4. If OAuth2: what value is set in `scopes`? (common mistake: literal `{CLIENT_ID}.default` instead of `https://cognitiveservices.azure.com/.default`)
5. Has the Service Principal been assigned a role on the backend inference resource?
6. Can you share the approximate UTC timestamp and subscription/project of a failed agent run?

---

## Cause

### Primary — `targetUrl` path mismatch

Azure AI Foundry constructs the final inference URL by appending `/chat/completions` (and optionally `?api-version=<value>`) directly to the `targetUrl` stored in the connection. If `targetUrl` does not include the full path prefix expected by the gateway, the resulting URL will be incorrect and the gateway will return a 404 or 400.

**Example:**

| Setting | Value |
|---|---|
| `targetUrl` (incorrect) | `https://my-gateway.example.com/v0/r0` |
| URL Foundry sends | `https://my-gateway.example.com/v0/r0/chat/completions` ❌ |
| `targetUrl` (correct) | `https://my-gateway.example.com/v0/r0/openai/deployments/my-model` |
| URL Foundry sends | `https://my-gateway.example.com/v0/r0/openai/deployments/my-model/chat/completions` ✅ |

The rule: **`targetUrl` must contain everything in the gateway URL except `/chat/completions`.**

### Secondary — OAuth2 `scopes` misconfiguration

A literal unresolved placeholder such as `{CLIENT_ID}.default` is sometimes left in the `scopes` field when customers customize Bicep templates. The correct scope for Azure AI services client credentials is `https://cognitiveservices.azure.com/.default`.

### Secondary — Missing RBAC role on the backend resource

The Service Principal used in the OAuth2 connection must have at minimum **Cognitive Services User** on the backend inference resource. Without this, the token will be acquired successfully but the backend will reject the request with a 401 or 403.

### Secondary — `inferenceAPIVersion` not set

If the customer's gateway backend requires an API version query parameter (e.g. `?api-version=2024-10-21`), this must be set in the connection metadata field `inferenceAPIVersion`. If left empty, Foundry will not append it and the gateway may return a 400.

---

## Mitigation or Resolution

### Fix 1 — Correct the `targetUrl`

Update the connection so `targetUrl` ends just before `/chat/completions`. Redeploy the connection via Bicep or ARM after making the change.

```bicep
// Incorrect
targetUrl: 'https://my-gateway.example.com/v0/r0'

// Correct — includes full deployment path, stops before /chat/completions
targetUrl: 'https://my-gateway.example.com/v0/r0/openai/deployments/my-model'
```

### Fix 2 — Correct the OAuth2 `scopes`

```bicep
// Incorrect
scopes: ['{CLIENT_ID}.default']

// Correct
scopes: ['https://cognitiveservices.azure.com/.default']
```

### Fix 3 — Assign RBAC role to the Service Principal

```bash
az role assignment create \
  --assignee <service-principal-client-id> \
  --role "Cognitive Services User" \
  --scope /subscriptions/<sub-id>/resourceGroups/<rg>/providers/Microsoft.CognitiveServices/accounts/<backend-resource>
```

### Fix 4 — Set `inferenceAPIVersion` in connection metadata

If the gateway requires an API version:

```bicep
metadata: {
  deploymentInPath: 'false'
  inferenceAPIVersion: '2024-10-21'  // match what the gateway expects
  // ...
}
```

After applying fixes, redeploy the connection and rerun the agent. Check the ADX logs again to confirm the proxied URL now matches the expected gateway path.

---

## Related Information

- [04-model-gtw sample — ModelGateway agent with OAuth2 (end-to-end reproduction)](https://github.com/geabdluca/FoundryAgentsSamples/tree/main/04-model-gtw): Use this sample to reproduce the connection setup in a controlled environment. It includes a working Bicep template, Python agent script, and parameter examples covering both APIM AI Gateway and custom gateway scenarios.
- [Azure AI Foundry ModelGateway connection documentation](https://learn.microsoft.com/azure/ai-foundry/)
- [APIM AI Gateway overview](https://learn.microsoft.com/azure/api-management/)

---

## Tags or Prompts

This TSG helps answer questions about: ModelGateway connection errors, Azure AI Foundry agent 400 error, agent inference 404, targetUrl misconfiguration, OAuth2 scopes placeholder, Cognitive Services User role assignment, inferenceAPIVersion, APIM AI Gateway agent connection, custom gateway agent connection, ModelGateway connection troubleshooting, agent proxying wrong URL, chat completions path mismatch.
