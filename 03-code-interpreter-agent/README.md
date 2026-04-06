# 03 — Code Interpreter Agent

This sample demonstrates an Azure AI Foundry agent that combines two tools in a single run:

- **CodeInterpreterTool** — executes Python code to perform numerical analysis on a CSV dataset
- **FileSearchTool** — performs semantic search over text file contents to retrieve dataset descriptions

The agent first calls `file_search` to understand the dataset schema, then calls `code_interpreter` to compute statistics and produce results.

## How it works

```
[config.json]
    │
    └── agent_code_interpreter.py
          ├─ Uploads diabetes.csv → Foundry file store (CodeInterpreterTool resource)
          ├─ Uploads diabetes_description.txt → vector store (FileSearchTool resource)
          ├─ Creates Foundry Agent with both tools
          ├─ Sends user_query with tool_choice=file_search (first call guaranteed)
          ├─ Model calls file_search → retrieves column descriptions
          ├─ Model calls code_interpreter → computes statistics on the CSV
          └─ Prints grounded answer with computed values
```

> **Note on forcing two tools in one run**: The Agents API `tool_choice` only governs the *first* tool call. After the first tool returns, the model is in auto mode. This sample uses `tool_choice=file_search` to guarantee the first call, then relies on system instructions to drive the model to call `code_interpreter` next before answering.

## Prerequisites

| Requirement | Notes |
|---|---|
| Python 3.10+ | |
| Azure AI Foundry project | With a GPT-4.1 (or compatible) deployment — `FileSearchTool` and `CodeInterpreterTool` require a capable model |
| Azure CLI | `az login` for local development |

No Azure AI Search service is needed — this sample uses only Foundry's built-in file store and vector store.

## Setup

### 1. Create a virtual environment and install dependencies

```bash
python -m venv .codeinterpretervenv

# Windows
.codeinterpretervenv\Scripts\activate

# macOS / Linux
source .codeinterpretervenv/bin/activate

pip install -r requirements.txt
```

### 2. Fill in `config.json`

Copy `config.json.example` to `config.json` and fill in your values:

| Key | Where to find it / Description |
|---|---|
| `project_endpoint` | Foundry portal → your project → **Overview** → Project details |
| `agent_name` | A name of your choice for the agent |
| `agent_model` | Your LLM deployment name exactly as it appears in the Foundry portal under **Models + endpoints** |
| `user_query` | The question to send to the agent — default works well as-is |
| `csv_file` | Path to the CSV file relative to this folder — defaults to `data/diabetes.csv` |

### 3. Authenticate

```bash
az login
```

## Run

```bash
python agent_code_interpreter.py
```

The script uploads the data files, creates the agent, runs the query, prints the response, and then cleans up the uploaded files (but does **not** delete the agent so you can inspect it in the Foundry portal).

## Sample data

| File | Description |
|---|---|
| `data/diabetes.csv` | Pima Indians Diabetes dataset — 768 patient records with 8 clinical features and a binary outcome |
| `data/diabetes_description.txt` | Plain-text description of the dataset columns, used by `FileSearchTool` |

## Troubleshooting

| Error | Likely cause |
|---|---|
| `model not found` | `agent_model` doesn't match an existing deployment — check the Foundry portal under **Models + endpoints** |
| File upload fails | Project endpoint is wrong or the account lacks access to the Foundry project |
| Agent produces no code output | `code_interpreter` was not called — check that system instructions are intact in `agent_code_interpreter.py` |

## References

- [Code Interpreter tool — Foundry Agent Service](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/code-interpreter)
- [File Search tool — Foundry Agent Service](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/file-search)
- [azure-ai-agents SDK reference](https://learn.microsoft.com/en-us/python/api/overview/azure/ai-agents-readme)
