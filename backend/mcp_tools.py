"""
Shared tool registry for the Inside-the-Game match-intelligence platform.

These tools are the single source of truth that BOTH expose the match state to:
  1. the Model Context Protocol server  (backend/mcp_server.py), and
  2. the multi-agent orchestrator        (backend/agents.py).

Each tool has a JSON-Schema input spec (MCP-compatible) and a pure Python
callable. Tools that only read/aggregate state are deterministic and fast;
a few are AI-backed (tactical summary, explainability) and delegate to the
existing engines so there is one implementation, not two.
"""
from __future__ import annotations
import time


# ── low-level state access (kept lazy to avoid import cycles) ────────────────
def _sim():
    import backend.match_simulator as simulator
    return simulator


def _all_events() -> list:
    return list(_sim().match_state.get("events", []))


# ── deterministic analytics ─────────────────────────────────────────────────
_DISRUPTIVE = {"foul", "tackle", "yellow_card", "red_card", "offside", "var_check"}
_ATTACKING = {"shot", "goal", "save", "penalty", "corner", "header", "dribble"}


def compute_player_performance(player: str | None = None, top: int = 10) -> dict:
    """Build an in-memory performance map from every event with a named player."""
    perf: dict[str, dict] = {}
    for e in _all_events():
        name = e.get("player")
        if not name:
            continue
        rec = perf.setdefault(name, {
            "player": name, "team": e.get("team"), "actions": 0,
            "goals": 0, "shots": 0, "passes": 0, "tackles": 0,
            "saves": 0, "cards": 0, "key_actions": 0, "types": {},
        })
        t = e.get("type", "")
        rec["actions"] += 1
        rec["types"][t] = rec["types"].get(t, 0) + 1
        if t == "goal":
            rec["goals"] += 1; rec["key_actions"] += 1
        elif t in ("shot", "shot_off_target", "save", "penalty", "penalty_missed"):
            rec["shots"] += 1
        elif t == "pass":
            rec["passes"] += 1
        elif t == "tackle":
            rec["tackles"] += 1
        elif t in ("yellow_card", "red_card"):
            rec["cards"] += 1
        if t in ("goal", "save", "penalty", "yellow_card", "red_card"):
            rec["key_actions"] += 1

    ranked = sorted(perf.values(), key=lambda r: (r["key_actions"], r["actions"]), reverse=True)
    if player:
        one = perf.get(player)
        return {"player": one} if one else {"player": None, "note": f"{player} not involved yet"}
    return {"count": len(ranked), "leaders": ranked[:top]}


def compute_match_metrics() -> dict:
    """
    Interpret raw events into explainable, broadcast-ready match metrics:
    tempo, pressure index, momentum (which way the game is swinging), and a
    control-vs-chaos read — the 'why it matters' signals judges ask for.
    """
    events = _all_events()
    state = _sim().get_state()
    minute = max(1, state.get("minute", 1))
    recent = events[-25:]

    disruptive = sum(1 for e in recent if e.get("type") in _DISRUPTIVE)
    attacking = sum(1 for e in recent if e.get("type") in _ATTACKING)
    passes = sum(1 for e in recent if e.get("type") == "pass")
    total = max(1, len(recent))

    # control vs chaos: share of calm build-up vs disruptive, contested play
    control_ratio = passes / total
    chaos_ratio = disruptive / total
    if control_ratio >= 0.5:
        rhythm = "control"
    elif chaos_ratio >= 0.35:
        rhythm = "chaos"
    else:
        rhythm = "contested"

    # momentum: +100 = all home, -100 = all away, from recent attacking actions
    home_att = sum(1 for e in recent if e.get("type") in _ATTACKING and e.get("team") == state.get("home_team"))
    away_att = sum(1 for e in recent if e.get("type") in _ATTACKING and e.get("team") == state.get("away_team"))
    swing = home_att - away_att
    denom = max(1, home_att + away_att)
    momentum = round(100 * swing / denom)

    tempo = round(len(recent) / max(1, min(minute, 25)), 2)  # events per minute recently
    poss = state.get("possession", {})

    return {
        "minute": minute,
        "tempo_events_per_min": tempo,
        "pressure_index": round(100 * chaos_ratio),
        "momentum": momentum,                       # -100..100 (home positive)
        "momentum_side": (state.get("home_team") if momentum > 10
                          else state.get("away_team") if momentum < -10 else "balanced"),
        "rhythm": rhythm,                           # control | contested | chaos
        "possession": poss,
        "attacking_actions_recent": attacking,
        "disruptive_actions_recent": disruptive,
    }


def latest_key_event() -> dict | None:
    for e in reversed(_all_events()):
        if e.get("type") in ("goal", "penalty", "red_card", "yellow_card", "save", "var_check"):
            return e
    return _all_events()[-1] if _all_events() else None


# ── AI-backed tools (delegate to existing engines — one implementation) ──────
def get_tactical_summary() -> dict:
    import backend.tactical_analyser as tactical
    events = _all_events()
    if len(events) < 3:
        return {"error": "not enough events yet"}
    return tactical.analyse_tactical_moment(events, _sim().get_state())


def explain_moment(minute: int | None = None) -> dict:
    import backend.tactical_analyser as tactical
    events = _all_events()
    if not events:
        return {"error": "no events yet"}
    if minute is not None:
        event = next((e for e in reversed(events) if e.get("minute") == minute), latest_key_event())
    else:
        event = latest_key_event()
    text = tactical.explain_key_moment(event, events, _sim().get_state())
    return {"minute": event.get("minute"), "type": event.get("type"), "why_it_matters": text}


# ── MCP tool registry (name → schema + callable) ─────────────────────────────
TOOLS: dict[str, dict] = {
    "get_match_state": {
        "description": "Current score, minute, possession and live statistics for the match.",
        "inputSchema": {"type": "object", "properties": {}},
        "handler": lambda **k: _sim().get_state(),
    },
    "get_recent_events": {
        "description": "The most recent N synthetic match events (passes, shots, tackles, goals, cards).",
        "inputSchema": {"type": "object", "properties": {
            "n": {"type": "integer", "description": "How many recent events", "default": 10}}},
        "handler": lambda n=10, **k: {"events": _sim().get_recent_events(int(n))},
    },
    "get_player_performance": {
        "description": "Per-player performance map built from events; omit 'player' for the top leaderboard.",
        "inputSchema": {"type": "object", "properties": {
            "player": {"type": "string"}, "top": {"type": "integer", "default": 10}}},
        "handler": lambda player=None, top=10, **k: compute_player_performance(player, int(top)),
    },
    "get_match_metrics": {
        "description": "Interpreted metrics: tempo, pressure index, momentum, and control-vs-chaos rhythm.",
        "inputSchema": {"type": "object", "properties": {}},
        "handler": lambda **k: compute_match_metrics(),
    },
    "get_tactical_summary": {
        "description": "AI tactical breakdown: formations, patterns, key battle and a prediction.",
        "inputSchema": {"type": "object", "properties": {}},
        "handler": lambda **k: get_tactical_summary(),
    },
    "explain_moment": {
        "description": "Explain WHY a given minute's moment matters tactically; defaults to the latest key moment.",
        "inputSchema": {"type": "object", "properties": {
            "minute": {"type": "integer"}}},
        "handler": lambda minute=None, **k: explain_moment(minute),
    },
    "get_goal_projection": {
        "description": "Expected-goals (xG) projection: projected final score, win probabilities and next-goal odds.",
        "inputSchema": {"type": "object", "properties": {}},
        "handler": lambda **k: _goal_projection(),
    },
}


def _goal_projection() -> dict:
    import backend.goal_projection as gp
    return gp.compute_projection()


def call_tool(name: str, arguments: dict | None = None) -> dict:
    """Invoke a registered tool by name with keyword arguments. Returns a dict."""
    spec = TOOLS.get(name)
    if not spec:
        return {"error": f"unknown tool '{name}'"}
    args = arguments or {}
    t0 = time.time()
    try:
        result = spec["handler"](**args)
    except Exception as e:  # tools never raise to callers
        result = {"error": str(e)}
    if isinstance(result, dict):
        result.setdefault("_ms", int((time.time() - t0) * 1000))
    return result


def list_tools() -> list[dict]:
    return [{"name": n, "description": s["description"], "inputSchema": s["inputSchema"]}
            for n, s in TOOLS.items()]
