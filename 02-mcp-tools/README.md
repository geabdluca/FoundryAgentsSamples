# 02 — MCP Tools

This folder contains samples that use **Model Context Protocol (MCP)** to connect Foundry agents to external tools and data sources.

## Subfolders

| Folder | Tool | Description |
|---|---|---|
| `foundry-iq/` | Foundry IQ via MCP | Connects a Foundry agent to an Azure AI Search **knowledge base** using the MCP endpoint. Enables agentic retrieval: LLM-based query planning, parallel subqueries, semantic reranking, and answer synthesis. |

> Additional MCP tool samples can be added as subfolders here (e.g. `sharepoint/`, `custom-mcp-server/`).

## MCP vs Azure AI Search Tool

See the comparison table in `01-search-tool-agent/README.md` for guidance on which approach fits your scenario.
