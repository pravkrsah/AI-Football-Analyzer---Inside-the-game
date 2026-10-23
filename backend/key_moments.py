"""
Key moments engine — one punchy insight per significant match event.

Deliberately different from tactical_analyser (whole-match patterns) and
goal_analysis (build-up sequence). This answers: "why does THIS moment matter
to the match narrative right now?"
"""

from backend.ai_client import chat

KEY_EVENT_TYPES = {
    "goal", "own_goal", "yellow_card", "red_card",
    "penalty", "penalty_missed", "var_check", "save",
    "half_time", "full_time", "substitution",
}

EVENT_LABELS = {
    "goal":           "Goal",
    "own_goal":       "Own Goal",
    "yellow_card":    "Yellow Card",
    "red_card":       "Red Card",
    "penalty":        "Penalty",
    "penalty_missed": "Penalty Missed",
    "var_check":      "VAR Check",
    "save":           "Key Save",
    "half_time":      "Half Time",
    "full_time":      "Full Time",
    "substitution":   "Substitution",
}

EVENT_ICONS = {
    "goal":           "⚽",
    "own_goal":       "⚽",
    "yellow_card":    "🟨",
    "red_card":       "🟥",
    "penalty":        "🎯",
    "penalty_missed": "❌",
    "var_check":      "🖥️",
    "save":           "🧤",
    "half_time":      "⏸️",
    "full_time":      "🏁",
    "substitution":   "🔄",
}


def is_key_event(event: dict) -> bool:
    return event.get("type") in KEY_EVENT_TYPES


def generate_moment_insight(event: dict, match_state: dict, recent_events: list) -> str:
    """
    One or two sentences on why this moment matters to the match narrative.
    Not a description of what happened — that's already in event['description'].
    """
    score = event.get("score", match_state.get("score", {}))
    etype = event.get("type", "")

    # Milestone events — use a template, no API call needed
    if etype == "half_time":
        h, a = score.get("home", 0), score.get("away", 0)
        home, away = match_state.get("home_team", "Home"), match_state.get("away_team", "Away")
        if h == a:
            return f"All square at the break — both managers will need to find a breakthrough in the second half."
        leader = home if h > a else away
        trailer = away if h > a else home
        return f"{leader} go in ahead — {trailer} must recalibrate at half-time or risk this slipping away."

    if etype == "full_time":
        h, a = score.get("home", 0), score.get("away", 0)
        home, away = match_state.get("home_team", "Home"), match_state.get("away_team", "Away")
        if h == a:   return f"The points are shared — a fair result given the balance of play across the 90 minutes."
        winner = home if h > a else away
        return f"{winner} take all three points in what proved a decisive afternoon."

    # Context lines for the prompt
    context_lines = []
    for e in recent_events[-5:]:
        context_lines.append(
            f"  {e['minute']}' [{e['type'].upper()}] {e.get('team','')} — {e.get('description','')}"
        )
    context = "\n".join(context_lines) or "  (no recent events)"

    prompt = f"""You are a Premier League pundit giving a one-sentence verdict on a key match moment.
DO NOT describe what happened — the viewer already saw it. Instead explain WHY it matters to the match narrative.

Match: {match_state.get('home_team','')} {score.get('home',0)} - {score.get('away',0)} {match_state.get('away_team','')}
Minute: {event.get('minute',0)}'
Event: [{etype.upper()}] {event.get('player','')} ({event.get('team','')}) — {event.get('description','')}

Recent context:
{context}

Give exactly ONE sentence (max 25 words) on the match-changing significance of this moment:"""

    try:
        return chat(prompt, max_tokens=80, temperature=0.75)
    except Exception:
        return _fallback_insight(etype, event, match_state, score)


def _fallback_insight(etype: str, event: dict, match_state: dict, score: dict) -> str:
    """Template insight used when the AI call fails (rate limit, network error, etc.)."""
    player = event.get("player") or "The player"
    team   = event.get("team") or "the team"
    h, a   = score.get("home", 0), score.get("away", 0)
    home   = match_state.get("home_team", "Home")
    away   = match_state.get("away_team", "Away")

    if etype in ("goal", "own_goal"):
        if h == a:
            return f"The scores are level — momentum has shifted and both sides will need to respond."
        leader = home if h > a else away
        trailer = away if h > a else home
        return f"{leader} are ahead now — {trailer} must find a way back into this match."
    if etype == "yellow_card":
        return f"{player}'s booking is a warning — one more and they'll be walking a tightrope for the rest of the game."
    if etype == "red_card":
        return f"Down to ten men — this red card completely changes the dynamic of the match for {team}."
    if etype == "penalty":
        return f"A penalty in this moment could prove pivotal — enormous pressure on both taker and goalkeeper."
    if etype == "var_check":
        return f"VAR is intervening — the outcome of this review could change the course of the match entirely."
    if etype == "save":
        return f"A crucial save — that stop may turn out to be one of the defining moments of this game."
    return f"A key moment at {event.get('minute', '?')}' that could yet prove decisive in this match."


def build_moment_record(event: dict, insight: str) -> dict:
    """Package an event + insight for SSE broadcast and API response."""
    return {
        "type":        "key_moment",
        "minute":      event.get("minute"),
        "event_type":  event.get("type"),
        "label":       EVENT_LABELS.get(event.get("type", ""), event.get("type", "")),
        "icon":        EVENT_ICONS.get(event.get("type", ""), "•"),
        "player":      event.get("player", ""),
        "team":        event.get("team", ""),
        "description": event.get("description", ""),
        "score":       event.get("score", {}),
        "insight":     insight,
    }
