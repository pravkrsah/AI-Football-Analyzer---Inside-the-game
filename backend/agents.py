"""
Multi-agent orchestration for Inside the Game.

A small, purpose-built agent framework (stdlib + Azure OpenAI only) in which
specialized agents each own one stage of the hackathon's required pipeline and
collaborate through a shared blackboard with explicit handoffs and per-agent
failure recovery — an end-to-end result no single prompt produces as well.

  Ingest  →  DataAgent        interpret synthetic events into metrics + leaders
  Explain →  TacticsAgent     formations / key battle / prediction
             ExplainAgent     WHY the latest moment matters
  Render  →  NarrativeAgent    broadcast beat + machine-readable overlay (stage d)
  Person. →  PersonaAgent      re-render for ONE fan profile (stage e)

Every agent reads/writes the shared blackboard and reaches the live match state
exclusively through the MCP tool registry (backend/mcp_tools.py), the same tools
an external MCP host would call — so this is genuine MCP integration, not a mock.
"""
from __future__ import annotations
import time

import backend.mcp_tools as tools
import backend.personalization as personalization


class Agent:
    """Base agent: a named role that acts on the shared blackboard and logs a trace step."""
    name = "agent"
    role = ""

    def act(self, bb: dict) -> None:  # pragma: no cover - overridden
        raise NotImplementedError

    def run(self, bb: dict) -> None:
        t0 = time.time()
        status, note, used = "ok", "", []
        try:
            used = self.act(bb) or []
        except Exception as e:  # failure recovery — never breaks the pipeline
            status, note = "recovered", str(e)[:120]
        bb["trace"].append({
            "agent": self.name, "role": self.role, "status": status,
            "tools": used, "note": note, "ms": int((time.time() - t0) * 1000),
        })


class DataAgent(Agent):
    """Stage: Interpret. Turns raw synthetic events into metrics + a player leaderboard,
    and flags a priority moment it hands off to the ExplainAgent."""
    name = "DataAgent"
    role = "Interpret synthetic events into explainable metrics"

    def act(self, bb):
        bb["match_state"] = tools.call_tool("get_match_state")
        bb["metrics"] = tools.call_tool("get_match_metrics")
        bb["leaders"] = tools.call_tool("get_player_performance", {"top": 5})
        key = tools.latest_key_event()
        if key and key.get("type") in ("goal", "penalty", "red_card"):
            bb["priority_moment"] = key           # handoff signal to ExplainAgent
        return ["get_match_state", "get_match_metrics", "get_player_performance"]


class TacticsAgent(Agent):
    """Stage: Explain. Formations, patterns, the decisive battle and a prediction."""
    name = "TacticsAgent"
    role = "Produce the tactical read of the match"

    def act(self, bb):
        bb["tactical"] = tools.call_tool("get_tactical_summary")
        return ["get_tactical_summary"]


class ExplainAgent(Agent):
    """Stage: Explain. Says WHY the latest (or handed-off priority) moment matters."""
    name = "ExplainAgent"
    role = "Explain why the key moment matters"

    def act(self, bb):
        pm = bb.get("priority_moment")
        minute = {"minute": pm.get("minute")} if pm else {}
        bb["explain"] = tools.call_tool("explain_moment", minute)
        return ["explain_moment"]


class NarrativeAgent(Agent):
    """Stage: Render. A broadcast beat plus a timed, machine-readable overlay packet
    (lower-third + momentum bar) that a rendering partner could draw on the live feed."""
    name = "NarrativeAgent"
    role = "Render insight into on-air narrative + graphics overlay"

    def act(self, bb):
        from backend.narrative_engine import generate_ambient_commentary
        state = bb.get("match_state", {})
        metrics = bb.get("metrics", {})
        bb["narrative"] = generate_ambient_commentary(state)

        # stage (d): machine-readable, timed overlay graphics for a broadcast feed
        tactical = bb.get("tactical", {})
        bb["overlay"] = {
            "t_minute": state.get("minute", 0),
            "lower_third": {
                "title": tactical.get("headline", "Live match intelligence"),
                "subtitle": f"{state.get('home_team','')} {state.get('score',{}).get('home',0)}"
                            f"-{state.get('score',{}).get('away',0)} {state.get('away_team','')}",
            },
            "momentum_bar": {
                "value": metrics.get("momentum", 0),      # -100..100 (home positive)
                "label": metrics.get("momentum_side", "balanced"),
            },
            "chips": [
                {"k": "Rhythm", "v": metrics.get("rhythm", "")},
                {"k": "Pressure", "v": f"{metrics.get('pressure_index', 0)}/100"},
                {"k": "Tempo", "v": f"{metrics.get('tempo_events_per_min', 0)}/min"},
            ],
            "ttl_seconds": 8,
        }
        return []


class PersonaAgent(Agent):
    """Stage: Personalize. Re-renders the shared packet for ONE fan profile."""
    name = "PersonaAgent"
    role = "Personalize the same intelligence per fan"

    def act(self, bb):
        bb["personalized"] = personalization.personalize(bb, bb.get("profile", {}))
        return []


# pipeline order (handoffs flow through the shared blackboard)
PIPELINE = [DataAgent(), TacticsAgent(), ExplainAgent(), NarrativeAgent(), PersonaAgent()]


def run_pipeline(profile: dict | None = None) -> dict:
    """Execute the full multi-agent pipeline and return the assembled intelligence packet."""
    t0 = time.time()
    bb: dict = {"profile": profile or {}, "trace": []}
    for agent in PIPELINE:
        agent.run(bb)

    bb["summary"] = {
        "agents": len(PIPELINE),
        "total_ms": int((time.time() - t0) * 1000),
        "pipeline": [a.name for a in PIPELINE],
        "recovered": [s["agent"] for s in bb["trace"] if s["status"] == "recovered"],
    }
    # drop the internal handoff object from the response
    bb.pop("priority_moment", None)
    return bb
