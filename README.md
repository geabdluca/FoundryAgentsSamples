# Foundry Agents Samples

End-to-end Python samples for building and running AI Agents with [Azure AI Foundry Agent Service](https://learn.microsoft.com/en-us/azure/foundry/agents/overview) using the `azure-ai-projects` v2 SDK (`>=2.0.0`).

## Prerequisites

- Python 3.10+
- An [Azure AI Foundry project](https://learn.microsoft.com/en-us/azure/foundry/how-to/create-projects) with at least one LLM deployment
- The Azure CLI installed and signed in (`az login`) — used for `DefaultAzureCredential`

## Samples

| # | Folder | Tool | Description |
|---|--------|------|-------------|
| 01 | [01-search-tool-agent](./01-search-tool-agent/) | `AzureAISearchTool` | Agent that queries an Azure AI Search index directly for grounded, citation-backed answers. Simplest search integration — no knowledge base required. |
| 02 | [02-mcp-tools/foundry-iq](./02-mcp-tools/foundry-iq/) | `MCPTool` (Foundry IQ) | Agent that connects to a Foundry IQ knowledge base via MCP for agentic retrieval: LLM-based query planning, parallel subqueries, semantic reranking, and answer synthesis. |
| 03 | [03-code-interpreter-agent](./03-code-interpreter-agent/) | Code Interpreter | Agent that uses the built-in code interpreter tool to analyze data, run Python, and produce results programmatically. |
| 04 | [04-model-gtw](./04-model-gtw/) | `ModelGateway` | Agent backed by a ModelGateway connection to route inference through an external AI gateway (e.g. APIM AI Gateway) using OAuth2 client credentials. |

> **Search Tool vs Foundry IQ**: Both use Azure AI Search but differ in retrieval depth. `AzureAISearchTool` queries the index directly — simpler, faster to set up. Foundry IQ adds an agentic pipeline on top (query decomposition, reranking, synthesis) — better for complex queries and multi-source scenarios. See [01-search-tool-agent/README.md](./01-search-tool-agent/README.md) for a full comparison table.

## Structure

Each sample is self-contained under its own numbered folder:

```
<sample-folder>/
├── config.json.example  # Template — copy to config.json and fill in your values
├── config.json          # Your local configuration (git-ignored, never committed)
├── requirements.txt     # Python dependencies for this sample
├── README.md            # Setup and run instructions specific to this sample
└── *.py                 # Sample script(s)
```

## Authentication

All samples use [`DefaultAzureCredential`](https://learn.microsoft.com/en-us/python/api/azure-identity/azure.identity.defaultazurecredential), which supports:

- **Local development**: `az login` (Azure CLI)
- **Production / hosted**: Managed Identity

No API keys are used or required.

## Validation environment

These samples have been validated end-to-end in a **private Azure AI Foundry** environment with:

- VNet-injected agents (no public network access on the Foundry resource)
- Private endpoints for Azure AI Search and storage
- All traffic routed over the private network

If you are running in a public (non-VNet) environment the samples work the same way — the VNet setup only affects network routing, not the SDK code or configuration structure.
