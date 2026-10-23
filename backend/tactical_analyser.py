import json
from backend.ai_client import chat

def _summarise(events: list, n: int = 20) -> str:
    recent = events[-n:]
    return "\n".join([
        f"  {e['minute']}' [{e['type'].upper()}] {e.get('team','')} — {e.get('player','')} — {e.get('description','')}"
        for e in recent
    ])

def analyse_tactical_moment(events: list, match_state: dict, focus_event: dict | None = None) -> dict:
    focus = f"\nFocus: {focus_event['minute']}' {focus_event.get('type','')} — {focus_event.get('description','')}" if focus_event else ""

    prompt = f"""You are a tactical analyst providing real-time analysis for a broadcast studio.{focus}

Match: {match_state['home_team']} vs {match_state['away_team']}
Score: {match_state['home_team']} {match_state['score']['home']} - {match_state['score']['away']} {match_state['away_team']}
Minute: {match_state['minute']}' | Possession: {match_state['home_team']} {match_state['possession']['home']}% / {match_state['away_team']} {match_state['possession']['away']}%

Recent events:
{_summarise(events)}

Return ONLY valid JSON:
{{
  "headline": "One punchy tactical headline (max 10 words)",
  "home_pattern": "2 sentences on {match_state['home_team']}'s tactical approach",
  "away_pattern": "2 sentences on {match_state['away_team']}'s tactical approach",
  "key_battle": "The key positional battle deciding this game",
  "prediction": "One sentence prediction for the rest of the match",
  "formation_home": "e.g. 4-3-3",
  "formation_away": "e.g. 4-2-3-1"
}}"""

    try:
        text = chat(prompt, max_tokens=350, temperature=0.65, json_mode=True)
    except Exception:
        home = match_state.get("home_team", "Home")
        away = match_state.get("away_team", "Away")
        poss = match_state.get("possession", {})
        return {
            "headline": f"{home} vs {away} — tactical battle in the Premier League",
            "home_pattern": (f"{home} are looking to control possession with {poss.get('home', 50)}% of the ball. "
                             f"They will look to exploit wide areas and transition quickly when they win the ball back."),
            "away_pattern": (f"{away} are working hard out of possession. "
                             f"Their defensive shape has been tested and they will need to find a way to create more in attack."),
            "key_battle": "The midfield battle is proving central to this contest — whichever side wins that zone will dictate the tempo.",
            "prediction": "This match remains in the balance and could be decided by a moment of individual quality.",
            "formation_home": "4-3-3",
            "formation_away": "4-4-2",
        }
    try:
        return json.loads(text)
    except Exception:
        return {"headline": text, "error": "Could not parse structured response"}

def explain_key_moment(event: dict, context_events: list, match_state: dict) -> str:
    prompt = f"""You are a tactical football expert. Explain WHY this moment is tactically significant in 3-4 sentences for a studio broadcast panel.

Key moment: {event['minute']}' — {event.get('type','')} | {event.get('player','')} ({event.get('team','')})
Description: {event.get('description','')}

Recent context:
{_summarise(context_events, n=10)}"""
    try:
        return chat(prompt, max_tokens=200, temperature=0.7)
    except Exception:
        etype = event.get("type", "")
        player = event.get("player", "")
        minute = event.get("minute", 0)
        if etype == "goal":
            return (f"The goal at {minute}' shifts the tactical dynamic completely. "
                    f"The trailing side must now open up and take more risks, which creates space for the opposition to exploit on the counter.")
        if etype == "yellow_card":
            return (f"{player}'s booking at {minute}' has tactical implications beyond the card itself. "
                    f"The player must now adjust their game, potentially leaving their side exposed in that area of the pitch.")
        return (f"This moment at {minute}' represents a significant shift in the match's tactical balance. "
                f"Both managers will be reassessing their approach in response to this development.")
