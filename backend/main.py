"""
HTTP server using Python stdlib only — no external web framework.
Routes GET/POST requests, serves static frontend files, and handles SSE.
"""
import json
import mimetypes
import os
import queue
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import backend.config as config
import backend.match_simulator as simulator
import backend.narrative_engine as narrative
import backend.tactical_analyser as tactical
import backend.embedding_search as embedding
import backend.translator as translator
import backend.live_feed as live_feed
import backend.goal_analysis as goal_analysis
import backend.key_moments as key_moments
import backend.pundit_chat as pundit_chat
import backend.guardrails as guardrails
import backend.agents as agents
import backend.mcp_tools as mcp_tools
import backend.mcp_server as mcp_server
from backend.database import init_db

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")

MIME = {
    ".html": "text/html; charset=utf-8",
    ".css":  "text/css",
    ".js":   "application/javascript",
    ".json": "application/json",
    ".ico":  "image/x-icon",
    ".png":  "image/png",
    ".svg":  "image/svg+xml",
}


class Handler(BaseHTTPRequestHandler):

    # ── Helpers ─────────────────────────────────────────────────

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def send_json(self, data, status: int = 200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length:
            raw = self.rfile.read(length)
            try:
                result = json.loads(raw)
                return result if isinstance(result, dict) else {}
            except Exception:
                return {}
        return {}

    def serve_file(self, filepath: str):
        if not os.path.isfile(filepath):
            self.send_json({"error": "Not found"}, 404)
            return
        ext = os.path.splitext(filepath)[1].lower()
        mime = MIME.get(ext, "application/octet-stream")
        with open(filepath, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        # always serve the latest frontend — avoids stale cached HTML/JS/CSS
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        print(f"  {self.address_string()} {fmt % args}")

    # ── OPTIONS (CORS preflight) ─────────────────────────────────

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    # ── GET ──────────────────────────────────────────────────────

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        qs = parse_qs(parsed.query)

        try:
            # Frontend
            if path in ("/", "/index.html"):
                self.serve_file(os.path.join(FRONTEND_DIR, "index.html"))

            elif path.startswith("/static/"):
                fname = path[len("/static/"):]
                self.serve_file(os.path.join(FRONTEND_DIR, fname))

            # SSE stream
            elif path == "/api/match/stream":
                self._sse_stream()

            # Match
            elif path == "/api/match/state":
                self.send_json(simulator.get_state())

            elif path == "/api/match/events":
                n = int(qs.get("n", ["20"])[0])
                self.send_json({"events": simulator.get_recent_events(n)})

            # Players
            elif path == "/api/players":
                data_path = os.path.join(os.path.dirname(__file__), "..", "data", "players.json")
                with open(data_path) as f:
                    players = json.load(f)
                self.send_json(players)

            # Participants of the CURRENT match (adapts to simulation OR replayed fixture)
            elif path == "/api/match/participants":
                state = simulator.get_state()
                home, away = state.get("home_team"), state.get("away_team")
                players, seen = [], set()
                # 1) full squads if the fixture is one we have in players.json (simulation)
                for team in (home, away):
                    for p in simulator.PLAYERS.get(team, []):
                        if p["name"] not in seen:
                            seen.add(p["name"]); players.append({"name": p["name"], "team": team})
                # 2) anyone who has actually appeared in events (covers live replays)
                for e in simulator.match_state.get("events", []):
                    n, t = e.get("player"), e.get("team")
                    if n and n not in seen:
                        seen.add(n); players.append({"name": n, "team": t})
                self.send_json({"home_team": home, "away_team": away, "players": players})

            # Languages
            elif path == "/api/translate/languages":
                self.send_json({"languages": translator.SUPPORTED_LANGUAGES})

            # MCP — discover the match-intelligence tools over HTTP
            elif path == "/api/mcp/tools":
                self.send_json({"server": mcp_server.SERVER_INFO, "tools": mcp_tools.list_tools()})

            # Historical moments list
            elif path == "/api/search/moments":
                self.send_json({"moments": embedding._moments})

            # Live feed — fixture discovery
            elif path == "/api/live/fixtures":
                mode = qs.get("mode", ["recent"])[0]
                try:
                    if mode == "live":
                        fixtures = live_feed.get_live_fixtures()
                    elif mode == "upcoming":
                        fixtures = live_feed.get_upcoming_fixtures()
                    else:
                        fixtures = live_feed.get_recent_fixtures()
                    self.send_json({"mode": mode, "fixtures": fixtures})
                except Exception as e:
                    self.send_json({"error": str(e), "fixtures": []}, 200)

            # Live feed — lineups for a specific fixture
            elif path == "/api/live/lineups":
                fixture_id = qs.get("fixture_id", [None])[0]
                if not fixture_id:
                    self.send_json({"error": "fixture_id required"}, 400)
                    return
                lineups = live_feed.get_lineups(int(fixture_id))
                self.send_json({"fixture_id": fixture_id, "lineups": lineups})

            else:
                self.send_json({"error": "Not found"}, 404)

        except Exception as e:
            print(f"[GET ERROR] {path}: {e}")
            self.send_json({"error": str(e)}, 500)

    # ── POST ─────────────────────────────────────────────────────

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        qs = parse_qs(parsed.query)
        body = self.read_json()

        try:
            # Match control
            if path == "/api/match/start":
                if simulator.match_state["running"]:
                    self.send_json({"error": "Match already running"}, 400)
                    return
                speed = float(qs.get("speed", ["1.5"])[0])
                threading.Thread(target=simulator.run_simulation, args=(speed,), daemon=True).start()
                self.send_json({"status": "started", "match_id": simulator.MATCH_ID, "speed": speed})

            elif path == "/api/match/stop":
                simulator.stop_simulation()
                live_feed.stop_live()
                self.send_json({"status": "stopped"})

            # Live feed — start replay of a completed fixture
            elif path == "/api/live/replay":
                fixture_id = body.get("fixture_id")
                if not fixture_id:
                    self.send_json({"error": "fixture_id required"}, 400)
                    return
                speed = float(body.get("speed", 5.0))
                result = live_feed.start_replay(int(fixture_id), speed)
                self.send_json(result)

            # Live feed — start live polling of an ongoing fixture
            elif path == "/api/live/start":
                fixture_id = body.get("fixture_id")
                if not fixture_id:
                    self.send_json({"error": "fixture_id required"}, 400)
                    return
                poll = int(body.get("poll_interval", 60))
                result = live_feed.start_live(int(fixture_id), poll)
                self.send_json(result)

            elif path == "/api/live/stop":
                live_feed.stop_live()
                self.send_json({"status": "live_stopped"})

            # Narrative
            elif path == "/api/narrative/commentary":
                event = body.get("event", {})
                ntype = body.get("narrative_type", "commentary")
                state = simulator.get_state()
                text = narrative.generate_social_snippet(event) if ntype == "social" else narrative.generate_live_commentary(event, state)
                self.send_json({"type": ntype, "text": text})

            elif path == "/api/narrative/half-time":
                events = simulator.match_state["events"]
                first_half = [e for e in events if e.get("minute", 0) <= 45]
                if not first_half:
                    self.send_json({"error": "No first-half events yet"}, 400)
                    return
                text = narrative.generate_half_time_analysis(first_half, simulator.get_state())
                self.send_json({"type": "half_time_analysis", "text": text})

            elif path == "/api/narrative/recap":
                events = simulator.match_state["events"]
                if len(events) < 5:
                    self.send_json({"error": "Not enough match events for a recap"}, 400)
                    return
                text = narrative.generate_match_recap(events, simulator.get_state())
                self.send_json({"type": "match_recap", "text": text})

            # Goal build-up analysis
            elif path == "/api/goal/buildup":
                events = simulator.match_state["events"]
                # Find the specific goal by minute + player, or use the last goal
                goal_event = body.get("goal_event")
                if not goal_event:
                    goals = [e for e in events if e.get("type") == "goal"]
                    if not goals:
                        self.send_json({"error": "No goals yet"}, 400)
                        return
                    goal_event = goals[-1]
                preceding = goal_analysis.get_preceding_events(events, goal_event)
                result = goal_analysis.analyse_goal_buildup(goal_event, preceding, simulator.get_state())
                self.send_json(result)

            # Goal projection (xG) + near-miss "better angle" coaching
            elif path == "/api/goal/projection":
                import backend.goal_projection as goal_projection
                self.send_json(goal_projection.project(int(body.get("near_misses", 3))))

            # Tactical
            elif path == "/api/tactical/analyse":
                events = simulator.match_state["events"]
                if len(events) < 3:
                    self.send_json({"error": "Not enough events yet"}, 400)
                    return
                result = tactical.analyse_tactical_moment(events, simulator.get_state(), body.get("focus_event"))
                self.send_json(result)

            elif path == "/api/tactical/explain":
                event = body.get("event", {})
                text = tactical.explain_key_moment(event, simulator.match_state["events"], simulator.get_state())
                self.send_json({"text": text})

            # Search
            elif path == "/api/search/similar":
                results = embedding.find_similar_moments(body.get("query", ""), int(body.get("top_k", 3)))
                self.send_json({"query": body.get("query", ""), "results": results})

            elif path == "/api/search/similar-event":
                results = embedding.find_similar_to_event(body.get("event", {}), int(body.get("top_k", 3)))
                self.send_json({"results": results})

            # Translation
            elif path == "/api/translate":
                result = translator.translate(body.get("text", ""), body.get("language", "es"))
                self.send_json(result)

            # Multi-agent orchestration — runs the full pipeline for one fan profile
            elif path == "/api/agents/analyse":
                profile = body.get("profile") if isinstance(body.get("profile"), dict) else body
                packet = agents.run_pipeline(profile)
                # push the broadcast overlay + personalized beat to live clients
                if packet.get("overlay"):
                    simulator.broadcast({"type": "agent_overlay", "data": packet["overlay"]})
                if packet.get("personalized"):
                    simulator.broadcast({"type": "personalized", "data": packet["personalized"]})
                self.send_json(packet)

            # MCP JSON-RPC 2.0 transport over HTTP (initialize / tools/list / tools/call)
            elif path == "/mcp":
                resp = mcp_server.handle_jsonrpc(body)
                if resp is None:
                    self.send_response(204); self._cors(); self.end_headers()
                else:
                    self.send_json(resp)

            # AI Pundit chat
            elif path == "/api/chat":
                question = (body.get("question") or "").strip()
                if not question:
                    self.send_json({"error": "question required"}, 400)
                    return
                # Safety pre-filter — no GPT call if question is off-topic or injected
                safe, rejection = guardrails.check_question(question)
                if not safe:
                    self.send_json({"answer": rejection})
                    return
                history = body.get("history", [])
                if not isinstance(history, list):
                    history = []
                state = simulator.get_state()
                events = simulator.get_recent_events(10)
                answer = pundit_chat.answer_question(question, state, events, history)
                self.send_json({"answer": answer})

            else:
                self.send_json({"error": "Not found"}, 404)

        except Exception as e:
            print(f"[POST ERROR] {path}: {e}")
            self.send_json({"error": str(e)}, 500)

    # ── SSE ──────────────────────────────────────────────────────

    def _sse_stream(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self._cors()
        self.end_headers()

        q: queue.Queue = queue.Queue()
        with simulator.clients_lock:
            simulator.clients.append(q)

        try:
            # Immediately send current state
            connected = json.dumps({"type": "connected", "state": simulator.get_state()})
            self.wfile.write(f"data: {connected}\n\n".encode())
            self.wfile.flush()

            while True:
                try:
                    event = q.get(timeout=20)
                    self.wfile.write(f"data: {json.dumps(event)}\n\n".encode())
                    self.wfile.flush()
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()

        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            with simulator.clients_lock:
                if q in simulator.clients:
                    simulator.clients.remove(q)


def create_server(host: str = "0.0.0.0", port: int = 8000) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), Handler)
