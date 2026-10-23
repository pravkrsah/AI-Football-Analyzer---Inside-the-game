# Football AI — Inside the Game
## Claude Code Project Instructions

### Project in one line
Real-time Premier League match intelligence demo built for the Microsoft & Premier League Developer Hackathon, running entirely locally against Azure OpenAI.

---

## Tech Stack
- **Backend**: Python 3.13 stdlib only — `http.server.ThreadingHTTPServer`, `threading`, `queue`, `sqlite3`
- **Frontend**: Vanilla JS + HTML5 + CSS3 — open `http://localhost:8000`, no build step
- **AI**: Azure OpenAI via `openai` SDK — GPT-4o (chat) + text-embedding-ada-002 (embeddings)
- **Realtime**: Server-Sent Events (SSE) — one `queue.Queue` per connected browser tab
- **Dependencies**: only `openai` and `python-dotenv` (no FastAPI, Flask, numpy, etc.)

## Why no web framework?
FastAPI and Flask both pull in C-extension dependencies (`pydantic-core`, `markupsafe`) that are absent from the corporate Infosys Artifactory PyPI mirror. Pure stdlib avoids all installation friction.

---

## Project Structure
```
Football_AI_Hackathon/
├── .env                    ← credentials — never commit
├── run.py                  ← entry point
├── requirements.txt        ← openai + python-dotenv only
├── backend/
│   ├── config.py           ← .env → typed config; strips path from endpoint URL
│   ├── ai_client.py        ← get_client() for chat, get_embed_client() for embeddings
│   ├── main.py             ← HTTP router: do_GET / do_POST / _sse_stream
│   ├── match_simulator.py  ← threaded simulator; broadcast() sends to all SSE queues
│   ├── narrative_engine.py ← commentary, half-time, recap, social snippets
│   ├── tactical_analyser.py← tactical breakdown (JSON-structured AI output)
│   ├── embedding_search.py ← cosine similarity; loads from data/embeddings_cache.json
│   ├── translator.py       ← 9-language translation via GPT-4o
│   ├── goal_analysis.py    ← goal build-up sequence (pitch zones → arrows) for Goals tab
│   ├── goal_projection.py  ← xG projection, win %, shot map + AI "better angle" (Projection tab)
│   ├── pundit_chat.py      ← fan-chat answer with live context (after guardrails)
│   ├── guardrails.py       ← regex prompt-injection pre-filter — NO GPT call
│   ├── key_moments.py      ← key-moment insight generator
│   ├── live_feed.py        ← API-Football fixtures + replay/live threads (reuse broadcast())
│   ├── agents.py           ← multi-agent orchestrator: Data/Tactics/Explain/Narrative/Persona
│   ├── personalization.py  ← per-fan rendering of the intelligence packet (For You tab)
│   ├── mcp_tools.py        ← shared MCP tool registry (used by agents AND mcp_server)
│   ├── mcp_server.py       ← MCP JSON-RPC 2.0 server (HTTP POST /mcp + stdio)
│   └── database.py         ← SQLite schema (match_events, narratives, tactical_analyses)
├── frontend/
│   ├── index.html
│   ├── app.js              ← SSE EventSource client + REST calls + DOM updates
│   └── style.css
├── data/
│   ├── players.json        ← hard-coded Man City vs Arsenal squads (15 players each)
│   ├── historical_moments.json ← 20 iconic PL moments for semantic search
│   └── embeddings_cache.json   ← auto-generated; delete to force recompute
└── logs/
    └── match.db            ← SQLite (auto-created by init_db())
```

---

## Environment Variables (.env)

| Variable | Purpose |
|---|---|
| `AZURE_OPENAI_API_KEY` | Shared key for both chat and embedding clients |
| `AZURE_OPENAI_ENDPOINT` | Base URL — `https://your-resource.openai.azure.com` (no path) |
| `AZURE_OPENAI_MODEL` | Chat deployment name, e.g. `gpt-4o` |
| `AZURE_OPENAI_API_VERSION` | Chat API version, e.g. `2024-05-01-preview` |
| `AZURE_OPENAI_TEXT_EMBEDDING` | Embedding deployment name, e.g. `text-embedding-ada-002` |
| `AZURE_OPENAI_EMBEDDING_VERSION` | Embedding API version — must be `2023-05-15` for ada-002 |

**Important:** `config.py` strips any path or query string from the endpoint URL using `urlparse`, so it's safe to paste a full URL from Azure portal.

**Two separate `AzureOpenAI` clients** exist because `text-embedding-ada-002` requires API version `2023-05-15`, different from GPT-4o.

---

## Running the Project

```bash
# Start server (Python 3.13 venv required)
venv313\Scripts\python run.py

# Open app
start http://localhost:8000

# Restart cleanly (kills all Python processes on Windows)
taskkill /F /IM python.exe
venv313\Scripts\python run.py
```

On startup `run.py` does:
1. `config.validate()` — prints resolved endpoint/model/version; raises if keys missing
2. `init_db()` — creates SQLite tables if absent
3. `embedding.load_historical_moments()` — loads 20 moments; computes + caches embeddings on first run (calls Azure); subsequent runs load from `data/embeddings_cache.json`
4. `create_server(port=8000).serve_forever()`

---

## Key Architectural Patterns

### SSE broadcast
```python
# One Queue per connected client, held in simulator.clients list
clients: list[queue.Queue] = []
clients_lock = threading.Lock()

def broadcast(event: dict):
    with clients_lock:
        for q in clients:
            q.put_nowait(event)
```
The SSE handler (`_sse_stream` in `main.py`) creates a Queue, appends it to `clients`, then loops calling `q.get(timeout=20)` and writing SSE frames.

### Background AI commentary
```python
# In match_simulator.run_simulation() — never blocks the sim loop
if event["type"] in ("goal", "yellow_card", "save", ...):
    threading.Thread(target=_ai_commentary_task, args=(event,), daemon=True).start()
```
Commentary appears 1–3 seconds after the triggering event as a separate `ai_commentary` SSE frame.

### Unified AI helper
```python
# backend/ai_client.py
def chat(prompt, max_tokens=300, temperature=0.75, json_mode=False) -> str:
    # Uses max_completion_tokens (required by gpt-5.x / gpt-4o on newer API versions)
    # All narrative/tactical/translation modules call this — single place to swap models
```

---

### Multi-agent pipeline (For You tab)
```python
# backend/agents.py — specialized agents share a blackboard `bb`, hand off, recover
PIPELINE = [DataAgent(), TacticsAgent(), ExplainAgent(), NarrativeAgent(), PersonaAgent()]
def run_pipeline(profile):
    bb = {"profile": profile, "trace": []}
    for agent in PIPELINE:        # DataAgent may set bb["priority_moment"] → ExplainAgent focuses it
        agent.run(bb)             # each agent reaches live state ONLY via backend/mcp_tools
    return bb                     # intelligence packet + per-agent trace
```
`POST /api/agents/analyse {profile}` runs this and also ⇒ `agent_overlay` / `personalized` over SSE.
Agents never touch `match_state` directly — they call `mcp_tools.call_tool(...)`, the same
registry the MCP server exposes, so agents and external MCP clients see identical data.

### MCP server (expose the match as tools)
```python
# backend/mcp_tools.py  — single source of truth: TOOLS = {name: {description, inputSchema, handler}}
# backend/mcp_server.py — JSON-RPC 2.0: initialize / tools/list / tools/call
#   HTTP  : POST /mcp         (handled in main.py via mcp_server.handle_jsonrpc)
#   stdio : python -m backend.mcp_server   (for VS Code / Claude Desktop / Azure MCP)
```
To add a tool: add an entry to `TOOLS` in `mcp_tools.py` — it is instantly available to both
the agents and every MCP client. No other change needed.

### Personalization (stage e)
`personalization.personalize(packet, profile)` re-renders one neutral intelligence packet for a
profile `{mode: analyst|casual|commentary, favorite_club, focus_player, language}`. Called by
`PersonaAgent`. The For You dropdowns are filled from `GET /api/match/participants` (current match,
sim OR replay) every time the tab opens.

### Projection vs Goals (keep them visually distinct)
- **Goals tab** → `goal_analysis` → top-down **pitch pass-map** (`buildPitchSVG`).
- **Projection tab** → `goal_projection` → **shot-trajectory** view (`shotTrajectorySvg`): parabola
  arc + shooting-angle wedge + outcome, and a dashed green "better angle" for misses.

### Frontend cache
`main.py:serve_file` sends `Cache-Control: no-cache` so edits to `app.js` / `style.css` show on
reload. The `?v=NN` query on the `<script>` tag in `index.html` is also bumped on JS changes.

## Common Tasks

### Add a new match event type
1. Add to `EVENT_WEIGHTS` in `match_simulator.py` with a probability weight
2. Add a description template in `_generate_event()`
3. If it should trigger AI commentary, add to the type-check list in `run_simulation()`

### Add a new API endpoint
- GET: add an `elif path == "/api/..."` branch in `Handler.do_GET()`
- POST: add an `elif path == "/api/..."` branch in `Handler.do_POST()`
- No decorators, no routing framework — plain string matching

### Add a new language
Add to `SUPPORTED_LANGUAGES` dict in `translator.py` — `{"code": "Language Name"}`. The GPT-4o translation prompt handles it automatically.

### Force embedding recompute
Delete `data/embeddings_cache.json` and restart — it recomputes all 20 moments against Azure.

### Change the fixture
Edit `HOME_TEAM`, `AWAY_TEAM` and `MATCH_ID` at the top of `match_simulator.py`. Update `data/players.json` with the new squads.

---

## What is Hard-Coded

| Item | Where | To change |
|---|---|---|
| Fixture: Man City vs Arsenal | `match_simulator.py` top | Edit `HOME_TEAM`, `AWAY_TEAM` |
| Squad (15 players each) | `data/players.json` | Edit JSON |
| Historical moments (20) | `data/historical_moments.json` | Add/edit entries, delete cache |
| Match ID | `match_simulator.py` | Edit `MATCH_ID` |
| Server port | `run.py` | Change `port=8000` |

---

## Known Constraints

- **Single fixture per server session** — the simulator keeps state in a module-level dict; restarting the simulation resets it, but the server must be restarted to change the fixture
- **In-process SSE only** — broadcast uses an in-process list of Queues; multiple server workers would lose events (fix: Redis pub/sub)
- **SQLite** — fine for local dev; replace with Azure SQL or Cosmos DB for production
- **No auth** — API is open on `localhost`; add API key middleware before exposing publicly

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `DeploymentNotFound` on embeddings | Wrong deployment name or API version | Check `AZURE_OPENAI_TEXT_EMBEDDING` and `AZURE_OPENAI_EMBEDDING_VERSION` in `.env` |
| `DeploymentNotFound` on chat | Wrong `AZURE_OPENAI_MODEL` | Verify deployment name in Azure OpenAI Studio |
| `unsupported_parameter: max_tokens` | Model requires `max_completion_tokens` | Already fixed in `ai_client.py`; ensure you're running latest code |
| `Resource not found` 404 | Endpoint URL contains `/openai/responses` path | `config.py` strips it; check `AZURE_OPENAI_ENDPOINT` is base URL only |
| AI Commentary never appears | Match not started, or AI thread failing silently | Check terminal for `[ai_commentary_task]` errors; verify Azure connectivity |
| Embeddings cache stale | Recomputed with wrong model | Delete `data/embeddings_cache.json` and restart |
| `ModuleNotFoundError: backend` | Running Python from wrong directory | Always run from project root: `venv313\Scripts\python run.py` |
