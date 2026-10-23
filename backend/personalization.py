"""
Personalization layer — stage (e) of the hackathon pipeline.

Takes a neutral match-intelligence packet and re-renders it for ONE fan profile
so the same underlying intelligence reaches a data-hungry analyst and a casual
fan as two genuinely different experiences:

  • mode          analyst | casual | commentary   (depth + tone)
  • favorite_club  bias framing toward this club's perspective
  • focus_player   player-focused mode: foreground this player's involvement
  • language       output language (English default)
"""
from __future__ import annotations
from backend.ai_client import chat
import backend.mcp_tools as mcp_tools

MODES = {
    "analyst": "a data-driven performance analyst. Be precise and quantitative. "
               "Reference concrete metrics (momentum, pressure index, possession, shots) and tactical cause-and-effect.",
    "casual":  "an enthusiastic mate watching with a fan. Be warm, simple and fun. "
               "No jargon or raw numbers — explain what it means for the people watching.",
    "commentary": "a live broadcast commentator. Be vivid and in-the-moment, one flowing beat of drama.",
}


def _focus_player_line(focus_player: str | None) -> str:
    if not focus_player:
        return ""
    perf = mcp_tools.compute_player_performance(focus_player)
    p = perf.get("player")
    if not p:
        return f"\nThe viewer is following {focus_player}, who has not been directly involved yet — note that."
    return (f"\nPLAYER-FOCUS MODE — centre the story on {focus_player} ({p.get('team')}): "
            f"{p.get('actions')} actions, {p.get('goals')} goals, {p.get('shots')} shots, "
            f"{p.get('tackles')} tackles, {p.get('passes')} passes so far.")


def personalize(packet: dict, profile: dict) -> dict:
    """Re-render a neutral intelligence packet for a specific fan profile."""
    profile = profile or {}
    mode = (profile.get("mode") or "casual").lower()
    persona = MODES.get(mode, MODES["casual"])
    club = profile.get("favorite_club") or ""
    focus_player = profile.get("focus_player") or ""
    language = profile.get("language") or "English"

    state = packet.get("match_state", {})
    metrics = packet.get("metrics", {})
    tactical = packet.get("tactical", {})
    why = packet.get("explain", {}).get("why_it_matters", "")

    club_line = (f"\nThe viewer supports {club} — frame insights from their perspective "
                 f"(what it means for {club}), but stay factually accurate.") if club else ""

    prompt = f"""You are {persona}

Produce a SHORT personalized match update for this viewer. 2-3 sentences for casual/commentary,
up to 4 crisp sentences for analyst. Make it feel made for THIS viewer.{club_line}{_focus_player_line(focus_player)}

MATCH: {state.get('home_team','Home')} {state.get('score',{}).get('home',0)}–{state.get('score',{}).get('away',0)} {state.get('away_team','Away')} | {state.get('minute',0)}'
METRICS: momentum {metrics.get('momentum',0)} (toward {metrics.get('momentum_side','balanced')}), rhythm {metrics.get('rhythm','')}, pressure {metrics.get('pressure_index',0)}/100, tempo {metrics.get('tempo_events_per_min',0)}/min
TACTICAL: {tactical.get('headline','')} — key battle: {tactical.get('key_battle','')}
WHY THE LAST MOMENT MATTERS: {why}

Write ONLY the personalized update, in {language}:"""

    try:
        text = chat(prompt, max_tokens=220, temperature=0.8)
    except Exception:
        side = metrics.get("momentum_side", "both sides")
        text = (f"{state.get('home_team','Home')} {state.get('score',{}).get('home',0)}–"
                f"{state.get('score',{}).get('away',0)} {state.get('away_team','Away')} at {state.get('minute',0)}'. "
                f"Momentum is with {side} and the game is in a {metrics.get('rhythm','contested')} phase.")

    return {
        "mode": mode,
        "language": language,
        "favorite_club": club,
        "focus_player": focus_player,
        "headline": tactical.get("headline", "Live match intelligence"),
        "text": text,
    }
