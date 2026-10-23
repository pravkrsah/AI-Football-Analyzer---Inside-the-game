"""
YouTube match finder.

Given a YouTube URL:
  1. Fetch the video title via YouTube oEmbed (no API key needed)
  2. Use GPT-4o to extract home/away team names from the title
  3. Search API-Football for the matching completed fixture
  4. Return the fixture ID so the frontend can trigger a replay
"""

import json
import datetime
import urllib.request
import urllib.parse

from backend.ai_client import chat
from backend.live_feed import _get, _format_fixture_list

_PL_LEAGUE_ID = 39


def _get_season() -> int:
    today = datetime.date.today()
    return today.year if today.month >= 8 else today.year - 1


def fetch_yt_title(url: str) -> str:
    """Fetch a YouTube video title via the public oEmbed endpoint (no API key)."""
    oembed = f"https://www.youtube.com/oembed?url={urllib.parse.quote(url, safe='')}&format=json"
    req = urllib.request.Request(oembed, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode())
    return data.get("title", "")


def _extract_teams(title: str) -> dict:
    """Use GPT-4o to pull team names out of a video title."""
    prompt = f"""Extract the two football teams and any date hint from this YouTube video title.
Return ONLY valid JSON with keys: home_team (string), away_team (string), season_hint (e.g. "2024-25" or null).
Use full official Premier League team names.

Title: "{title}"

JSON:"""
    try:
        raw = chat(prompt, max_tokens=120, temperature=0.1, json_mode=True)
        return json.loads(raw)
    except Exception:
        return {}


def _search_fixtures(home: str, away: str, season: int) -> list:
    """Return recent FT fixtures for these two teams in this season."""
    today     = datetime.date.today()
    from_date = (today - datetime.timedelta(days=365)).isoformat()
    to_date   = today.isoformat()

    try:
        data = _get("/fixtures", {
            "league":  _PL_LEAGUE_ID,
            "season":  season,
            "from":    from_date,
            "to":      to_date,
            "status":  "FT",
        })
        fixtures = _format_fixture_list(data.get("response", []))
    except Exception as e:
        print(f"[YouTubeMatch] API-Football error: {e}")
        return []

    def _fuzzy(team_name: str, query: str) -> bool:
        tn, q = team_name.lower(), query.lower()
        words = [w for w in q.split() if len(w) >= 4]
        return any(w in tn for w in words) or q in tn

    return [
        f for f in fixtures
        if ((_fuzzy(f["home_team"], home) and _fuzzy(f["away_team"], away))
            or (_fuzzy(f["home_team"], away) and _fuzzy(f["away_team"], home)))
    ]


def find_match_for_video(url: str) -> dict:
    """
    Main entry point. Returns on success:
      { fixture_id, home_team, away_team, date, home_score, away_score, title }
    Returns on failure:
      { error, title? }
    """
    # Step 1 — video title
    try:
        title = fetch_yt_title(url)
    except Exception as e:
        return {"error": f"Could not read video title ({e})"}

    title = (title or "").strip()
    if not title:
        return {"error": "YouTube returned no title for this URL"}

    # Step 2 — extract teams via GPT-4o
    info = _extract_teams(title)
    home = info.get("home_team", "").strip()
    away = info.get("away_team", "").strip()

    if not home or not away:
        return {"error": "Could not identify both teams from the video title", "title": title}

    # Step 3 — search API-Football (current season, then previous)
    season = _get_season()
    fixtures = _search_fixtures(home, away, season)
    if not fixtures:
        fixtures = _search_fixtures(home, away, season - 1)

    if not fixtures:
        return {
            "error": f"No completed fixture found for {home} vs {away} in API-Football",
            "title": title,
            "home_team": home,
            "away_team": away,
        }

    best = fixtures[0]   # most recent match first (list is reversed in get_recent_fixtures)
    return {
        "fixture_id": best["id"],
        "home_team":  best["home_team"],
        "away_team":  best["away_team"],
        "date":       best["date"],
        "home_score": best.get("home_score"),
        "away_score": best.get("away_score"),
        "home_logo":  best.get("home_logo", ""),
        "away_logo":  best.get("away_logo", ""),
        "title":      title,
    }
