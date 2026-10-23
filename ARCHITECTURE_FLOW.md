# Inside the Game — End-to-End Component Flow

How every component connects, and **what triggers what** in the code. Read this
alongside `README.md` (overview) and `CLAUDE.md` (project conventions).

Legend: `→` a direct call · `⇒` an SSE push to the browser · `⟳` a background daemon thread.

---

## 1. Layers at a glance

```
Browser (frontend/)                         Backend (backend/, Python stdlib)            Azure
──────────────────────                      ─────────────────────────────────           ─────────────
index.html / app.js / style.css             main.py  (ThreadingHTTPServer router)
   │  fetch() REST  +  EventSource SSE          │
   │                                            ├─ match_simulator.py  ⟳ event loop      ┌───────────────┐
   │                                            ├─ live_feed.py        ⟳ replay/live ──▶ │ API-Football  │
   │                                            ├─ narrative_engine.py ─┐                └───────────────┘
   │                                            ├─ tactical_analyser.py ├─ ai_client.chat ─┐
   │                                            ├─ goal_analysis.py     │                  │ ┌───────────┐
   │                                            ├─ goal_projection.py   │                  ├▶│ GPT-4o    │
   │                                            ├─ pundit_chat.py ⟵ guardrails.py          │ └───────────┘
   │                                            ├─ translator.py ───────┘                  │ ┌───────────┐
   │                                            ├─ embedding_search.py ── get_embed_client ─▶│ ada-002   │
   │                                            │                                          │ └───────────┘
   │                                            ├─ agents.py ──▶ mcp_tools.py  (tool registry)
   │                                            └─ mcp_server.py ──▶ mcp_tools.py  (JSON-RPC: HTTP + stdio)
```

Everything AI goes through **one** function — `ai_client.chat()` — except embeddings,
which use `ai_client.get_embed_client()`.

---

## 2. Component catalog

| File | Responsibility | Triggered by | Calls |
|---|---|---|---|
| `run.py` | Process entry point | `python run.py` | `config.validate` → `init_db` → `embedding.load_historical_moments` → `create_server().serve_forever()` |
| `backend/config.py` | `.env` → typed config, endpoint/URL + API-version normalisation | import time | — |
| `backend/ai_client.py` | `chat()` (all text AI) + `get_embed_client()` (embeddings) | every AI module | Azure OpenAI |
| `backend/main.py` | HTTP router: `do_GET` / `do_POST` / `_sse_stream` | every browser request | all backend modules |
| `backend/match_simulator.py` | Synthetic match engine; `broadcast()` to all SSE queues; spawns AI threads | `POST /api/match/start` | `narrative_engine`, `key_moments`, `goal_analysis` (via ⟳ threads) |
| `backend/live_feed.py` | API-Football fixtures; replay/live threads reuse the same `broadcast()` | `/api/live/*` | API-Football, `narrative_engine` |
| `backend/narrative_engine.py` | commentary / ambient / half-time / recap / social snippet | simulator threads, `/api/narrative/*` | `ai_client.chat` |
| `backend/tactical_analyser.py` | tactical JSON breakdown; explain-a-moment | `/api/tactical/*`, agents, mcp_tools | `ai_client.chat` |
| `backend/goal_analysis.py` | goal build-up sequence (zones → pitch arrows) | `/api/goal/buildup`, simulator ⟳ | `ai_client.chat` |
| `backend/goal_projection.py` | xG projection, win %, next-goal odds, shot map + AI "better angle" | `/api/goal/projection`, mcp_tools | `ai_client.chat` |
| `backend/pundit_chat.py` | fan-chat answer with live context | `/api/chat` (after guardrails) | `ai_client.chat` |
| `backend/guardrails.py` | regex pre-filter (prompt-injection / length) — **no** GPT call | `/api/chat` | — |
| `backend/embedding_search.py` | cosine similarity over cached moment embeddings | `/api/search/*`, startup | `get_embed_client` |
| `backend/translator.py` | translate text to 1 of 9 languages | `/api/translate` | `ai_client.chat` |
| `backend/database.py` | SQLite schema + parameterised writes | startup, event logging | SQLite |
| `backend/agents.py` | **multi-agent orchestrator** (Data/Tactics/Explain/Narrative/Persona) | `/api/agents/analyse` | `mcp_tools`, `personalization` |
| `backend/personalization.py` | re-render one intelligence packet per fan profile | `agents.PersonaAgent` | `ai_client.chat`, `mcp_tools` |
| `backend/mcp_tools.py` | shared **tool registry** (6 tools) used by agents **and** MCP | agents, mcp_server | simulator state, tactical, goal_projection |
| `backend/mcp_server.py` | **MCP** JSON-RPC 2.0 server (HTTP `POST /mcp` + stdio) | MCP host / `/mcp` | `mcp_tools` |

---

## 3. Startup flow (`run.py`)

```
python run.py
  1. config.validate()                 → prints endpoint/model/version; raises if keys missing
  2. init_db()                         → creates logs/match.db tables if absent
  3. embedding.load_historical_moments()
        → loads data/historical_moments.json (20 moments)
        → first run: embeds via ada-002, caches to data/embeddings_cache.json
        → later runs: loads the cache in milliseconds
  4. create_server(port=8000).serve_forever()   → ThreadingHTTPServer
```

---

## 4. Page load (what the browser does)

```
Browser                                   main.py
  GET /                   →  serve frontend/index.html      (Cache-Control: no-cache)
  GET /static/app.js      →  serve frontend/app.js
  GET /static/style.css   →  serve frontend/style.css
  [DOMContentLoaded in app.js]
  GET /api/players        →  data/players.json              → fills Squads panel
  GET /api/match/stream   →  _sse_stream() opens a queue.Queue, appends to simulator.clients
                          ⇐  event: connected { state }     → applyState()
```

The EventSource stays open for the page lifetime; every later `⇒` lands here and is
routed by **`handleEvent(data)`** on `data.type`.

---

## 5. Simulation — the core event loop & its triggers

`POST /api/match/start?speed=` → `threading.Thread(run_simulation)` ⟳

```
run_simulation(speed):
  _reset_state()                     # restores Man City vs Arsenal fixture + zeroes stats
  ⇒ match_start
  for minute in 1..91:
      _generate_event(minute)        # weighted random event; mutates score/stats
      ⇒ <event>                      # pass/shot/goal/foul/card/save/...
      if event.type in (goal, yellow_card, red_card, penalty, var_check,
                        half_time, full_time, save):
          ⟳ _ai_commentary_task(event)     # → narrative.generate_live_commentary ⇒ ai_commentary
          ⟳ _key_moment_task(event)        # → key_moments.generate_moment_insight ⇒ key_moment
      minute == 45  → ⇒ half_time (+ ⟳ key moment)
      minute == 91  → ⇒ full_time  (+ ⟳ key moment); finished = True
```

### What triggers what (background fan-out)

| Trigger event | Spawns ⟳ | Produces ⇒ |
|---|---|---|
| goal / card / save / penalty / var_check / HT / FT | `_ai_commentary_task` | `ai_commentary` |
| goal | (inside commentary task) `generate_social_snippet` | `social_snippet` |
| goal | (inside commentary task) `_goal_buildup_task` → `goal_analysis.analyse_goal_buildup` | `goal_buildup` |
| any key event + HT/FT | `_key_moment_task` | `key_moment` |

All AI runs in **daemon threads** so the sim loop never blocks on the LLM — commentary
therefore lands 1–3 s *after* its event.

### Browser routing (`app.js handleEvent`)

```
match_start      → reset feeds/score/stats/chat
goal/own_goal    → updateScore + goal card + fetch /api/goal/buildup (pitch SVG)
yellow/red_card  → event card
ai_commentary    → commentary feed (+ Web Speech API if voice on)
social_snippet   → social feed
key_moment       → Key Moments timeline
goal_buildup     → fill the goal card's pitch diagram (buildPitchSVG)
stats_update     → possession bar + stat rows
half_time/full_time → status badge; full_time grades the fan prediction
agent_overlay / personalized → pushed by /api/agents/analyse (see §9)
```

---

## 6. Live / Replay (real fixtures)

```
GET  /api/live/fixtures?mode=recent  → live_feed.get_recent_fixtures() → API-Football
POST /api/live/replay {fixture_id}   → live_feed.start_replay() ⟳
     ⟳ fetch /fixtures, /fixtures/events, /fixtures/statistics
     ⇒ match_start / goal / card / ai_commentary / stats_update   (same pipeline as §5)
```

`live_feed` **reuses `match_simulator.broadcast()` and `match_state`**, so the browser
cannot tell replay from simulation. A replay overwrites `match_state["home_team"]`;
`_reset_state()` restores the simulator fixture on the next `/api/match/start`.

---

## 7. Goals tab — build-up diagram

```
goal happens  ⇒ goal_buildup (auto, from simulator ⟳)      OR    user clicks a goal card
   → POST /api/goal/buildup { goal_event }
   → goal_analysis.get_preceding_events() + analyse_goal_buildup()  (GPT-4o, JSON)
   → returns buildup_sequence of zones (GK..A-C..GOAL)
   → app.js buildPitchSVG(sequence) draws the full pitch + animated passing arrows
```

---

## 8. Projection tab — xG + shot analysis (distinct from Goals)

```
user clicks "Project Goals"  → POST /api/goal/projection
   → goal_projection.project():
        compute_projection()   # deterministic: xG, projected score, win %, next-goal %
        shot_map(limit=4)      # recent goals + misses
            └─ misses → ai_client.chat  "better angle" (shooting-coach, 1 sentence)
   → app.js renders:
        projection header (NOW → PROJECTED, xG, win-probability bar)
        per shot: shotTrajectorySvg()  # goal-view: parabola + angle wedge + outcome
                  + dashed green "better angle" arc for misses + AI text
```

`get_goal_projection` (deterministic part) is **also an MCP tool** (§10).

---

## 9. For You tab — multi-agent pipeline + personalization

```
tab opens        → initForYou()
   → GET /api/match/participants   # teams + players of the CURRENT match (sim OR replay)
   → populate favourite-club / focus-player dropdowns (re-run every open)

click "Generate" → POST /api/agents/analyse { profile }
   → agents.run_pipeline(profile):     # shared blackboard `bb`, per-agent try/except recovery
        DataAgent      → mcp_tools: get_match_state + get_match_metrics + get_player_performance
                         (sets bb.priority_moment if last event was a goal → handoff)
        TacticsAgent   → mcp_tools.get_tactical_summary          (GPT-4o)
        ExplainAgent   → mcp_tools.explain_moment(priority)      (GPT-4o)
        NarrativeAgent → narrative.generate_ambient_commentary   (GPT-4o)
                         + builds machine-readable `overlay` (lower-third, momentum bar)
        PersonaAgent   → personalization.personalize(bb, profile) (GPT-4o)
   ⇒ agent_overlay      (broadcast to all SSE clients)
   ⇒ personalized       (broadcast to all SSE clients)
   → response: { match_state, metrics, leaders, tactical, explain, narrative,
                 overlay, personalized, trace[], summary }
   → app.js renders the personalized briefing + a clickable agent pipeline
        (tap a row → fyAgentDetail() reveals that agent's contribution from the packet)
```

Every agent reaches live state **only** through `mcp_tools` — the same registry an
external MCP host calls — so this is genuine MCP integration, not a mock.

---

## 10. MCP server — mount the live match as agent tools

```
backend/mcp_tools.py   TOOLS = {
    get_match_state, get_recent_events, get_player_performance,
    get_match_metrics, get_tactical_summary, explain_moment, get_goal_projection }

HTTP transport:   POST /mcp  (JSON-RPC 2.0)  → mcp_server.handle_jsonrpc()
                    initialize · tools/list · tools/call
stdio transport:  python -m backend.mcp_server   (line-delimited JSON-RPC)
                    → usable by VS Code / Claude Desktop / Azure MCP
GET /api/mcp/tools → convenience discovery for the browser
```

`agents.py` and `mcp_server.py` share `mcp_tools`, so agents and external clients see
identical data.

---

## 11. Pundit chat — safety first

```
POST /api/chat { question, history }
   → guardrails.check_question()        # regex: length + prompt-injection — NO GPT call
        fail → return the rejection string immediately
        pass ↓
   → pundit_chat.answer_question(question, state, last-8 events, history[-4])
        system guard + live match context injected → ai_client.chat (max 220 tokens)
```

---

## 12. Other on-demand endpoints

| User action | Endpoint | Backend | AI |
|---|---|---|---|
| Analyse Tactics | `POST /api/tactical/analyse` | `tactical_analyser` | GPT-4o (JSON) |
| Half-time / Recap | `POST /api/narrative/half-time` · `/recap` | `narrative_engine` | GPT-4o |
| Similar Moments | `POST /api/search/similar` | `embedding_search` | ada-002 |
| Auto similar-event | `POST /api/search/similar-event` | `embedding_search` | ada-002 |
| Translate | `POST /api/translate` | `translator` | GPT-4o |

---

## 13. Threading & state model

- **One module-level `match_state` dict** holds the live match (shared by simulator, live_feed, agents, projection, mcp_tools).
- **One `clients: list[queue.Queue]`** — one queue per open browser tab; `broadcast()` puts each event on every queue under `clients_lock`.
- **Every LLM call is off the critical path**: the sim loop spawns daemon threads; on-demand endpoints run inside the request's own server thread (ThreadingHTTPServer = one thread per request).
- **No external datastore** — SQLite + in-process queues. (Production swap: Redis pub/sub for `broadcast`, Azure SQL/Cosmos for state — see README "Enterprise Azure Architecture".)

---

## 14. Request → feature quick index

| Tab / action | REST trigger | SSE it listens for |
|---|---|---|
| Live feed & scoreboard | `GET /api/match/stream` | `match_start`, event types, `stats_update`, `half_time`, `full_time` |
| AI Commentary | — (push only) | `ai_commentary` |
| Tactics | `POST /api/tactical/analyse` | — |
| For You (agents) | `POST /api/agents/analyse` | `agent_overlay`, `personalized` |
| Goals | `POST /api/goal/buildup` | `goal_buildup` |
| Projection | `POST /api/goal/projection` | — |
| Players | (client-side from events) | all events |
| Key Moments | — (push only) | `key_moment` |
| Similar Moments | `POST /api/search/similar` | — |
| Multi-Language | `POST /api/translate` | — |
| Recap | `POST /api/narrative/recap` · `/half-time` | — |
| Ask the Pundit | `POST /api/chat` | — |
```
