"""
API-Football integration.

Two modes:
  replay  — fetch all events from a completed fixture and replay at simulation speed
  live    — poll the API every 60 s for new events during an ongoing match

All events are normalised to the same dict schema used by match_simulator and
fed into the same broadcast() pipeline so every AI feature works unchanged.
"""

import os
import json
import time
import threading
import urllib.request
import urllib.error
from dotenv import load_dotenv

load_dotenv()

import backend.match_simulator as simulator

# ── Config ────────────────────────────────────────────────────────
_API_KEY         = os.getenv("APIFOOTBALL_API_KEY", "")
_BASE_URL        = "https://v3.football.api-sports.io"
_PL_LEAGUE_ID    = 39
# Free plan covers 2022–2024. Raise APIFOOTBALL_MAX_SEASON in .env after upgrading.
_MAX_SEASON      = int(os.getenv("APIFOOTBALL_MAX_SEASON", "2024"))

def _get_season() -> int:
    import datetime
    today = datetime.date.today()
    current = today.year if today.month >= 8 else today.year - 1
    return min(current, _MAX_SEASON)

_live_thread: threading.Thread | None = None
_stop_flag = threading.Event()


# ── HTTP helper ───────────────────────────────────────────────────

def _get(path: str, params: dict) -> dict:
    """Make a GET request to the API-Football v3 API."""
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{_BASE_URL}{path}?{qs}"
    req = urllib.request.Request(url, headers={
        "x-apisports-key": _API_KEY,
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())


# ── Fixture discovery ─────────────────────────────────────────────

def get_live_fixtures() -> list[dict]:
    """Return all currently live Premier League fixtures."""
    data = _get("/fixtures", {"live": "all", "league": _PL_LEAGUE_ID})
    return _format_fixture_list(data.get("response", []))


_SEASON_WINDOWS = {
    2024: ("2024-08-01", "2025-05-31"),
    2023: ("2023-08-01", "2024-05-31"),
    2022: ("2022-08-01", "2023-05-31"),
}

def get_recent_fixtures(count: int = 10) -> list[dict]:
    """Return the last N completed PL fixtures using date-range queries (free-plan compatible)."""
    season = _get_season()
    for s in (season, season - 1, season - 2):
        from_date, to_date = _SEASON_WINDOWS.get(s, (f"{s}-08-01", f"{s+1}-05-31"))
        try:
            data = _get("/fixtures", {
                "league":  _PL_LEAGUE_ID,
                "season":  s,
                "from":    from_date,
                "to":      to_date,
                "status":  "FT",
            })
            errors = data.get("errors")
            if errors:
                print(f"[LiveFeed] recent fixtures season={s}: errors={errors}")
                continue
            fixtures = _format_fixture_list(data.get("response", []))
            print(f"[LiveFeed] recent fixtures season={s}: {len(fixtures)} results")
            if fixtures:
                return list(reversed(fixtures))[:count]
        except Exception as e:
            print(f"[LiveFeed] get_recent_fixtures season={s} error: {e}")
    return []


def get_upcoming_fixtures(count: int = 10) -> list[dict]:
    """Return next N scheduled PL fixtures using date-range queries (free-plan compatible)."""
    import datetime
    today = datetime.date.today().isoformat()
    season = _get_season()
    for s in (season, season - 1, season - 2):
        _, to_date = _SEASON_WINDOWS.get(s, (f"{s}-08-01", f"{s+1}-05-31"))
        if today > to_date:
            continue  # season already finished, no upcoming matches
        try:
            data = _get("/fixtures", {
                "league": _PL_LEAGUE_ID,
                "season": s,
                "from":   today,
                "to":     to_date,
            })
            errors = data.get("errors")
            if errors:
                print(f"[LiveFeed] upcoming fixtures season={s}: errors={errors}")
                continue
            fixtures = _format_fixture_list(data.get("response", []))
            print(f"[LiveFeed] upcoming fixtures season={s}: {len(fixtures)} results")
            if fixtures:
                return fixtures[:count]
        except Exception as e:
            print(f"[LiveFeed] get_upcoming_fixtures season={s} error: {e}")
    return []


def _format_fixture_list(fixtures: list) -> list[dict]:
    out = []
    for f in fixtures:
        fix = f.get("fixture", {})
        teams = f.get("teams", {})
        goals = f.get("goals", {})
        status = fix.get("status", {})
        out.append({
            "id":         fix.get("id"),
            "date":       fix.get("date", "")[:10],
            "status":     status.get("short", ""),
            "minute":     status.get("elapsed"),
            "home_team":  teams.get("home", {}).get("name", ""),
            "away_team":  teams.get("away", {}).get("name", ""),
            "home_logo":  teams.get("home", {}).get("logo", ""),
            "away_logo":  teams.get("away", {}).get("logo", ""),
            "home_score": goals.get("home"),
            "away_score": goals.get("away"),
            "venue":      fix.get("venue", {}).get("name", ""),
        })
    return out


# ── Event normalisation ───────────────────────────────────────────

_TYPE_MAP = {
    # (api type, api detail) → our type
    ("goal",  "normal goal"):   "goal",
    ("goal",  "penalty"):       "goal",
    ("goal",  "own goal"):      "own_goal",
    ("card",  "yellow card"):   "yellow_card",
    ("card",  "red card"):      "red_card",
    ("card",  "yellow red card"): "red_card",
    ("subst", ""):              "substitution",
    ("var",   ""):              "var_check",
}

def _normalise(raw: dict, home_team: str, away_team: str, match_id: str) -> dict | None:
    """Convert a raw API-Football event to our internal format. Returns None to skip."""
    api_type   = (raw.get("type") or "").lower()
    api_detail = (raw.get("detail") or "").lower()
    elapsed    = (raw.get("time") or {}).get("elapsed") or 0
    extra      = (raw.get("time") or {}).get("extra") or 0
    minute     = elapsed + extra

    team_name  = (raw.get("team") or {}).get("name", "")
    player     = (raw.get("player") or {}).get("name", "") or ""
    assist     = (raw.get("assist") or {}).get("name", "") or ""

    our_type = _TYPE_MAP.get((api_type, api_detail))
    if our_type is None:
        # fall back to prefix match for var events
        for (at, ad), ot in _TYPE_MAP.items():
            if api_type == at:
                our_type = ot
                break
    if our_type is None:
        return None  # skip unknown event types

    score = dict(simulator.match_state["score"])

    # Build description
    if our_type == "goal":
        is_pen = "penalty" in api_detail
        suffix = " (penalty)" if is_pen else ""
        desc = f"{player} scores{suffix}! {home_team} {score['home']} - {score['away']} {away_team}"
        if assist:
            desc = f"{player} scores{suffix} — assist by {assist}! {home_team} {score['home']} - {score['away']} {away_team}"
    elif our_type == "own_goal":
        desc = f"Own goal by {player}! {home_team} {score['home']} - {score['away']} {away_team}"
    elif our_type == "yellow_card":
        desc = f"YELLOW CARD shown to {player}"
    elif our_type == "red_card":
        desc = f"RED CARD — {player} is sent off!"
    elif our_type == "substitution":
        desc = f"Substitution: {player} comes on"
        if assist:
            desc = f"Substitution: {player} replaces {assist}"
    elif our_type == "var_check":
        desc = f"VAR check underway — reviewing incident involving {player}"
    else:
        desc = raw.get("comments") or f"{api_type}: {player}"

    return {
        "match_id":   match_id,
        "minute":     minute,
        "type":       our_type,
        "team":       team_name,
        "player":     player,
        "description": desc,
        "score":      score,
        "possession": dict(simulator.match_state["possession"]),
        "is_penalty": "penalty" in api_detail,
        "source":     "api_football",
    }


# ── Score sync ────────────────────────────────────────────────────

def _sync_score(fixture_id: int):
    """Fetch current score and update simulator state."""
    try:
        data = _get("/fixtures", {"id": fixture_id})
        resp = data.get("response", [])
        if not resp:
            return
        goals = resp[0].get("goals", {})
        if goals.get("home") is not None:
            simulator.match_state["score"]["home"] = goals["home"]
        if goals.get("away") is not None:
            simulator.match_state["score"]["away"] = goals["away"]
        status = resp[0].get("fixture", {}).get("status", {})
        elapsed = status.get("elapsed") or 0
        simulator.match_state["minute"] = elapsed
    except Exception as e:
        print(f"[LiveFeed] score sync error: {e}")


# ── Fixture statistics ────────────────────────────────────────────

def _fetch_and_broadcast_stats(fixture_id: int, home: str, away: str):
    """
    Fetch real match statistics from /fixtures/statistics and broadcast
    a stats_update SSE event. Called after full-time so the panel shows
    accurate totals rather than the 0s produced by normalised event replay.
    """
    try:
        data = _get("/fixtures/statistics", {"fixture": fixture_id})
        resp = data.get("response", [])
        if not resp:
            print(f"[LiveFeed] No statistics for fixture {fixture_id}")
            return

        raw = {}
        for team_data in resp:
            tname = team_data.get("team", {}).get("name", "")
            stats = {}
            for s in team_data.get("statistics", []):
                val = s.get("value") or 0
                if isinstance(val, str) and val.endswith("%"):
                    val = int(val.rstrip("%"))
                elif not isinstance(val, (int, float)):
                    val = 0
                stats[s.get("type", "")] = val
            raw[tname] = stats

        h = raw.get(home, {})
        a = raw.get(away, {})

        stats_payload = {
            "shots":           {"home": h.get("Total Shots", 0),      "away": a.get("Total Shots", 0)},
            "shots_on_target": {"home": h.get("Shots on Goal", 0),    "away": a.get("Shots on Goal", 0)},
            "fouls":           {"home": h.get("Fouls", 0),            "away": a.get("Fouls", 0)},
            "yellow_cards":    {"home": h.get("Yellow Cards", 0),     "away": a.get("Yellow Cards", 0)},
            "corners":         {"home": h.get("Corner Kicks", 0),     "away": a.get("Corner Kicks", 0)},
            "possession":      {
                "home": int(str(h.get("Ball Possession", "50%")).rstrip("%") or 50),
                "away": int(str(a.get("Ball Possession", "50%")).rstrip("%") or 50),
            },
        }

        # Mirror into server state so /api/match/state reflects real data
        for key in ("shots", "shots_on_target", "fouls", "yellow_cards", "corners", "possession"):
            simulator.match_state[key] = stats_payload[key]

        simulator.broadcast({"type": "stats_update", "stats": stats_payload})
        print(f"[LiveFeed] Stats broadcast for fixture {fixture_id}: {stats_payload}")

    except Exception as e:
        print(f"[LiveFeed] stats fetch error: {e}")


# ── Filler event templates (used between real API events during replay) ───────

_FILLER = {
    "pass": [
        "{home} work the ball patiently through midfield.",
        "{away} retain possession, probing for an opening.",
        "{home} switch play to the right flank, looking to stretch {away}.",
        "{away} recycle possession in their own half under pressure.",
        "Quick one-two from {home} in the centre circle.",
        "{away} build from the back, goalkeeper involved.",
    ],
    "corner": [
        "{home} win a corner — defender gets the first touch.",
        "Corner for {away}, swung in but cleared by {home}.",
        "{home} corner comes to nothing — {away} break quickly.",
        "Another corner for {away} as the pressure mounts.",
    ],
    "foul": [
        "Foul given against {away} — {home} free kick in midfield.",
        "Referee stops play for a {home} foul near the touchline.",
        "Tactical foul from {away} to halt {home}'s counter-attack.",
        "{home} caught in possession — {away} free kick awarded.",
        "Physical challenge from {home} — {away} have a free kick.",
    ],
    "free_kick": [
        "{home} free kick from 30 yards — goes straight into the wall.",
        "{away} take the free kick quickly but {home} are organised.",
        "Free kick for {home} on the left flank — played short.",
    ],
    "shot": [
        "{home} attempt from range — comfortable for the goalkeeper.",
        "Long-range effort from {away} — well over the crossbar.",
        "{home} drive curls wide of the far post.",
        "{away} force a corner with a powerful low shot.",
        "Speculative effort from {home} — straight at the keeper.",
    ],
    "tackle": [
        "Strong tackle from {home} wins the ball back in midfield.",
        "{away} press high and dispossess {home} in their own half.",
        "Great pressing from {home} — {away} forced long.",
        "Last-ditch challenge from {away} denies {home} a clear run.",
    ],
    "clearance": [
        "{home} clear their lines under sustained pressure from {away}.",
        "Defensive header from {away} keeps {home} at bay.",
        "{home} goalkeeper punches clear from a dangerous {away} cross.",
        "Scramble in the {home} box — eventually cleared for a corner.",
    ],
    "header": [
        "Aerial duel goes to {home} from the goal kick.",
        "{away} win the header and feed a midfielder in space.",
        "Flick-on from {home} — {away} deal with it comfortably.",
    ],
    "dribble": [
        "{home} winger drives inside — cut back to midfield.",
        "Good skill from an {away} player — wins a foul.",
        "{home} advance down the left, beat their man but lose the ball.",
    ],
    "offside": [
        "Offside flag raised against {home} — {away} free kick.",
        "{away} forward caught offside — tight call from the linesman.",
    ],
}

import random as _random

def _broadcast_filler_events(home: str, away: str, match_id: str,
                              from_min: int, to_min: int, speed: float,
                              ambient_counter: list):
    """
    Broadcast synthetic flow-of-play events to fill gaps between real API events.
    Fires one event every ~3 game minutes. Every 10 game minutes fires ambient commentary.
    ambient_counter is a one-element list so we can mutate it from a nested scope.
    """
    import backend.narrative_engine as _ne

    step = 2  # game minutes between filler events
    current = from_min + step
    sleep_per_step = min(step / speed if speed > 0 else 1.0, 1.5)  # max 1.5s real time

    while current < to_min:
        if _stop_flag.is_set():
            return

        time.sleep(sleep_per_step)

        # Drift possession gradually (±2 each step, clamped 35–65)
        ph = simulator.match_state["possession"]["home"]
        ph = max(35, min(65, ph + _random.randint(-2, 2)))
        simulator.match_state["possession"]["home"] = ph
        simulator.match_state["possession"]["away"] = 100 - ph

        etype = _random.choice(list(_FILLER.keys()))
        team  = home if _random.random() < ph / 100 else away
        desc  = _random.choice(_FILLER[etype]).format(home=home, away=away, team=team)

        filler_event = {
            "match_id":    match_id,
            "minute":      current,
            "type":        etype,
            "team":        team,
            "player":      "",
            "description": desc,
            "score":       dict(simulator.match_state["score"]),
            "possession":  dict(simulator.match_state["possession"]),
            "source":      "synthetic",
        }
        simulator.match_state["minute"] = current
        simulator.broadcast(filler_event)

        # Every 10 game minutes fire ambient bridge commentary (background, GPT-4o)
        ambient_counter[0] += step
        if ambient_counter[0] >= 10:
            ambient_counter[0] = 0
            state_snap = {
                "home_team":  home,
                "away_team":  away,
                "score":      dict(simulator.match_state["score"]),
                "minute":     current,
                "possession": dict(simulator.match_state["possession"]),
                "shots":      dict(simulator.match_state["shots"]),
            }
            threading.Thread(
                target=_ambient_commentary_task,
                args=(state_snap, match_id),
                daemon=True,
            ).start()

        current += step


def _ambient_commentary_task(state: dict, match_id: str):
    """Fire a short 'flow of play' commentary to bridge between key moments."""
    try:
        import backend.narrative_engine as _ne
        text = _ne.generate_ambient_commentary(state)
        if text:
            simulator.broadcast({
                "type":     "ai_commentary",
                "match_id": match_id,
                "minute":   state["minute"],
                "text":     text,
                "source":   "ambient",
            })
    except Exception as e:
        print(f"[LiveFeed] ambient commentary error: {e}")


# ── Replay mode ───────────────────────────────────────────────────

def start_replay(fixture_id: int, speed: float = 1.0):
    """
    Fetch all events from a completed fixture and replay them
    in real-match order, with configurable speed multiplier.
    speed=1.0 means real-time (1 second per in-game minute between events).
    speed=5.0 replays 5× faster.
    """
    global _live_thread, _stop_flag

    stop_live()  # stop any current live/replay feed

    _stop_flag = threading.Event()
    _live_thread = threading.Thread(
        target=_replay_worker,
        args=(fixture_id, speed),
        daemon=True,
    )
    _live_thread.start()
    return {"status": "replay_started", "fixture_id": fixture_id, "speed": speed}


def _replay_worker(fixture_id: int, speed: float):
    print(f"[LiveFeed] Starting replay for fixture {fixture_id}")
    try:
        # Fetch fixture info
        fix_data = _get("/fixtures", {"id": fixture_id})
        fix_resp = fix_data.get("response", [])
        if not fix_resp:
            print("[LiveFeed] No fixture data found")
            return

        fix   = fix_resp[0]
        teams = fix.get("teams", {})
        goals = fix.get("goals", {})
        venue = fix.get("fixture", {}).get("venue", {}).get("name", "")
        home  = teams.get("home", {}).get("name", "Manchester City")
        away  = teams.get("away", {}).get("name", "Arsenal")
        match_id = f"APIFOOTBALL-{fixture_id}"

        # Reset simulator state for this fixture
        simulator.match_state.update({
            "match_id":  match_id,
            "home_team": home,
            "away_team": away,
            "venue":     venue,
            "score":     {"home": 0, "away": 0},
            "minute":    0,
            "half":      1,
            "running":   True,
            "finished":  False,
            "events":    [],
            "possession": {"home": 50, "away": 50},
            "shots":     {"home": 0, "away": 0},
            "shots_on_target": {"home": 0, "away": 0},
            "fouls":     {"home": 0, "away": 0},
            "yellow_cards": {"home": 0, "away": 0},
            "corners":   {"home": 0, "away": 0},
        })

        home_logo = teams.get("home", {}).get("logo", "")
        away_logo = teams.get("away", {}).get("logo", "")

        # Broadcast match start
        simulator.broadcast({
            "type": "match_start", "match_id": match_id,
            "home_team": home, "away_team": away, "venue": venue, "minute": 0,
            "score": {"home": 0, "away": 0},
            "home_logo": home_logo, "away_logo": away_logo,
        })

        # Fetch events
        ev_data = _get("/fixtures/events", {"fixture": fixture_id})
        raw_events = ev_data.get("response", [])
        raw_events.sort(key=lambda e: (e.get("time", {}).get("elapsed") or 0))

        last_minute = 0
        _ambient_counter = [0]  # mutable counter shared with _broadcast_filler_events

        for raw in raw_events:
            if _stop_flag.is_set():
                break

            event = _normalise(raw, home, away, match_id)
            if event is None:
                continue

            minute = event["minute"]

            # Fill the gap between last real event and this one with synthetic events
            gap = minute - last_minute
            if gap > 0:
                _broadcast_filler_events(home, away, match_id,
                                         last_minute, minute, speed, _ambient_counter)

            # Update score in state before broadcasting
            if event["type"] in ("goal", "own_goal"):
                side = "home" if event["team"] == home else "away"
                if event["type"] == "own_goal":
                    side = "away" if side == "home" else "home"
                simulator.match_state["score"][side] += 1
                event["score"] = dict(simulator.match_state["score"])

            # Update match stats counters for trackable event types
            if event["type"] == "yellow_card":
                side = "home" if event["team"] == home else "away"
                simulator.match_state["yellow_cards"][side] += 1
            if event["type"] in ("goal", "own_goal"):
                side = "home" if event["team"] == home else "away"
                simulator.match_state["shots"][side] += 1
                simulator.match_state["shots_on_target"][side] += 1

            simulator.match_state["minute"] = minute
            simulator.match_state["events"].append(event)
            simulator.broadcast(event)

            # After goals and cards: push a dedicated stats_update so the browser
            # panel updates even if the event itself has no stats field.
            stat_trigger_types = {"goal", "own_goal", "yellow_card", "red_card"}
            if event["type"] in stat_trigger_types:
                _stats_now = {
                    "shots":           dict(simulator.match_state["shots"]),
                    "shots_on_target": dict(simulator.match_state["shots_on_target"]),
                    "fouls":           dict(simulator.match_state["fouls"]),
                    "yellow_cards":    dict(simulator.match_state["yellow_cards"]),
                    "corners":         dict(simulator.match_state["corners"]),
                    "possession":      dict(simulator.match_state["possession"]),
                }
                simulator.broadcast({"type": "stats_update", "stats": _stats_now})
                print(f"[LiveFeed] stats_update after {event['type']}: {_stats_now}")

            # Trigger AI commentary for key events (background thread — API call)
            key_types = {"goal", "own_goal", "yellow_card", "red_card", "var_check", "penalty", "save"}
            if event["type"] in key_types:
                threading.Thread(
                    target=simulator._ai_commentary_task,
                    args=(event,),
                    daemon=True,
                ).start()
                threading.Thread(
                    target=simulator._key_moment_task,
                    args=(event,),
                    daemon=True,
                ).start()

            # Half-time marker
            if minute == 45 and last_minute < 45:
                _ht_score = dict(simulator.match_state["score"])
                _ht_stats = {
                    "shots":           dict(simulator.match_state["shots"]),
                    "shots_on_target": dict(simulator.match_state["shots_on_target"]),
                    "fouls":           dict(simulator.match_state["fouls"]),
                    "yellow_cards":    dict(simulator.match_state["yellow_cards"]),
                    "corners":         dict(simulator.match_state["corners"]),
                    "possession":      dict(simulator.match_state["possession"]),
                }
                # Compute HT key moment insight synchronously (template, no API call)
                _ht_km = None
                try:
                    import backend.key_moments as _km
                    _ht_ev = {"type": "half_time", "minute": 45, "score": _ht_score}
                    _ht_insight = _km.generate_moment_insight(_ht_ev, simulator.get_state(), simulator.match_state["events"][-10:])
                    _ht_km = _km.build_moment_record(_ht_ev, _ht_insight)
                    _ht_km["description"] = f"HALF TIME — {home} {_ht_score['home']} - {_ht_score['away']} {away}"
                except Exception as _e:
                    print(f"[LiveFeed] HT key moment error: {_e}")

                ht = {
                    "match_id": match_id, "minute": 45, "type": "half_time",
                    "team": None, "player": None,
                    "description": f"HALF TIME — {home} {_ht_score['home']} - {_ht_score['away']} {away}",
                    "score": _ht_score,
                    "km": _ht_km,  # embedded for direct JS handling
                }
                simulator.match_state["events"].append(ht)
                simulator.broadcast(ht)
                simulator.broadcast({"type": "stats_update", "stats": _ht_stats})
                simulator.match_state["half"] = 2
                print(f"[LiveFeed] HT broadcast, km={'yes' if _ht_km else 'no'}")

            last_minute = minute

        # ── Full time ────────────────────────────────────────────────
        _ft_score = dict(simulator.match_state["score"])
        _ft_stats = {
            "shots":           dict(simulator.match_state["shots"]),
            "shots_on_target": dict(simulator.match_state["shots_on_target"]),
            "fouls":           dict(simulator.match_state["fouls"]),
            "yellow_cards":    dict(simulator.match_state["yellow_cards"]),
            "corners":         dict(simulator.match_state["corners"]),
            "possession":      dict(simulator.match_state["possession"]),
        }

        # Compute FT key moment synchronously (template, no API call)
        _ft_km = None
        try:
            import backend.key_moments as _km
            _ft_ev = {"type": "full_time", "minute": 90, "score": _ft_score}
            _ft_insight = _km.generate_moment_insight(_ft_ev, simulator.get_state(), simulator.match_state["events"][-10:])
            _ft_km = _km.build_moment_record(_ft_ev, _ft_insight)
            _ft_km["description"] = f"FULL TIME — {home} {_ft_score['home']} - {_ft_score['away']} {away}"
            print(f"[LiveFeed] FT key moment computed: {_ft_insight}")
        except Exception as _e:
            print(f"[LiveFeed] FT key moment error: {_e}")

        ft = {
            "match_id": match_id, "minute": 90, "type": "full_time",
            "team": None, "player": None,
            "description": f"FULL TIME — {home} {_ft_score['home']} - {_ft_score['away']} {away}",
            "score": _ft_score,
            "km": _ft_km,  # embedded key moment — JS handles directly in full_time handler
        }
        simulator.match_state["events"].append(ft)
        simulator.match_state["finished"] = True
        simulator.match_state["running"]  = False
        simulator.broadcast(ft)
        # Explicit stats_update after FT so panel shows final accumulated totals
        simulator.broadcast({"type": "stats_update", "stats": _ft_stats})

        # Fetch real stats (possession, fouls, corners, total shots) from API
        # and overwrite with accurate figures
        try:
            stat_data = _get("/fixtures/statistics", {"fixture": fixture_id})
            stat_resp = stat_data.get("response", [])
            if stat_resp:
                raw_by_team = {}
                for td in stat_resp:
                    tname = td.get("team", {}).get("name", "")
                    stats_map = {}
                    for s in td.get("statistics", []):
                        val = s.get("value")
                        if val is None:
                            val = 0
                        if isinstance(val, str) and val.endswith("%"):
                            val = int(val.rstrip("%") or 0)
                        elif not isinstance(val, (int, float)):
                            val = 0
                        stats_map[s.get("type", "")] = val
                    raw_by_team[tname] = stats_map

                h_stats = raw_by_team.get(home, {})
                a_stats = raw_by_team.get(away, {})

                real_stats = {
                    "shots":           {"home": h_stats.get("Total Shots", _ft_stats["shots"]["home"]),
                                        "away": a_stats.get("Total Shots", _ft_stats["shots"]["away"])},
                    "shots_on_target": {"home": h_stats.get("Shots on Goal", _ft_stats["shots_on_target"]["home"]),
                                        "away": a_stats.get("Shots on Goal", _ft_stats["shots_on_target"]["away"])},
                    "fouls":           {"home": h_stats.get("Fouls", 0),         "away": a_stats.get("Fouls", 0)},
                    "yellow_cards":    {"home": h_stats.get("Yellow Cards", _ft_stats["yellow_cards"]["home"]),
                                        "away": a_stats.get("Yellow Cards", _ft_stats["yellow_cards"]["away"])},
                    "corners":         {"home": h_stats.get("Corner Kicks", 0),  "away": a_stats.get("Corner Kicks", 0)},
                    "possession":      {"home": h_stats.get("Ball Possession", 50),
                                        "away": a_stats.get("Ball Possession", 50)},
                }
                simulator.broadcast({"type": "stats_update", "stats": real_stats})
                print(f"[LiveFeed] Real stats broadcast: poss={real_stats['possession']}, shots={real_stats['shots']}")
        except Exception as _se:
            print(f"[LiveFeed] Real stats fetch failed: {_se}")

        print(f"[LiveFeed] Replay complete for fixture {fixture_id}.")

    except Exception as e:
        print(f"[LiveFeed] Replay error: {e}")
        simulator.match_state["running"] = False


# ── Live polling mode ─────────────────────────────────────────────

def start_live(fixture_id: int, poll_interval: int = 60):
    """
    Poll API-Football every poll_interval seconds for new events
    during an ongoing live match.
    """
    global _live_thread, _stop_flag

    stop_live()

    _stop_flag = threading.Event()
    _live_thread = threading.Thread(
        target=_live_worker,
        args=(fixture_id, poll_interval),
        daemon=True,
    )
    _live_thread.start()
    return {"status": "live_started", "fixture_id": fixture_id, "poll_interval": poll_interval}


def _live_worker(fixture_id: int, poll_interval: int):
    print(f"[LiveFeed] Starting live polling for fixture {fixture_id} every {poll_interval}s")
    seen_events: set[str] = set()
    match_id = f"APIFOOTBALL-{fixture_id}"

    # Fetch fixture info once
    try:
        fix_data = _get("/fixtures", {"id": fixture_id})
        fix_resp = fix_data.get("response", [])
        if not fix_resp:
            print("[LiveFeed] No fixture found")
            return
        teams = fix_resp[0].get("teams", {})
        venue = fix_resp[0].get("fixture", {}).get("venue", {}).get("name", "")
        home  = teams.get("home", {}).get("name", "")
        away  = teams.get("away", {}).get("name", "")
    except Exception as e:
        print(f"[LiveFeed] Failed to load fixture info: {e}")
        return

    simulator.match_state.update({
        "match_id": match_id, "home_team": home, "away_team": away, "venue": venue,
        "running": True, "finished": False, "events": [],
        "score": {"home": 0, "away": 0}, "minute": 0, "half": 1,
        "possession": {"home": 50, "away": 50},
        "shots": {"home": 0, "away": 0}, "shots_on_target": {"home": 0, "away": 0},
        "fouls": {"home": 0, "away": 0}, "yellow_cards": {"home": 0, "away": 0},
        "corners": {"home": 0, "away": 0},
    })
    home_logo = teams.get("home", {}).get("logo", "")
    away_logo = teams.get("away", {}).get("logo", "")
    simulator.broadcast({
        "type": "match_start", "match_id": match_id,
        "home_team": home, "away_team": away, "venue": venue,
        "minute": 0, "score": {"home": 0, "away": 0},
        "home_logo": home_logo, "away_logo": away_logo,
    })

    while not _stop_flag.is_set():
        try:
            _sync_score(fixture_id)

            ev_data = _get("/fixtures/events", {"fixture": fixture_id})
            raw_events = ev_data.get("response", [])

            for raw in raw_events:
                # Deduplicate by (minute, type, player)
                key = f"{raw.get('time',{}).get('elapsed')}:{raw.get('type')}:{(raw.get('player') or {}).get('id')}"
                if key in seen_events:
                    continue
                seen_events.add(key)

                event = _normalise(raw, home, away, match_id)
                if event is None:
                    continue

                simulator.match_state["events"].append(event)
                simulator.broadcast(event)

                key_types = {"goal", "own_goal", "yellow_card", "red_card", "var_check", "save"}
                if event["type"] in key_types:
                    threading.Thread(
                        target=simulator._ai_commentary_task,
                        args=(event,),
                        daemon=True,
                    ).start()
                    threading.Thread(
                        target=simulator._key_moment_task,
                        args=(event,),
                        daemon=True,
                    ).start()

            # Refresh live stats every poll cycle
            threading.Thread(
                target=_fetch_and_broadcast_stats,
                args=(fixture_id, home, away),
                daemon=True,
            ).start()

            # Check if match finished
            fix_data = _get("/fixtures", {"id": fixture_id})
            fix_resp = fix_data.get("response", [])
            if fix_resp:
                status = fix_resp[0].get("fixture", {}).get("status", {}).get("short", "")
                if status == "FT":
                    ft = {
                        "match_id": match_id, "minute": 90, "type": "full_time",
                        "team": None, "player": None,
                        "description": f"FULL TIME — {home} {simulator.match_state['score']['home']} - {simulator.match_state['score']['away']} {away}",
                        "score": dict(simulator.match_state["score"]),
                    }
                    simulator.match_state["events"].append(ft)
                    simulator.match_state["finished"] = True
                    simulator.match_state["running"]  = False
                    simulator.broadcast(ft)
                    threading.Thread(target=simulator._key_moment_task, args=(ft,), daemon=True).start()
                    print("[LiveFeed] Match finished")
                    return

        except Exception as e:
            print(f"[LiveFeed] Poll error: {e}")

        _stop_flag.wait(poll_interval)

    simulator.match_state["running"] = False
    print("[LiveFeed] Live polling stopped")


def stop_live():
    global _stop_flag
    _stop_flag.set()
    simulator.match_state["running"] = False


def get_lineups(fixture_id: int) -> dict:
    """
    Fetch starting lineups for a fixture from API-Football.
    Returns {home_team: [{name, number, position},...], away_team: [...]}
    Falls back to empty lists if lineups not available.
    """
    try:
        data = _get("/fixtures/lineups", {"fixture": fixture_id})
        lineups = data.get("response", [])
        result = {}
        for side in lineups:
            team_name = side.get("team", {}).get("name", "Unknown")
            players = []
            for p in side.get("startXI", []):
                pi = p.get("player", {})
                players.append({
                    "name":     pi.get("name", ""),
                    "number":   pi.get("number", ""),
                    "position": pi.get("pos", ""),
                    "grid":     pi.get("grid", ""),
                })
            # Also add substitutes
            for p in side.get("substitutes", []):
                pi = p.get("player", {})
                players.append({
                    "name":     pi.get("name", ""),
                    "number":   pi.get("number", ""),
                    "position": pi.get("pos", "SUB"),
                    "grid":     None,
                })
            result[team_name] = players
        return result
    except Exception as e:
        print(f"[LiveFeed] lineups error: {e}")
        return {}
