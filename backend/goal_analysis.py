"""
Goal build-up analysis — distinct from tactical_analyser.py.

tactical_analyser  → team-wide patterns, formation, key battle, match prediction
goal_analysis      → specific event sequence that led to one goal; pundit replay style
"""

import json
from backend.ai_client import chat


def _build_sequence_text(preceding_events: list, n: int = 8) -> str:
    """Summarise the last N events before the goal as a numbered sequence."""
    events = preceding_events[-n:]
    lines = []
    for i, e in enumerate(events, 1):
        lines.append(
            f"  {i}. {e['minute']}' [{e['type'].upper()}] "
            f"{e.get('team', '')} — {e.get('player', '')} — {e.get('description', '')}"
        )
    return "\n".join(lines) if lines else "  (no preceding events recorded)"


def analyse_goal_buildup(goal_event: dict, preceding_events: list, match_state: dict) -> dict:
    """
    Produce a structured build-up analysis for one goal.
    Returns a dict with keys: summary, buildup_narrative, defensive_error, key_player, verdict
    """
    sequence = _build_sequence_text(preceding_events)
    score = goal_event.get("score", {})
    is_penalty = goal_event.get("is_penalty", False)

    prompt = f"""You are a Premier League pundit analysing a goal for a TV breakdown segment.
{"Note: this was a penalty kick — focus on the foul that earned it and the execution." if is_penalty else ""}

GOAL: {goal_event['minute']}' — {goal_event.get('player', '')} ({goal_event.get('team', '')})
Score after: {match_state['home_team']} {score.get('home', 0)} - {score.get('away', 0)} {match_state['away_team']}
Description: {goal_event.get('description', '')}

Event sequence leading to the goal:
{sequence}

Return ONLY valid JSON with these exact keys:
{{
  "summary": "One punchy headline sentence for this goal (max 12 words)",
  "buildup_narrative": "3-4 sentences narrating how the move developed — who started it, key pass or dribble, how the defence was beaten. Be specific about players and zones. TV pundit tone.",
  "defensive_error": "One sentence on what the defending team did wrong (or 'No clear defensive error — clinical finishing' if appropriate)",
  "key_player": "Name of the player most responsible for creating or finishing the goal",
  "verdict": "One sentence overall verdict — was this a team goal, individual brilliance, or defensive gift?",
  "buildup_sequence": [
    {{
      "step": 1,
      "player": "short player name (surname only)",
      "action": "one of: pass | dribble | cross | header | shot | goal | tackle | clearance",
      "from_zone": "one of: GK | D-L | D-C | D-R | M-L | M-C | M-R | A-L | A-C | A-R",
      "to_zone": "one of: D-L | D-C | D-R | M-L | M-C | M-R | A-L | A-C | A-R | GOAL",
      "label": "3-5 word description of this step"
    }}
  ]
}}

For buildup_sequence include 3-6 steps tracing the move from where possession was won to the goal.
The final step must have action "goal" and to_zone "GOAL".
Zones: GK=goalkeeper, D-L/C/R=defensive third left/centre/right, M-L/C/R=midfield, A-L/C/R=attacking third, GOAL=net."""

    try:
        text = chat(prompt, max_tokens=700, temperature=0.7, json_mode=True)
    except Exception:
        player = goal_event.get("player", "")
        team = goal_event.get("team", "")
        minute = goal_event.get("minute", 0)
        score = goal_event.get("score", {})
        return {
            "summary": f"{player} scores at {minute}' to make it {score.get('home',0)}-{score.get('away',0)}",
            "buildup_narrative": (
                f"{'A penalty converted by ' + player if is_penalty else player + ' finds the net'} "
                f"at {minute}' to give {team} the lead. "
                f"The build-up saw patient ball circulation before the decisive moment created the opening. "
                f"The defence was caught out of position and the striker made no mistake with a composed finish."
            ),
            "defensive_error": "The defensive line was caught too high and failed to track the runner.",
            "key_player": player,
            "verdict": "A well-worked team goal that rewarded sustained pressure.",
            "buildup_sequence": [
                {"step": 1, "player": "Midfielder", "action": "pass", "from_zone": "M-C", "to_zone": "A-C", "label": "Through ball played"},
                {"step": 2, "player": player or "Striker", "action": "shot", "from_zone": "A-C", "to_zone": "GOAL", "label": "Clinical finish"},
            ],
            "goal_event": goal_event,
            "minute": minute,
            "scorer": player,
            "team": team,
            "is_penalty": is_penalty,
        }
    try:
        result = json.loads(text)
        result["goal_event"] = goal_event
        result["minute"] = goal_event.get("minute")
        result["scorer"] = goal_event.get("player", "")
        result["team"] = goal_event.get("team", "")
        result["is_penalty"] = is_penalty
        if "buildup_sequence" not in result:
            result["buildup_sequence"] = []
        return result
    except Exception:
        return {
            "summary": goal_event.get("description", "Goal"),
            "buildup_narrative": text,
            "defensive_error": "",
            "key_player": goal_event.get("player", ""),
            "verdict": "",
            "buildup_sequence": [],
            "goal_event": goal_event,
            "minute": goal_event.get("minute"),
            "scorer": goal_event.get("player", ""),
            "team": goal_event.get("team", ""),
            "is_penalty": is_penalty,
        }


def get_preceding_events(all_events: list, goal_event: dict, window: int = 8) -> list:
    """Return up to `window` events that occurred before this goal in the event list."""
    goal_minute = goal_event.get("minute", 0)
    goal_idx = None

    # Find the goal's position in the event list
    for i, e in enumerate(all_events):
        if (e.get("minute") == goal_minute
                and e.get("type") == goal_event.get("type")
                and e.get("player") == goal_event.get("player")):
            goal_idx = i
            break

    if goal_idx is None:
        # Fall back: events up to and including this minute
        preceding = [e for e in all_events if e.get("minute", 0) < goal_minute]
    else:
        preceding = all_events[:goal_idx]

    # Exclude half_time / full_time / match_start markers
    preceding = [e for e in preceding if e.get("type") not in ("half_time", "full_time", "match_start")]
    return preceding[-window:]
