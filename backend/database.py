import sqlite3
import json
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "logs", "match.db")

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS match_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id TEXT,
            minute INTEGER,
            event_type TEXT,
            team TEXT,
            player TEXT,
            description TEXT,
            data TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS narratives (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id TEXT,
            event_id INTEGER,
            narrative_type TEXT,
            language TEXT DEFAULT 'en',
            content TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS tactical_analyses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id TEXT,
            minute INTEGER,
            analysis TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()
    conn.close()

def save_event(match_id: str, event: dict) -> int:
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO match_events (match_id, minute, event_type, team, player, description, data) VALUES (?,?,?,?,?,?,?)",
        (match_id, event.get("minute"), event.get("type"), event.get("team"),
         event.get("player"), event.get("description"), json.dumps(event))
    )
    conn.commit()
    row_id = cur.lastrowid
    conn.close()
    return row_id

def save_narrative(match_id: str, event_id: int, narrative_type: str, content: str, language: str = "en"):
    conn = get_conn()
    conn.execute(
        "INSERT INTO narratives (match_id, event_id, narrative_type, language, content) VALUES (?,?,?,?,?)",
        (match_id, event_id, narrative_type, language, content)
    )
    conn.commit()
    conn.close()

def get_all_events(match_id: str) -> list:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM match_events WHERE match_id=? ORDER BY minute ASC", (match_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
