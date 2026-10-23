import json
import os
import queue
import random
import threading
import time

with open(os.path.join(os.path.dirname(__file__), "..", "data", "players.json")) as f:
    PLAYERS = json.load(f)

HOME_TEAM = "Manchester City"
AWAY_TEAM = "Arsenal"
MATCH_ID = "PL2025-MCY-ARS-001"

EVENT_WEIGHTS = {
    "pass": 40, "shot": 5, "foul": 10, "corner": 6,
    "free_kick": 6, "offside": 3, "tackle": 8, "header": 4,
    "save": 4, "clearance": 5, "dribble": 5,
    "yellow_card": 2, "var_check": 1, "penalty": 1,
}

SHOT_TO_GOAL_PROB = 0.18
PENALTY_TO_GOAL_PROB = 0.75

match_state = {
    "match_id": MATCH_ID,
    "home_team": HOME_TEAM, "away_team": AWAY_TEAM,
    "venue": "Etihad Stadium, Manchester",
    "competition": "Premier League", "date": "2025-10-11",
    "score": {"home": 0, "away": 0},
    "minute": 0, "half": 1,
    "running": False, "finished": False,
    "events": [],
    "possession": {"home": 50, "away": 50},
    "shots": {"home": 0, "away": 0},
    "shots_on_target": {"home": 0, "away": 0},
    "fouls": {"home": 0, "away": 0},
    "yellow_cards": {"home": 0, "away": 0},
    "corners": {"home": 0, "away": 0},
}

clients: list[queue.Queue] = []
clients_lock = threading.Lock()

def _reset_state():
    match_state.update({
        # restore the simulator fixture — a prior live replay may have overwritten these
        "match_id": MATCH_ID, "home_team": HOME_TEAM, "away_team": AWAY_TEAM,
        "venue": "Etihad Stadium, Manchester", "competition": "Premier League",
        "score": {"home": 0, "away": 0},
        "minute": 0, "half": 1,
        "running": False, "finished": False,
        "events": [],
        "possession": {"home": 50, "away": 50},
        "shots": {"home": 0, "away": 0},
        "shots_on_target": {"home": 0, "away": 0},
        "fouls": {"home": 0, "away": 0},
        "yellow_cards": {"home": 0, "away": 0},
        "corners": {"home": 0, "away": 0},
    })

def _pick_team() -> str:
    return HOME_TEAM if random.randint(1, 100) <= match_state["possession"]["home"] else AWAY_TEAM

def _pick_player(team: str, exclude_gk: bool = True) -> str:
    pool = [p for p in PLAYERS[team] if not exclude_gk or p["position"] != "GK"]
    return random.choice(pool)["name"]

def _pick_gk(team: str) -> str:
    gks = [p for p in PLAYERS[team] if p["position"] == "GK"]
    return gks[0]["name"] if gks else "Goalkeeper"

def _side(team: str) -> str:
    return "home" if team == HOME_TEAM else "away"

def _opp(team: str) -> str:
    return AWAY_TEAM if team == HOME_TEAM else HOME_TEAM

def _update_possession():
    shift = random.randint(-3, 3)
    home = max(30, min(70, match_state["possession"]["home"] + shift))
    match_state["possession"] = {"home": home, "away": 100 - home}

def _generate_event(minute: int) -> dict:
    _update_possession()
    team = _pick_team()
    opp = _opp(team)
    side = _side(team)

    event_type = random.choices(
        list(EVENT_WEIGHTS.keys()), weights=list(EVENT_WEIGHTS.values()), k=1
    )[0]

    event = {
        "match_id": MATCH_ID, "minute": minute,
        "type": event_type, "team": team,
        "player": _pick_player(team),
        "description": "",
        "score": dict(match_state["score"]),
        "possession": dict(match_state["possession"]),
    }

    if event_type in ("shot", "penalty"):
        match_state["shots"][side] += 1
        is_penalty = event_type == "penalty"
        goal_prob = PENALTY_TO_GOAL_PROB if is_penalty else SHOT_TO_GOAL_PROB
        is_goal = random.random() < goal_prob

        if is_goal:
            match_state["score"][side] += 1
            match_state["shots_on_target"][side] += 1
            event["type"] = "goal"
            event["is_goal"] = True
            if is_penalty:
                event["is_penalty"] = True
                event["description"] = f"PENALTY GOAL! {event['player']} converts from the spot. {HOME_TEAM} {match_state['score']['home']} - {match_state['score']['away']} {AWAY_TEAM}"
            else:
                event["description"] = f"{event['player']} scores! {HOME_TEAM} {match_state['score']['home']} - {match_state['score']['away']} {AWAY_TEAM}"
            event["score"] = dict(match_state["score"])
        elif is_penalty:
            event["type"] = "penalty_missed"
            event["description"] = f"Penalty MISSED by {event['player']}!"
        else:
            is_on_target = random.random() < 0.45
            if is_on_target:
                match_state["shots_on_target"][side] += 1
                event["type"] = "save"
                event["description"] = f"{event['player']} fires on target — great save by {_pick_gk(opp)}"
            else:
                event["type"] = "shot_off_target"
                event["description"] = f"{event['player']} shoots — goes wide of the post"

    elif event_type == "foul":
        match_state["fouls"][side] += 1
        fouled = _pick_player(opp)
        event["description"] = f"{event['player']} brings down {fouled} — foul given"

    elif event_type == "yellow_card":
        match_state["fouls"][side] += 1
        match_state["yellow_cards"][side] += 1
        event["description"] = f"YELLOW CARD shown to {event['player']}"

    elif event_type == "corner":
        match_state["corners"][side] += 1
        event["description"] = f"Corner awarded to {team}. {event['player']} to deliver."

    elif event_type == "free_kick":
        event["description"] = f"Free kick to {team}. {event['player']} lines it up."

    elif event_type == "offside":
        event["description"] = f"Offside flag — {event['player']} caught in an advanced position"

    elif event_type == "var_check":
        event["description"] = f"VAR check underway — reviewing the incident involving {event['player']}"

    elif event_type == "tackle":
        event["description"] = f"Great tackle by {event['player']} — wins possession back for {team}"

    elif event_type == "header":
        event["description"] = f"{event['player']} wins the aerial duel — clears the danger for {team}"

    elif event_type == "dribble":
        event["description"] = f"{event['player']} drives forward with a mazy run, taking on defenders"

    elif event_type == "clearance":
        event["description"] = f"Last-ditch clearance from {event['player']} — {team} breathe a sigh of relief"

    else:
        event["description"] = f"{event['player']} plays a composed pass, maintaining {team}'s possession"

    event["stats"] = {
        "shots": dict(match_state["shots"]),
        "shots_on_target": dict(match_state["shots_on_target"]),
        "fouls": dict(match_state["fouls"]),
        "yellow_cards": dict(match_state["yellow_cards"]),
        "corners": dict(match_state["corners"]),
        "possession": dict(match_state["possession"]),
    }
    match_state["events"].append(event)
    return event

def broadcast(event: dict):
    with clients_lock:
        dead = []
        for q in clients:
            try:
                q.put_nowait(event)
            except Exception:
                dead.append(q)
        for q in dead:
            clients.remove(q)

def run_simulation(speed: float = 1.5):
    _reset_state()
    match_state["running"] = True

    broadcast({"type": "match_start", "match_id": MATCH_ID,
               "home_team": HOME_TEAM, "away_team": AWAY_TEAM,
               "venue": match_state["venue"], "minute": 0,
               "score": {"home": 0, "away": 0}})

    for minute in range(1, 92):
        if not match_state["running"]:
            break

        match_state["minute"] = minute

        if minute == 45:
            match_state["half"] = 2
            ht_event = {
                "match_id": MATCH_ID, "minute": 45, "type": "half_time",
                "team": None, "player": None,
                "description": f"HALF TIME — {HOME_TEAM} {match_state['score']['home']} - {match_state['score']['away']} {AWAY_TEAM}",
                "score": dict(match_state["score"]),
                "stats": {k: dict(v) if isinstance(v, dict) else v for k, v in {
                    "shots": match_state["shots"],
                    "shots_on_target": match_state["shots_on_target"],
                    "possession": match_state["possession"],
                    "fouls": match_state["fouls"],
                    "corners": match_state["corners"],
                }.items()}
            }
            match_state["events"].append(ht_event)
            broadcast(ht_event)
            threading.Thread(target=_key_moment_task, args=(ht_event,), daemon=True).start()
            time.sleep(speed * 2)
            continue

        if minute == 91:
            ft_event = {
                "match_id": MATCH_ID, "minute": 90, "type": "full_time",
                "team": None, "player": None,
                "description": f"FULL TIME — {HOME_TEAM} {match_state['score']['home']} - {match_state['score']['away']} {AWAY_TEAM}",
                "score": dict(match_state["score"]),
                "stats": {k: dict(v) if isinstance(v, dict) else v for k, v in {
                    "shots": match_state["shots"],
                    "shots_on_target": match_state["shots_on_target"],
                    "possession": match_state["possession"],
                    "fouls": match_state["fouls"],
                    "corners": match_state["corners"],
                }.items()}
            }
            match_state["events"].append(ft_event)
            match_state["finished"] = True
            match_state["running"] = False
            broadcast(ft_event)
            threading.Thread(target=_key_moment_task, args=(ft_event,), daemon=True).start()
            break

        num_events = random.randint(1, 3)
        for _ in range(num_events):
            event = _generate_event(minute)
            broadcast(event)

            # Spawn AI commentary + key moment insight in background for key events
            if event.get("type") in ("goal", "yellow_card", "red_card", "penalty",
                                      "var_check", "half_time", "full_time", "save"):
                threading.Thread(target=_ai_commentary_task, args=(event,), daemon=True).start()
                threading.Thread(target=_key_moment_task,    args=(event,), daemon=True).start()

            time.sleep(random.uniform(0.1, 0.3))

        time.sleep(speed)

    match_state["running"] = False

def _ai_commentary_task(event: dict):
    try:
        import backend.narrative_engine as narrative
        state = get_state()
        text = narrative.generate_live_commentary(event, state)
        broadcast({"type": "ai_commentary", "minute": event.get("minute"),
                   "trigger_event_type": event.get("type"), "text": text})

        if event.get("type") == "goal":
            tweet = narrative.generate_social_snippet(event)
            broadcast({"type": "social_snippet", "minute": event.get("minute"), "text": tweet})
            # Trigger build-up analysis in a separate thread so commentary isn't delayed
            threading.Thread(target=_goal_buildup_task, args=(event,), daemon=True).start()
    except Exception as e:
        print(f"[ai_commentary_task] {e}")

def _key_moment_task(event: dict):
    try:
        import backend.key_moments as km
        state = get_state()
        recent = match_state["events"][-10:]
        insight = km.generate_moment_insight(event, state, recent)
        record  = km.build_moment_record(event, insight)
        broadcast(record)
    except Exception as e:
        print(f"[key_moment_task] {e}")

def _goal_buildup_task(goal_event: dict):
    try:
        import backend.goal_analysis as ga
        state = get_state()
        preceding = ga.get_preceding_events(match_state["events"], goal_event)
        result = ga.analyse_goal_buildup(goal_event, preceding, state)
        broadcast({"type": "goal_buildup", "minute": goal_event.get("minute"), "data": result})
    except Exception as e:
        print(f"[goal_buildup_task] {e}")

def stop_simulation():
    match_state["running"] = False

def get_state() -> dict:
    return {k: v for k, v in match_state.items() if k != "events"}

def get_recent_events(n: int = 20) -> list:
    return match_state["events"][-n:]
