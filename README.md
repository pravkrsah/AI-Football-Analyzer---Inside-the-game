# Football AI — Inside the Game
### Microsoft & Premier League Developer Hackathon

Real-time match intelligence platform delivering AI-generated commentary, tactical analysis, multilingual narratives, and semantic search over iconic Premier League moments — all powered by Azure OpenAI.

---

## Features

| Feature | Description |
|---|---|
| **Live Match Simulator** | Probabilistic minute-by-minute event engine (goals, cards, saves, VAR, corners, …) streamed to the browser via Server-Sent Events |
| **AI Commentary** | Automatic BBC-style commentary generated for every key event (goal, save, yellow/red card, penalty, VAR) using GPT-4o |
| **Tactical Analyser** | Real-time formation detection, pattern recognition, and key battle identification on demand |
| **Match Narratives** | Half-time analysis and full match reports in Guardian/Sky Sports journalist style |
| **Multilingual Delivery** | Any narrative translated instantly into 9 languages (Spanish, French, German, Arabic, Mandarin, Portuguese, Hindi, Japanese) |
| **Semantic Search** | Find historically similar Premier League moments from a curated dataset of 20 iconic events using Azure OpenAI embeddings |
| **Social Snippets** | Auto-generated tweets for goal events, ready to post |
| **Multi-Agent Pipeline** ("For You") | Five specialist agents — Data · Tactics · Explain · Narrative · Persona — share a blackboard, hand off, and recover from failures to produce one intelligence packet. Each agent is clickable to reveal its contribution |
| **Personalization** | The same intelligence re-rendered per fan: analyst vs casual vs commentator, favourite club, player-focus mode, and language |
| **MCP Server** | A Model Context Protocol (JSON-RPC 2.0) server exposes the live match as agent tools over HTTP (`POST /mcp`) **and** stdio (`python -m backend.mcp_server`) for VS Code / Claude Desktop / Azure MCP |
| **Goal Projection** | Expected-goals (xG) read, projected final score, win probability, and next-goal odds |
| **Shot Analysis** | Per-shot trajectory + shooting-angle diagram; for missed chances an AI shooting coach draws and explains a **better angle** |
| **Broadcast Overlay** | Machine-readable, timed overlay packet (lower-third + momentum bar) ready for a live feed |

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     Browser (Frontend)                   │
│  Vanilla JS · HTML5 · CSS3  —  no build step            │
│                                                          │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────┐  │
│  │  Match   │  │   AI     │  │ Tactical │  │ Search │  │
│  │  Feed    │  │Commentary│  │ Analyser │  │  Panel │  │
│  └────┬─────┘  └─────┬────┘  └────┬─────┘  └───┬────┘  │
│       │ SSE          │ REST        │ REST        │ REST  │
└───────┼──────────────┼─────────────┼─────────────┼───────┘
        │              │             │             │
┌───────▼──────────────▼─────────────▼─────────────▼───────┐
│              Python HTTP Server  (stdlib only)             │
│                    backend/main.py                         │
│                                                            │
│  ┌───────────────┐  ┌──────────────┐  ┌────────────────┐ │
│  │match_simulator│  │narrative_    │  │tactical_       │ │
│  │  (threading)  │  │engine.py     │  │analyser.py     │ │
│  │               │  │              │  │                │ │
│  │ SSE broadcast │  │ Commentary   │  │ Formation +    │ │
│  │ queue.Queue   │  │ Half-time    │  │ Pattern AI     │ │
│  │ per client    │  │ Recap        │  │                │ │
│  └───────┬───────┘  └──────┬───────┘  └───────┬────────┘ │
│          │                 │                   │          │
│  ┌───────▼─────────────────▼───────────────────▼────────┐ │
│  │                    ai_client.py                       │ │
│  │     chat()  ·  get_client()  ·  get_embed_client()   │ │
│  └───────────────────────┬───────────────────────────────┘ │
│                          │                                  │
│  ┌───────────────────────▼───────────────────────────────┐ │
│  │                   backend/config.py                   │ │
│  │  Reads .env · Parses endpoint URL · API version mgmt │ │
│  └───────────────────────────────────────────────────────┘ │
│                                                            │
│  ┌──────────────┐  ┌───────────────┐  ┌────────────────┐ │
│  │embedding_    │  │  translator   │  │  database.py   │ │
│  │search.py     │  │  .py          │  │  (SQLite)      │ │
│  │cosine sim    │  │  9 languages  │  │  events +      │ │
│  │cached .json  │  │               │  │  narratives    │ │
│  └──────────────┘  └───────────────┘  └────────────────┘ │
└────────────────────────────────────────────────────────────┘
                           │
              ┌────────────▼────────────┐
              │     Azure OpenAI        │
              │                         │
              │  GPT-4o                 │
              │  (Chat Completions API) │
              │                         │
              │  text-embedding-ada-002 │
              │  (Embeddings API)       │
              └─────────────────────────┘
```

### Key Design Decisions

- **No external web framework** — pure Python `http.server.ThreadingHTTPServer`. Chosen to eliminate C-extension dependencies that may be absent in corporate PyPI mirrors.
- **Server-Sent Events (SSE)** — one persistent connection per browser tab; each client gets its own `queue.Queue` fed by a `broadcast()` function. Far lighter than WebSockets for one-way push.
- **Separate embedding client** — `text-embedding-ada-002` requires API version `2023-05-15`, different from the GPT-4o chat API version. Two `AzureOpenAI` client instances handle this transparently.
- **Embedding cache** — computed once on startup, saved to `data/embeddings_cache.json`. Subsequent restarts load in milliseconds.
- **Background AI threads** — commentary is generated in daemon threads so the simulation loop never blocks waiting for the LLM.
- **SQLite persistence** — match events and narratives are stored locally for replay and audit.

---

## Project Structure

```
Football_AI_Hackathon/
├── .env                        ← Azure OpenAI credentials (never commit)
├── run.py                      ← Entry point — starts the HTTP server
├── requirements.txt            ← openai + python-dotenv only
│
├── backend/
│   ├── config.py               ← .env parsing, URL normalisation, API version mgmt
│   ├── ai_client.py            ← Unified Azure OpenAI client (chat + embeddings)
│   ├── main.py                 ← HTTP request router (GET/POST/SSE)
│   ├── match_simulator.py      ← Threaded match engine + SSE broadcast
│   ├── narrative_engine.py     ← Commentary, half-time, recap, social snippets
│   ├── tactical_analyser.py    ← Tactical breakdown + JSON-structured AI output
│   ├── embedding_search.py     ← Cosine similarity over cached embeddings
│   ├── translator.py           ← Multilingual translation via GPT-4o
│   ├── goal_analysis.py        ← Goal build-up sequence (pitch zones → arrows)
│   ├── goal_projection.py      ← xG projection, win %, shot map + AI "better angle"
│   ├── pundit_chat.py          ← Fan chat answer with live context
│   ├── guardrails.py           ← Regex prompt-injection pre-filter (no GPT call)
│   ├── key_moments.py          ← Key-moment insight generator
│   ├── live_feed.py            ← API-Football fixtures + replay/live threads
│   ├── agents.py               ← Multi-agent orchestrator (5 agents, blackboard)
│   ├── personalization.py      ← Per-fan rendering of the intelligence packet
│   ├── mcp_tools.py            ← Shared MCP tool registry (agents + server)
│   ├── mcp_server.py           ← MCP JSON-RPC 2.0 server (HTTP + stdio)
│   └── database.py             ← SQLite schema + helpers
│
├── frontend/
│   ├── index.html              ← Single-page app shell
│   ├── app.js                  ← SSE client, API calls, UI updates
│   └── style.css               ← Dark-mode football dashboard theme
│
├── data/
│   ├── players.json            ← Manchester City & Arsenal squads (15 players each)
│   ├── historical_moments.json ← 20 iconic Premier League moments for semantic search
│   └── embeddings_cache.json   ← Auto-generated on first run (do not edit)
│
├── logs/
│   └── match.db                ← SQLite database (auto-created)
│
├── ARCHITECTURE_FLOW.md        ← End-to-end component flow + "what triggers what"
├── VIDEO_SUBMISSION.avi        ← ≤2-min hackathon demo (narrated)
├── VIDEO_WALKTHROUGH.avi       ← Full ~10-min architecture walkthrough
│
└── venv313/                    ← Python 3.13 virtual environment
```

> See **`ARCHITECTURE_FLOW.md`** for the full component map and the exact
> trigger chain (user action → JS → endpoint → backend → AI → SSE → render).

---

## Prerequisites

- **Python 3.13** (`py -3.13 -m venv venv313`)
- **Azure OpenAI resource** with two deployments:
  - A GPT-4o (or later) deployment for chat
  - A `text-embedding-ada-002` deployment for embeddings

---

## Setup & Run

### 1. Create virtual environment

```bash
py -3.13 -m venv venv313
```

### 2. Install dependencies

```bash
venv313\Scripts\pip install openai python-dotenv
```

> If on a corporate network with a restricted PyPI mirror, download wheels manually and extract them to `venv313\Lib\site-packages\`.

### 3. Configure `.env`

```env
AZURE_OPENAI_API_KEY=your_api_key_here
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com
AZURE_OPENAI_MODEL=gpt-4o
AZURE_OPENAI_API_VERSION=2024-05-01-preview

AZURE_OPENAI_TEXT_EMBEDDING=text-embedding-ada-002
AZURE_OPENAI_EMBEDDING_VERSION=2023-05-15
AZURE_OPENAI_EMBEDDING_ENDPOINT=https://your-resource.openai.azure.com
```

### 4. Run the server

```bash
venv313\Scripts\python run.py
```

Open `http://localhost:8000` in your browser.

### 5. Using the app

1. Click **Start Match** to begin the simulation
2. **AI Commentary** appears automatically in the feed for goals, saves, cards, VAR events
3. Click **Analyse Now** in the Tactics panel for real-time formation analysis
4. Click **Half-Time Analysis** or **Full Match Recap** for narrative reports
5. Type in the **Similar Moments** search box to find historically analogous Premier League events
6. Select a language from the **Translation** panel to localise any narrative

---

## API Reference

### GET endpoints

| Endpoint | Description |
|---|---|
| `GET /api/match/state` | Current score, minute, possession, stats |
| `GET /api/match/events?n=20` | Last N match events |
| `GET /api/match/stream` | SSE stream — persistent connection for live events |
| `GET /api/players` | Squad data for both teams |
| `GET /api/match/participants` | Teams + players of the **current** match (adapts to simulation or replay) |
| `GET /api/translate/languages` | Supported language list |
| `GET /api/search/moments` | All historical moments in the dataset |
| `GET /api/mcp/tools` | List the MCP tools exposed by the server |

### POST endpoints

| Endpoint | Body | Description |
|---|---|---|
| `POST /api/match/start?speed=1.5` | — | Start simulation (`speed` = seconds per minute) |
| `POST /api/match/stop` | — | Stop simulation |
| `POST /api/narrative/commentary` | `{event, narrative_type}` | Generate commentary for an event |
| `POST /api/narrative/half-time` | — | Generate half-time analysis |
| `POST /api/narrative/recap` | — | Generate full match report |
| `POST /api/tactical/analyse` | `{focus_event?}` | Run tactical analysis |
| `POST /api/tactical/explain` | `{event}` | Explain a single moment tactically |
| `POST /api/search/similar` | `{query, top_k}` | Semantic search over historical moments |
| `POST /api/search/similar-event` | `{event, top_k}` | Find moments similar to a live event |
| `POST /api/translate` | `{text, language}` | Translate text to target language code |
| `POST /api/goal/buildup` | `{goal_event?}` | AI build-up sequence for a goal (pitch arrows) |
| `POST /api/goal/projection` | `{near_misses?}` | xG projection + shot map + AI "better angle" |
| `POST /api/agents/analyse` | `{profile}` | Run the 5-agent pipeline; returns the intelligence packet + trace |
| `POST /api/chat` | `{question, history}` | AI pundit answer (guardrails pre-filter first) |
| `POST /mcp` | JSON-RPC 2.0 | MCP transport: `initialize` · `tools/list` · `tools/call` |

The **MCP server** also runs over stdio for a real MCP host:
```bash
venv313\Scripts\python -m backend.mcp_server
```

### SSE event types

| `type` field | Fired when |
|---|---|
| `connected` | Client connects — includes current match state |
| `match_start` | Simulation begins |
| `goal` / `yellow_card` / `save` / `var_check` / … | Each match event |
| `half_time` / `full_time` | Milestone events |
| `ai_commentary` | AI commentary ready for a key event (async, ~1–2 s after event) |
| `social_snippet` | Auto-tweet text ready for a goal event |
| `goal_buildup` | AI build-up sequence for a goal (fills the Goals pitch diagram) |
| `key_moment` | Key-moment insight for the Key Moments timeline |
| `stats_update` | Possession / shots / fouls / cards refresh |
| `agent_overlay` | Broadcast overlay packet pushed after an agent run |
| `personalized` | Personalized briefing pushed after an agent run |

---

## Potential Improvements

### Near-term enhancements

| Improvement | What it adds |
|---|---|
| **Real match data** | Integrate [football-data.org](https://www.football-data.org/) or [API-Football](https://www.api-football.com/) for live Premier League fixtures instead of synthetic events |
| **Multiple fixtures** | Support a full match-day schedule, not just one hard-coded fixture |
| **Player ratings** | AI-generated post-match player ratings (1–10) with justification |
| **Substitution logic** | Simulate realistic manager substitutions based on scoreline and fatigue |
| **xG model** | Calculate expected goals per shot based on position, shot type, and defensive pressure |
| **Fan sentiment** | Simulated crowd reaction intensity tied to the scoreline and match context |
| **Voice commentary** | Pass AI commentary text to Azure Speech Service (Text-to-Speech) for audio output |
| **Push notifications** | Azure Notification Hubs for goal alerts to mobile subscribers |

### Architecture improvements

| Improvement | What it adds |
|---|---|
| **WebSockets** | Replace SSE with bidirectional WebSocket for fan interaction (polls, predictions) |
| **Redis pub/sub** | Replace in-process `queue.Queue` broadcast with Redis so multiple server instances share the same event stream |
| **Async backend** | Migrate to `asyncio`/`aiohttp` to avoid thread-per-connection overhead at scale |
| **Embedding pipeline** | Expand historical moments dataset to thousands of events; use Azure AI Search for scalable vector retrieval |
| **Streaming AI responses** | Use `stream=True` on Chat Completions to show commentary word-by-word as it generates |
| **Caching layer** | Cache repeated tactical analyses and translations in Redis to reduce LLM token spend |

---

## Enterprise Azure Architecture

For a production deployment serving thousands of concurrent fans:

```
┌─────────────────────────────────────────────────────────┐
│                  Azure Front Door (CDN)                  │
│            Global load balancing · WAF · TLS            │
└─────────────────────┬───────────────────────────────────┘
                      │
        ┌─────────────┴──────────────┐
        │                            │
┌───────▼────────┐          ┌────────▼───────┐
│  Azure Static  │          │ Azure Container│
│  Web Apps      │          │ Apps (Backend) │
│  (Frontend)    │          │ Auto-scale     │
└────────────────┘          └───────┬────────┘
                                    │
              ┌─────────────────────┼──────────────────────┐
              │                     │                      │
    ┌─────────▼──────┐  ┌──────────▼──────┐  ┌───────────▼──────┐
    │  Azure OpenAI  │  │  Azure Cache    │  │  Azure Event     │
    │  Service       │  │  for Redis      │  │  Hubs            │
    │                │  │  (pub/sub +     │  │  (real-time      │
    │  GPT-4o        │  │   response      │  │   match events   │
    │  text-embed-   │  │   cache)        │  │   ingestion)     │
    │  ada-002       │  └─────────────────┘  └──────────────────┘
    └────────────────┘
              │
    ┌─────────▼──────────────────────────────────────────────────┐
    │                    Azure AI Search                          │
    │   Vector index over thousands of historical moments        │
    │   Hybrid semantic + keyword search                         │
    └────────────────────────────────────────────────────────────┘
              │
    ┌─────────▼──────┐  ┌─────────────────┐  ┌────────────────┐
    │  Azure SQL /   │  │  Azure Service  │  │  Azure AI      │
    │  Cosmos DB     │  │  Bus            │  │  Speech        │
    │  (match +      │  │  (commentary    │  │  (TTS audio    │
    │   narrative    │  │   job queue)    │  │   commentary)  │
    │   history)     │  └─────────────────┘  └────────────────┘
    └────────────────┘

    ┌──────────────────────────────────────────────────────────┐
    │                 Azure Monitor + App Insights              │
    │   Token usage · latency · error rates · SSE connections  │
    └──────────────────────────────────────────────────────────┘
```

### Required Azure resources

| Resource | SKU / Tier | Purpose |
|---|---|---|
| **Azure OpenAI Service** | S0 | GPT-4o for commentary/tactics/translation; text-embedding-ada-002 for semantic search |
| **Azure Container Apps** | Consumption | Host Python backend with auto-scaling |
| **Azure Static Web Apps** | Free / Standard | Serve the frontend globally via CDN |
| **Azure Front Door** | Standard | Global load balancing, WAF, TLS termination |
| **Azure Cache for Redis** | C1 Basic | SSE broadcast pub/sub + LLM response caching |
| **Azure Event Hubs** | Standard | Ingest real-time match events from data providers |
| **Azure AI Search** | Basic | Vector + keyword search over large historical moments dataset |
| **Azure SQL Database** | Serverless | Match events, narratives, tactical analyses at scale |
| **Azure Service Bus** | Standard | Reliable queue for async AI commentary jobs |
| **Azure AI Speech** | Standard | Text-to-Speech for live audio commentary |
| **Azure Notification Hubs** | Free / Basic | Push goal alerts to mobile fans |
| **Azure Monitor + App Insights** | Pay-as-you-go | Full observability — token spend, latency, errors |
| **Azure Key Vault** | Standard | Secrets management (API keys, connection strings) |

---

## Data & Compliance Notes

- All match events in this project are **synthetically generated** — no real Premier League data is used
- Player names are sourced from publicly available squad information
- For production use with real match data, a commercial licence from the Premier League or a data provider (Opta, Statsperform, API-Football) is required
- AI-generated content should be reviewed before publication — add a human-in-the-loop moderation step for anything fan-facing

---

## Tech Stack Summary

| Layer | Technology |
|---|---|
| Frontend | Vanilla JavaScript (ES6+), HTML5, CSS3 — no build step |
| Backend | Python 3.13 stdlib (`http.server`, `threading`, `sqlite3`, `queue`) |
| AI | Azure OpenAI — GPT-4o (Chat Completions) + text-embedding-ada-002 |
| Realtime | Server-Sent Events (SSE) |
| Persistence | SQLite (local), JSON embeddings cache |
| Dependencies | `openai>=1.50.0`, `python-dotenv>=1.0.0` |
