# Agent-Marketplace

Production-shaped MVP for an **Outcome Execution Layer** focused on **regulatory compliance workflows for AI systems**.

This repository is designed to evolve into an **agent marketplace + execution platform**:
- Agents are **pluggable** and have a clear contract (schemas, cost, reliability)
- A decoupled **orchestrator** plans + executes steps, records an audit trail, and aggregates outputs
- A dedicated **validator layer** assigns confidence + explainability checks

## Local / Codespaces development

Ports (kept consistent with your devcontainer):
- Backend: `8040`
- Frontend: `5273`

### Backend (FastAPI)

```bash
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 0.0.0.0 --port 8040 --reload --app-dir backend --reload-dir backend
```

### Seed regulations (dev/demo)

If your environment has no ingestion pipeline populating `regulation_units`, you can seed a small GDPR corpus:

```bash
curl -X POST http://127.0.0.1:8040/regulations/seed
curl http://127.0.0.1:8040/regulations/stats
```

### Semantic embeddings (Hugging Face)

Copy `.env.example` to `.env` at the **repository root** (or `backend/.env`), set `HF_TOKEN`, and restart the API. The server does **not** read `.env.example` at runtime.

After the token is active, refresh stored vectors:

```bash
curl -X POST "http://127.0.0.1:8040/regulations/ingest/reembed"
# Optional: limit to one framework
curl -X POST "http://127.0.0.1:8040/regulations/ingest/reembed?framework_code=GDPR"
```

### Frontend (Next.js)

```bash
cd frontend
npm install
npm run dev
```

## API

### `POST /execute`

Request:

```json
{
  "intent": "Check if my AI hiring tool is GDPR compliant",
  "context": {
    "company": "Acme Inc",
    "region": "EU",
    "data_types": ["PII", "biometric"],
    "data_retention": "12 months",
    "dpia_done": false
  }
}
```

Response (initial):

```json
{ "execution_id": "<uuid>", "status": "queued" }
```

Poll for result:
- `GET /executions/{execution_id}`

Execution introspection (progress + durable audit stream):
- `GET /executions/{execution_id}/steps`
- `GET /executions/{execution_id}/audit`

### `GET /agents`
- lists all available agents (built-ins + registered)

### `POST /agents/register`
- registers agent metadata (future marketplace hook)