# Inside the Game — Hackathon Submission

**Event:** Microsoft + Premier League — *Inside the Game: Developer Hackathon*
**Project:** Inside the Game — real-time, explainable, personalized match intelligence from synthetic football events.

---

## Elevator pitch

Football stories don't end with the scoreline. **Inside the Game** turns a stream of
**synthetic football events** into **explainable, personalized match intelligence** for
studio, broadcast, and streaming.

A live engine streams synthetic events over Server-Sent Events. A team of **five specialist
AI agents** — Data, Tactics, Explain, Narrative, and Persona — share a blackboard, hand off to
each other, and reach the live match through **Model Context Protocol (MCP) tools** to produce
one intelligence packet. The same intelligence is then **re-rendered for each fan** (analyst vs
casual, favourite club, player-focus, nine languages). Every goal is **explained** with a build-up
diagram, and every missed chance gets an AI shooting coach's **"better angle."** It runs entirely
in **pure Python on Azure OpenAI** — no web framework.

## What it does

- **Real-time match intelligence** — synthetic events → momentum, pressure, tempo, control-vs-chaos.
- **Multi-agent pipeline (For You)** — 5 agents, shared blackboard, handoffs, failure recovery; each agent is clickable to reveal its contribution.
- **MCP server** — exposes the live match as agent tools over **HTTP (`POST /mcp`)** and **stdio** (`python -m backend.mcp_server`) for VS Code / Claude Desktop / Azure MCP.
- **Personalization** — one packet, many experiences (mode, club, player, language).
- **Explainability** — goal build-up pitch diagram + a machine-readable broadcast overlay.
- **Goal projection & shot analysis** — xG, projected score, win probability, next-goal odds; per-shot trajectory + angle, and a drawn "better angle" for misses.
- **AI commentary, half-time & match recap, social snippets, semantic search** over 20 iconic PL moments, **9-language** delivery, fan prediction, player tracking, voice commentary.
- **Safety** — regex prompt-injection pre-filter (zero GPT calls) + hardened system prompt + parameterised SQL.

## Microsoft / Azure technologies

| Area | Used |
|---|---|
| AI models | **Azure OpenAI** — GPT-4o (chat/JSON) + `text-embedding-ada-002` (embeddings) |
| Agentic design | Custom **multi-agent orchestrator** (shared blackboard, handoffs, recovery) |
| Tooling protocol | **Model Context Protocol** server (JSON-RPC 2.0) — HTTP + stdio |
| Data | Self-generated **synthetic, football-realistic** event stream (per rules §4.7) |
| Runtime | Python 3.13 standard library (`http.server`, `threading`, `queue`, `sqlite3`) |

**Category fit:** Grand Prize (end-to-end, explainable, personalized) · **Best Multi-Agent System**
(5 agents + MCP) · Best Use of Microsoft Foundry *(migration path ready)* · Best Enterprise /
Azure Cloud Native *(deployment path in README "Enterprise Azure Architecture")*.

## How it meets the required pipeline (§4.1)

Ingest (synthetic SSE events) → Interpret (`DataAgent` metrics) → Explain (`TacticsAgent` +
`ExplainAgent` "why it matters") → Render (`NarrativeAgent` on-air text + machine-readable overlay)
→ Personalize (`PersonaAgent` per fan). Full trace in `ARCHITECTURE_FLOW.md`.

---

## Run & test instructions (for judges)

**Prerequisites:** Windows/macOS/Linux, Python 3.13, an Azure OpenAI resource with a GPT-4o
deployment and a `text-embedding-ada-002` deployment.

```bash
# 1. create + activate a venv, then install the two deps
python -m venv venv313
venv313\Scripts\pip install -r requirements.txt     # openai, python-dotenv

# 2. configure credentials
copy .env.example .env         # then fill in your Azure OpenAI values

# 3. run (from the project root)
venv313\Scripts\python run.py
#    → open http://localhost:8000
```

**90-second demo path:** click **▶ Start Match** → watch live events + AI commentary →
open **For You**, pick a club/player/mode, **Generate**, and tap an agent to see its output →
open **Projection**, **Project Goals** → open **Goals** for the build-up diagram.

**MCP (optional):**
```bash
curl -s http://localhost:8000/api/mcp/tools              # list tools over HTTP
venv313\Scripts\python -m backend.mcp_server             # run as a stdio MCP server
```

**Demo video:** https://youtu.be/yrcy3w02iDE
**GitHub URL** https://github.com/pravkrsah/AI-Football-Analyzer---Inside-the-game.git
---

## Submission checklist

- [ ] Registered before Oct 20 (12:00pm PT) — *required to submit*
- [ ] Public **GitHub** repo (with `.env` git-ignored; keys rotated)
- [ ] Demo video **< 2 min** uploaded to YouTube/Vimeo + link added above
- [ ] Project pitch/description (this file)
- [ ] Free testing access / run instructions (above)
- [ ] Submitted on **aka.ms/insidethegame** (Innovation Studio Platform) by **Oct 27, 11:59pm PT**
