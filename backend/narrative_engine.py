from backend.ai_client import chat


def generate_ambient_commentary(state: dict) -> str:
    """
    Generate a short 'flow of play' commentary to bridge between key events.
    Called every ~10 game minutes during replay to keep the commentary feed alive.
    """
    home  = state.get("home_team", "Home")
    away  = state.get("away_team", "Away")
    score = state.get("score", {})
    minute = state.get("minute", 0)
    poss  = state.get("possession", {})
    shots = state.get("shots", {})

    dominant = home if poss.get("home", 50) >= 50 else away
    trailing_side = None
    h, a = score.get("home", 0), score.get("away", 0)
    if h != a:
        trailing_side = away if h > a else home

    prompt = f"""You are a BBC Sport Premier League radio commentator giving a brief match update between key incidents.
Write exactly 1-2 sentences describing the current flow of play. Be atmospheric, varied, and specific to the teams.
Do NOT repeat the exact score — it will be shown on screen. Focus on who is dominant, the tempo, or the tactical picture.

Match: {home} {h}–{a} {away} | {minute}'
Possession: {home} {poss.get('home', 50)}% / {away} {poss.get('away', 50)}%
Shots: {home} {shots.get('home', 0)} / {away} {shots.get('away', 0)}
Currently dominant: {dominant}
{f"Under pressure: {trailing_side}" if trailing_side else "Match level — both sides looking for the breakthrough"}

Match update (1-2 sentences only):"""

    try:
        return chat(prompt, max_tokens=80, temperature=0.88)
    except Exception:
        ph = poss.get("home", 50)
        if ph > 55:
            return f"{home} are controlling possession here, looking to work an opening as {away} sit deep."
        elif ph < 45:
            return f"{away} have had the better of this spell, with {home} pinned back in their own half."
        else:
            return f"End-to-end play here — both sides pressing for the next breakthrough."


def generate_live_commentary(event: dict, match_state: dict) -> str:
    score = event.get("score", {})
    prompt = f"""You are a passionate BBC Sport Premier League commentator.
Generate compelling live commentary for this match event in 1-2 sentences. Be concise, energetic, and atmospheric.

Match: {match_state['home_team']} vs {match_state['away_team']}
Score: {match_state['home_team']} {score.get('home',0)} - {score.get('away',0)} {match_state['away_team']}
Minute: {event['minute']}'
Event: {event['type']} | Player: {event.get('player','')} ({event.get('team','')})
Description: {event.get('description','')}

Commentary:"""
    try:
        return chat(prompt, max_tokens=120, temperature=0.85)
    except Exception:
        etype = event.get("type", "")
        player = event.get("player", "")
        minute = event.get("minute", 0)
        if etype in ("goal", "own_goal"):
            return f"{minute}' — {player} finds the net! The crowd erupts as the scoreline changes in this Premier League encounter."
        if etype == "yellow_card":
            return f"{minute}' — The referee reaches for the yellow card. {player} will need to be careful for the remainder of this match."
        if etype == "red_card":
            return f"{minute}' — Straight red! {player} is dismissed and their side must now play with ten men."
        return f"{minute}' — {event.get('description', 'A key moment in this Premier League clash.')} The stadium is buzzing."

def generate_half_time_analysis(events: list, match_state: dict) -> str:
    score = match_state.get("score", {})
    goals = [e for e in events if e.get("type") == "goal"]
    goal_summary = "\n".join([f"- {g['minute']}' {g['player']} ({g['team']})" for g in goals]) or "No goals"
    stats = events[-1].get("stats", {}) if events else {}

    prompt = f"""You are a Sky Sports tactical analyst giving a half-time summary.
Write a punchy, insightful half-time analysis in 3-4 sentences covering: key moments, tactical patterns, and what each team must do in the second half.

{match_state['home_team']} {score.get('home',0)} - {score.get('away',0)} {match_state['away_team']}
Goals: {goal_summary}
Possession: {match_state['home_team']} {stats.get('possession',{}).get('home',50)}% / {match_state['away_team']} {stats.get('possession',{}).get('away',50)}%
Shots: {match_state['home_team']} {stats.get('shots',{}).get('home',0)} / {match_state['away_team']} {stats.get('shots',{}).get('away',0)}

Half-time analysis:"""
    try:
        return chat(prompt, max_tokens=250, temperature=0.75)
    except Exception:
        home = match_state.get("home_team", "Home")
        away = match_state.get("away_team", "Away")
        h, a = score.get("home", 0), score.get("away", 0)
        poss = match_state.get("possession", {})
        if h == a:
            return (f"It's all square at half-time between {home} and {away} — {h}-{h}. "
                    f"Both sides have had their moments, with possession split {poss.get('home', 50)}/{poss.get('away', 50)}. "
                    f"The second half promises to be just as tight, with the outcome still very much in the balance. "
                    f"Tactical adjustments in the dressing room could prove the difference.")
        leader = home if h > a else away
        trailer = away if h > a else home
        ls, ts = (h, a) if h > a else (a, h)
        return (f"{leader} lead {ls}-{ts} at the break against {trailer}. "
                f"The dominant side have controlled possession at {poss.get('home' if leader == home else 'away', 50)}% "
                f"and will be pleased with how the first half unfolded. "
                f"{trailer} will need a tactical rethink if they are to find a way back into this contest in the second period. "
                f"The next goal will be crucial.")

def generate_match_recap(events: list, match_state: dict) -> str:
    score = match_state.get("score", {})
    goals = [e for e in events if e.get("type") == "goal"]
    goal_summary = "\n".join([f"- {g['minute']}' {g['player']} ({g['team']})" for g in goals]) or "No goals"
    key = [e for e in events if e["type"] in ("goal","yellow_card","red_card","penalty","var_check","half_time","full_time")]
    key_text = "\n".join([f"- {e['minute']}' [{e['type'].upper()}] {e.get('description','')}" for e in key])
    last_stats = next((e["stats"] for e in reversed(events) if "stats" in e), {})

    prompt = f"""You are a senior football journalist writing a match report for The Guardian.
Write a detailed, engaging match report in 5-6 sentences: result, key moments, tactical story, player highlights.

FINAL: {match_state['home_team']} {score.get('home',0)} - {score.get('away',0)} {match_state['away_team']} | {match_state.get('venue','')}
Goals: {goal_summary}
Key events:\n{key_text}
Possession: {match_state['home_team']} {last_stats.get('possession',{}).get('home',50)}% / {match_state['away_team']} {last_stats.get('possession',{}).get('away',50)}%
Shots: {match_state['home_team']} {last_stats.get('shots',{}).get('home',0)} / {match_state['away_team']} {last_stats.get('shots',{}).get('away',0)}
Corners: {match_state['home_team']} {last_stats.get('corners',{}).get('home',0)} / {match_state['away_team']} {last_stats.get('corners',{}).get('away',0)}

Match report:"""
    try:
        return chat(prompt, max_tokens=400, temperature=0.7)
    except Exception:
        home = match_state.get("home_team", "Home")
        away = match_state.get("away_team", "Away")
        h, a = score.get("home", 0), score.get("away", 0)
        venue = match_state.get("venue", "")
        poss = last_stats.get("possession", {})
        shots = last_stats.get("shots", {})
        corners = last_stats.get("corners", {})
        yellows = [e for e in events if e.get("type") == "yellow_card"]
        reds = [e for e in events if e.get("type") == "red_card"]

        if h == a:
            result_line = f"A hard-fought goalless draw between {home} and {away}{' at ' + venue if venue else ''} sees both sides share the spoils."
        elif h > a:
            goal_line = f"{goals[0]['minute']}' {goals[0]['player']}" if goals else "an early goal"
            result_line = f"{home} claimed all three points with a {h}-{a} victory over {away}{' at ' + venue if venue else ''}, settled by {goal_line}."
        else:
            goal_line = f"{goals[0]['minute']}' {goals[0]['player']}" if goals else "a clinical finish"
            result_line = f"{away} secured a {a}-{h} win away at {home}{' at ' + venue if venue else ''} thanks to {goal_line}."

        stats_line = (f"The statistics told an even story: {home} dominated with {poss.get('home', 50)}% possession "
                      f"and {shots.get('home', 0)} shots, while {away} mustered {shots.get('away', 0)} attempts of their own.")
        discipline = ""
        if yellows:
            names = ", ".join(e.get("player", "a player") for e in yellows[:3])
            discipline = f" Bookings for {names} added needle to a competitive encounter."
        if reds:
            discipline += f" {reds[0].get('player', 'A player')} was sent off, reducing the side to ten men."

        return result_line + " " + stats_line + discipline

def generate_social_snippet(event: dict) -> str:
    prompt = f"""Write a punchy, engaging tweet (max 240 chars) for this Premier League moment. Use 1-2 emojis max.

Event: {event.get('type','')} — {event.get('description','')} | Minute: {event['minute']}'

Tweet:"""
    try:
        return chat(prompt, max_tokens=80, temperature=0.9)
    except Exception:
        etype = event.get("type", "")
        player = event.get("player", "")
        minute = event.get("minute", 0)
        score = event.get("score", {})
        if etype in ("goal", "own_goal"):
            return f"⚽ GOAL! {player} scores in the {minute}th minute! {score.get('home',0)}-{score.get('away',0)} #PremierLeague"
        if etype == "yellow_card":
            return f"🟨 {player} is booked in the {minute}th minute. Walking a tightrope now. #PremierLeague"
        if etype == "red_card":
            return f"🟥 RED CARD! {player} is sent off in the {minute}th minute! Down to 10 men. #PremierLeague"
        return f"⚡ Key moment at {minute}' — {event.get('description', 'drama in the Premier League')}! #PremierLeague"
