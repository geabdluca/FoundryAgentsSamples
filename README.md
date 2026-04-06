# Foundry Agents Samples

End-to-end Python samples for building and running AI Agents with [Azure AI Foundry Agent Service](https://learn.microsoft.com/en-us/azure/foundry/agents/overview) using the `azure-ai-projects` v2 SDK (`>=2.0.0`).

## Prerequisites

- Python 3.10+
- An [Azure AI Foundry project](https://learn.microsoft.com/en-us/azure/foundry/how-to/create-projects) with at least one LLM deployment
- The Azure CLI installed and signed in (`az login`) — used for `DefaultAzureCredential`

## Samples

| # | Folder | Description |
|---|--------|-------------|
| 01 | [01-foundry-iq-agent](./01-foundry-iq-agent/) | Agent that connects to a Foundry IQ knowledge base (Azure AI Search) via MCP and answers questions grounded in enterprise data |

## Structure

Each sample is self-contained under its own numbered folder:

```
<sample-folder>/
├── config.json          # All required configuration parameters (fill in before running)
├── requirements.txt     # Python dependencies for this sample
├── README.md            # Setup and run instructions specific to this sample
└── *.py                 # Sample script(s)
```

## Authentication

All samples use [`DefaultAzureCredential`](https://learn.microsoft.com/en-us/python/api/azure-identity/azure.identity.defaultazurecredential), which supports:

- **Local development**: `az login` (Azure CLI)
- **Production / hosted**: Managed Identity

No API keys are used or required.
