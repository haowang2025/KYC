# ClearCheck — Merchant Risk Triage Agent

> The first risk agent in the agent economy.

**ClearCheck** answers one question: *Can we proceed with this merchant — or should we hold?*

It returns a **Green / Yellow / Red** decision with 3 reasons, 3 next actions, and evidence.

## Quick Start

```bash
# 1. Install
pip install -r requirements.txt

# 2. Configure
cp .env.example .env
# Edit .env with your TokenRouter API key

# 3. Run CLI
python server.py --name "Parsian Bank" --country "Iran"

# 4. Or start API server
python server.py --serve --port 8000
# Then: curl -X POST http://localhost:8000/triage \
#   -H "Content-Type: application/json" \
#   -d '{"entity_name": "Parsian Bank", "country": "Iran"}'
```

## Architecture

```
User Query → KG Search (ArangoDB) → 3-Layer Risk Rules → LLM Reasoning → Report
                                     A. Entity Risk
                                     B. Jurisdiction Risk
                                     C. Data Completeness
```

## Files

| File | Purpose |
|------|---------|
| `server.py` | FastAPI server + CLI entry point |
| `triage_engine.py` | 3-layer risk rules + TokenRouter LLM reasoning |
| `kg_client.py` | ArangoDB KG client + fallback data |
| `expert_loop.py` | AgentHansa Expert long-poll worker |
| `skills/` | Skill-as-prompt definitions |

## Demo Cases

```bash
# 🔴 RED — Sanctioned entity
python server.py --name "Parsian Bank" --country "Iran"

# 🟢 GREEN — Clean merchant
python server.py --name "Stripe Inc" --country "US"

# 🟡 YELLOW — Ambiguous
python server.py --name "Golden Star Trading" --country "UAE" --amount 200000
```

## AgentHansa Deployment

```bash
# Start the expert loop to receive tasks from the Task Mesh
python expert_loop.py
```

## Built With

- **TokenRouter** — LLM API (Claude via TokenRouter)
- **ArangoDB** — Entity Knowledge Graph
- **FastAPI** — API server
- **AgentHansa** — Agent marketplace deployment
