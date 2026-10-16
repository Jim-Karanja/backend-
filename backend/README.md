> **Note:** this is the original backend README. In this combined folder see the top-level `README.md` for how to run everything and for which features were rebuilt (the original `hub/` code was missing).

# Complaints Hub backend

Independent Python/FastAPI API for Safaricom PLC telecom and M-Pesa complaint demos.
It owns PostgreSQL storage, collection, replies, OpenAI classification and the MCP server.
The browser dashboard lives in its own frontend repository; no frontend files are required
or served by this backend. `GET /` returns API metadata.

## Setup and run

From this repository root in Git Bash on Windows:

```bash
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements.txt
# Only if .env does not already exist:
cp -n .env.example .env
./.venv/Scripts/python.exe -m uvicorn hub.main:app --reload --host 127.0.0.1 --port 8000
```

In PowerShell use `.\.venv\Scripts\python.exe` instead. On Linux/macOS/WSL, create
an environment using `python3 -m venv .venv` and use `.venv/bin/python` for the commands.
When running inside the original combined workspace, its existing interpreter is
`../.venv/Scripts/python.exe`; you do not need to recreate it.

- API health: http://127.0.0.1:8000/health
- API documentation: http://127.0.0.1:8000/docs
- MCP: http://127.0.0.1:8000/mcp/ (trailing slash required)

Both the app and `python -m hub.initdb` load `.env` from this backend repository root,
regardless of the shell's working directory. Existing environment variables take precedence.
Restart after changing `.env`. Keep API keys and database credentials in the backend only.

## Link the frontend

Set the frontend's browser origins in this backend's `.env`:

```dotenv
FRONTEND_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
```

For a separately hosted frontend, replace or extend the list with its exact origin,
for example `https://dashboard.example.com` (no path or trailing slash). Point the
frontend's public API URL at this backend's address. CORS permits GET and JSON POST
requests from the configured origins. See the [FastAPI CORS documentation](https://fastapi.tiangolo.com/tutorial/cors/).
The frontend talks to the API over HTTP; repository locations and names do not matter.

## Demo and database

Demo mode is enabled by default. With `DATABASE_URL` configured, startup creates missing
tables and seeds 32 fictional complaints plus two resumable collection runs once. Existing
posts, manual posts, triage and collection history are preserved across restarts. The
examples cover Safaricom voice, bundles, airtime, SIM and Home Fibre, and M-Pesa transfers,
merchant/agent payments, reversals and account access. These are fictional cases, not actual
customer reports. Generated legacy retail fixtures are upgraded automatically.

```dotenv
DATABASE_URL=postgresql://postgres:YOUR_PASSWORD@localhost:5432/complaints
HUB_DEMO_MODE=true
```

Create the PostgreSQL database first. To apply the schema/seed explicitly:

```bash
./.venv/Scripts/python.exe -m hub.initdb
```

Without `DATABASE_URL`, storage is temporary and resets on restart. `hub.demo:app` is an
optional isolated in-memory backend which ignores `.env`; the frontend still runs separately.
Simulated replies last only for the current server session. All newly seeded posts have
status `new`. `POST /api/demo/posts` saves a manually entered fictional post directly into
the inbox. Platform collection/replies remain simulated while demo mode is enabled.

Set `HUB_DEMO_MODE=false` to use real platform adapters. Live collection requires a stable
`AUTHOR_HASH_SALT`, `FB_PAGE_TOKEN` for Facebook reads/replies, `X_BEARER_TOKEN` for X reads
and `X_USER_TOKEN` for X replies. Disabling demo mode does not delete previously saved data.
This prototype has no login/authentication layer; the local commands bind to loopback.

## OpenAI classification

```dotenv
OPENAI_API_KEY=your_key_here
OPENAI_MODEL=gpt-4.1-mini
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_API_STYLE=responses
```

`OPENAI_BASE_URL` points the client at any OpenAI-compatible endpoint (default OpenAI).
`OPENAI_API_STYLE` selects the request shape: `responses` uses the OpenAI `/responses` API
with Structured Outputs; `chat` uses `/chat/completions` with `response_format` JSON schema,
for OpenAI-compatible gateways. For OpenCode Console use
`OPENAI_BASE_URL=https://opencode.ai/inference/openai/v1` — free models there are only
callable from inside OpenCode, so a paid Console key is required for external use.

Classification runs automatically (see Background classification); the dashboard displays
category, urgency and reason as results arrive and exposes no manual controls. Classification
uses the API account associated with your key. Keys are never returned to browser/MCP clients.
Configuration status reports presence, not verified access.

### Background classification

```dotenv
AUTO_CLASSIFY=true
AUTO_CLASSIFY_INTERVAL=300
AUTO_CLASSIFY_BATCH=10
```

When `AUTO_CLASSIFY` is enabled and `OPENAI_API_KEY` is set, the server classifies the oldest
`AUTO_CLASSIFY_BATCH` unclassified complaints every `AUTO_CLASSIFY_INTERVAL` seconds (minimum
30) in a background task started with the app. Failures are logged and the timer keeps
running; the inbox only changes when a batch succeeds. `/api/setup` reports the timer under
`ai.auto_classify`. The dashboard polls every 15 seconds while it is open and no dialog is
in use, so automatic classifications appear without a reload.

OpenAI receives text and temporary references, not author hashes or raw platform records.
Text itself may contain personal information. The request uses `store=false` and
[Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses).
Validated results persist category, urgency, short reason, model and classification time.
Invalid/incomplete responses save nothing; complaints changed mid-request are skipped.
Existing status, drafts and response timestamps are preserved. Results are suggestions
for review, not verified findings or automatic replies.

Urgency: **1 Low, 2 Normal, 3 Medium, 4 High, 5 Critical**. Categories cover telecom and
M-Pesa services. AI classification awaits a valid key.

## API and MCP

| Endpoint | Purpose |
| --- | --- |
| `GET /api/setup` | Storage, demo, AI presence and MCP metadata; no secrets |
| `GET /api/overview` | Counts and latest collection time |
| `GET /api/complaints` | Oldest-first inbox; platform, search, limit and offset |
| `GET /api/runs` | Newest-first collection history |
| `POST /api/demo/posts` | Demo-only insertion; `platform` and `text` |
| `POST /collect` | Validate/collect a source; supports dry-run and resume cursor |
| `POST /reply` | Simulate or publish a reply according to server mode |
| `POST /api/ai/classify` | `{"limit":10}` (1-25), or `platform` plus `external_id` |

The official [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk/tree/v1.x)
serves Streamable HTTP at `/mcp/`, using the same store and AI configuration. Local MCP
clients can use these tools: `list_complaints`, `get_complaint`, `complaint_overview`,
`classify_complaints`. Classification sends text to OpenAI and saves the result. No second
server is needed. Example client configuration (formats vary by client):

```json
{"mcpServers":{"complaints-hub":{"type":"http","url":"http://127.0.0.1:8000/mcp/"}}}
```

Cloud-hosted clients cannot reach your machine's localhost directly.

## Tests and layout

```bash
./.venv/Scripts/python.exe -m unittest discover -v
# Optional real PostgreSQL integration tests run in a throwaway schema:
TEST_DATABASE_URL=postgresql://... ./.venv/Scripts/python.exe -m unittest tests.test_postgres_store -v
```

`hub/` contains the application, `tests/` its unit/HTTP/MCP/database tests, and `schema.sql`
the database schema. `n8n/` contains importable collection/reply workflows; point their
hub URLs at this backend. No test in this repository requires frontend source files.
