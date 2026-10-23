"""
Goal projection & near-miss coaching.

Two explainability features over the live synthetic event stream:

  • Projection  — an expected-goals (xG) read of the match, a projected final
                  scoreline, win probabilities and the chance of a goal in the
                  next 15 minutes (all deterministic, broadcast-ready).
  • Near-miss   — for chances that were NOT converted (saved, off target, missed
                  penalty), an AI "better angle" a shooting coach would suggest.
"""
from __future__ import annotations
import math
from backend.ai_client import chat

# crude pre-shot chance quality by synthetic event type
XG_BY_TYPE = {
    "goal": 0.40, "penalty": 0.79, "penalty_missed": 0.79,
    "save": 0.33, "shot_off_target": 0.05, "header": 0.10,
}
_NEAR_MISS_TYPES = ("save", "shot_off_target", "penalty_missed")


def _sim():
    import backend.match_simulator as simulator
    return simulator


def compute_projection() -> dict:
    """Deterministic xG projection, projected score, win % and next-goal odds."""
    sim = _sim()
    state = sim.get_state()
    events = list(sim.match_state.get("events", []))
    minute = max(1, state.get("minute", 1))
    home, away = state.get("home_team", "Home"), state.get("away_team", "Away")

    xg = {"home": 0.0, "away": 0.0}
    big = {"home": 0, "away": 0}
    for e in events:
        q = XG_BY_TYPE.get(e.get("type", ""))
        if not q:
            continue
        side = "home" if e.get("team") == home else "away"
        xg[side] += q
        if q >= 0.30:
            big[side] += 1

    score = state.get("score", {"home": 0, "away": 0})
    shots = state.get("shots", {"home": 0, "away": 0})

    # project the rest of the match from the current xG rate, damped (teams rarely
    # sustain an early rate) and capped so early-game numbers stay believable
    remaining = max(0, 90 - minute)
    damp = 0.55
    proj_remaining = {s: min(4.0, (xg[s] / minute) * remaining * damp) for s in ("home", "away")}
    proj_xg = {s: round(xg[s] + proj_remaining[s], 2) for s in ("home", "away")}
    proj_score = {s: min(score.get(s, 0) + 4,
                         max(score.get(s, 0), round(score.get(s, 0) + proj_remaining[s])))
                  for s in ("home", "away")}

    # win probabilities from projected xG difference (simple logistic model)
    d = proj_xg["home"] - proj_xg["away"]
    p_home_raw = 1.0 / (1.0 + math.exp(-0.9 * d))
    draw = 0.27 * math.exp(-abs(d))
    p_home = (1 - draw) * p_home_raw
    p_away = (1 - draw) * (1 - p_home_raw)
    win_prob = {"home": round(100 * p_home), "draw": round(100 * draw), "away": round(100 * p_away)}

    # chance of a goal in the next 15 minutes
    shots_total = shots.get("home", 0) + shots.get("away", 0)
    xg_total = xg["home"] + xg["away"]
    avg_xg = (xg_total / shots_total) if shots_total else 0.1
    exp_shots_15 = (shots_total / minute) * 15
    exp_goals_15 = exp_shots_15 * avg_xg
    next_goal_pct = round(100 * (1 - math.exp(-exp_goals_15)))

    return {
        "minute": minute, "home_team": home, "away_team": away,
        "score": score, "shots": shots,
        "xg": {s: round(xg[s], 2) for s in ("home", "away")},
        "big_chances": big,
        "projected_xg_full": proj_xg,
        "projected_score": proj_score,
        "win_prob": win_prob,
        "next_goal_15min_pct": next_goal_pct,
    }


def _fallback_angle(ev: dict) -> str:
    t = ev.get("type")
    if t == "save":
        return "Aim for the far post across the keeper rather than straight at them, or take a touch to open the shooting angle."
    if t == "shot_off_target":
        return "Keep it down and on target — a side-foot placement into the corner beats blazing for power from there."
    if t == "penalty_missed":
        return "Pick a side early and commit; a confident low shot inside the post is far harder to save than a change of mind."
    return "A composed first touch to set the body before shooting would have improved the chance."


def near_miss_insights(limit: int = 3) -> list[dict]:
    """For the most recent unconverted big chances, suggest a better option."""
    sim = _sim()
    events = list(sim.match_state.get("events", []))
    misses = [e for e in events if e.get("type") in _NEAR_MISS_TYPES]
    misses = misses[-limit:][::-1]  # most recent first

    out = []
    for ev in misses:
        xg_est = XG_BY_TYPE.get(ev.get("type", ""), 0.1)
        prompt = (
            "You are a Premier League shooting coach reviewing a chance that was NOT scored. "
            "In ONE concise sentence (max 28 words), suggest a better option the attacker could "
            "have taken — angle, placement, first touch, or a pass. Be specific and constructive.\n\n"
            f"Chance: {ev.get('minute')}' {ev.get('player')} ({ev.get('team')}) — "
            f"{ev.get('type')} — {ev.get('description','')}. Estimated chance quality xG={xg_est:.2f}."
        )
        try:
            angle = chat(prompt, max_tokens=70, temperature=0.7)
        except Exception:
            angle = _fallback_angle(ev)
        out.append({
            "minute": ev.get("minute"), "player": ev.get("player"),
            "team": ev.get("team"), "type": ev.get("type"),
            "chance_xg": round(xg_est, 2),
            "what_happened": ev.get("description", ""),
            "better_angle": angle,
        })
    return out


_SHOT_TYPES = ("goal", "save", "shot_off_target", "penalty", "penalty_missed")


def _buildup_for_shot(events: list, shot: dict) -> list[dict]:
    """Deterministic build-up sequence (same zone format as the Goals tab) ending
    at the shot — so the projection pitch renders identically to the goal diagram."""
    import backend.goal_analysis as ga
    preceding = ga.get_preceding_events(events, shot, window=4)
    names = [e.get("player") for e in preceding if e.get("player")]
    shooter = shot.get("player") or "Shooter"
    scored = shot.get("type") == "goal"
    is_pen = shot.get("type") in ("penalty", "penalty_missed") or shot.get("is_penalty")
    seed = int(shot.get("minute") or 0)
    wing = "A-L" if seed % 2 == 0 else "A-R"
    final_action = "goal" if scored else "shot"

    if is_pen:
        seq = [
            {"player": names[-1] if names else "Won penalty", "action": "dribble",
             "from_zone": "M-C", "to_zone": "A-C", "label": "Penalty won"},
            {"player": shooter, "action": final_action, "from_zone": "A-C", "to_zone": "GOAL",
             "label": "Penalty scored" if scored else "Penalty saved"},
        ]
    else:
        p2 = names[-2] if len(names) >= 2 else (names[-1] if names else "Build-up")
        p1 = names[-1] if names else "Build-up"
        seq = [
            {"player": p2, "action": "pass", "from_zone": "M-C", "to_zone": wing, "label": "Progress play"},
            {"player": p1, "action": "dribble" if seed % 3 == 0 else "cross",
             "from_zone": wing, "to_zone": "A-C", "label": "Final ball in"},
            {"player": shooter, "action": final_action, "from_zone": "A-C", "to_zone": "GOAL",
             "label": "Clinical finish" if scored else "Shot — chance missed"},
        ]
    for i, s in enumerate(seq, 1):
        s["step"] = i
    return seq


def shot_map(limit: int = 4) -> list[dict]:
    """Recent notable shots (goals + misses) for the shot-map SVG. Misses get an
    AI 'better angle'; goals carry their trajectory outcome."""
    sim = _sim()
    events = list(sim.match_state.get("events", []))
    shots = [e for e in events if e.get("type") in _SHOT_TYPES][-limit:][::-1]

    out = []
    for e in shots:
        t = e.get("type")
        scored = (t == "goal")
        is_pen = bool(e.get("is_penalty")) or t in ("penalty", "penalty_missed")
        entry = {
            "minute": e.get("minute"), "player": e.get("player"),
            "team": e.get("team"), "type": t,
            "xg": round(XG_BY_TYPE.get(t, 0.1), 2),
            "scored": scored, "is_penalty": is_pen,
            "what_happened": e.get("description", ""),
            "buildup_sequence": _buildup_for_shot(events, e),
        }
        if not scored:
            # a better-angle arrow on the same pitch (to a goal corner)
            entry["better"] = {"from_zone": "A-C",
                               "corner": "top" if (e.get("minute") or 0) % 2 == 0 else "bottom",
                               "label": "Better angle"}
            xg_est = XG_BY_TYPE.get(t, 0.1)
            prompt = (
                "You are a Premier League shooting coach reviewing a chance that was NOT scored. "
                "In ONE concise sentence (max 28 words), suggest a better option — angle, placement, "
                "first touch, or a pass. Be specific and constructive.\n\n"
                f"Chance: {e.get('minute')}' {e.get('player')} ({e.get('team')}) — {t} — "
                f"{e.get('description','')}. Estimated chance quality xG={xg_est:.2f}."
            )
            try:
                entry["better_angle"] = chat(prompt, max_tokens=70, temperature=0.7)
            except Exception:
                entry["better_angle"] = _fallback_angle(e)
        out.append(entry)
    return out


def project(limit: int = 4) -> dict:
    """Full projection packet = deterministic projection + shot map (goals + AI near-miss coaching)."""
    data = compute_projection()
    data["shot_map"] = shot_map(limit)
    return data
