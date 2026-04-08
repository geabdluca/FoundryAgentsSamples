# 03 — Code Interpreter Agent

This sample demonstrates an Azure AI Foundry agent that uses **CodeInterpreterTool** to execute Python code for numerical analysis on an uploaded CSV dataset.

## How it works

```
[config.json]
    │
    └── agent_code_interpreter.py
          ├─ Uploads diabetes.csv → Foundry file store
          ├─ Creates Foundry Agent with CodeInterpreterTool bound to the uploaded file
          ├─ Sends user_query via the Responses API
          ├─ Model calls code_interpreter → computes statistics on the CSV
          └─ Prints the analysis results
```

## Prerequisites

| Requirement | Notes |
|---|---|
| Python 3.10+ | |
| Azure AI Foundry project | With a **gpt-5-mini** deployment — file binding via `AutoCodeInterpreterToolParam` requires this model |
| Azure CLI | `az login` for local development |

No Azure AI Search service is needed — this sample uses only Foundry's built-in file store.

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
| `agent_model` | Your gpt-5-mini deployment name as it appears under **Models + endpoints** |
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

The script uploads the CSV, creates the agent, runs the query, and prints the response. The agent is **not** deleted after the run so you can inspect it in the Foundry portal.

## Sample data

| File | Description |
|---|---|
| `data/diabetes.csv` | Pima Indians Diabetes dataset — 768 patient records with 8 clinical features and a binary outcome |
| `data/diabetes_description.txt` | Plain-text description of the dataset columns |

## Troubleshooting

| Error | Likely cause |
|---|---|
| `model not found` | `agent_model` doesn't match an existing deployment — check the Foundry portal under **Models + endpoints** |
| File upload fails | Project endpoint is wrong or the account lacks access to the Foundry project |
| Agent produces no code output | `code_interpreter` was not called — check that system instructions are intact in `agent_code_interpreter.py` |


## References

- [Code Interpreter tool — Foundry Agent Service](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/code-interpreter)
- [azure-ai-projects SDK reference](https://learn.microsoft.com/en-us/python/api/overview/azure/ai-projects-readme)
