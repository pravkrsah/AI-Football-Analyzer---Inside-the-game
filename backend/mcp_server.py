"""
Model Context Protocol (MCP) server for the match-intelligence platform.

Implements the MCP JSON-RPC 2.0 surface (initialize / tools/list / tools/call)
over two transports:

  • HTTP   — the app's POST /mcp endpoint calls handle_jsonrpc() so the browser
             and any HTTP MCP client can discover and invoke the match tools.
  • stdio  — `python -m backend.mcp_server` runs a line-delimited JSON-RPC loop,
             so a real MCP host (VS Code, Claude Desktop, Azure MCP) can mount
             the live match state as agent tools.

The tools themselves live in backend/mcp_tools.py and are shared with the
multi-agent orchestrator, so agents and external MCP clients see identical data.
"""
from __future__ import annotations
import json
import sys

import backend.mcp_tools as mcp_tools

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "inside-the-game-mcp", "version": "1.0.0"}


def handle_jsonrpc(req: dict) -> dict | None:
    """Handle a single JSON-RPC 2.0 request dict; return a response dict (or None for notifications)."""
    rpc_id = req.get("id")
    method = req.get("method")
    params = req.get("params") or {}

    def ok(result):
        return {"jsonrpc": "2.0", "id": rpc_id, "result": result}

    def err(code, message):
        return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": code, "message": message}}

    if method == "initialize":
        return ok({
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": SERVER_INFO,
        })

    if method in ("notifications/initialized", "initialized"):
        return None  # notification, no response

    if method == "ping":
        return ok({})

    if method == "tools/list":
        return ok({"tools": mcp_tools.list_tools()})

    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") or {}
        result = mcp_tools.call_tool(name, arguments)
        # MCP content envelope: text block carrying the JSON payload
        return ok({
            "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
            "isError": bool(isinstance(result, dict) and result.get("error")),
        })

    if rpc_id is None:
        return None  # unknown notification
    return err(-32601, f"Method not found: {method}")


# ── stdio transport (real MCP host) ──────────────────────────────────────────
def main() -> None:  # pragma: no cover - interactive loop
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except Exception:
            continue
        resp = handle_jsonrpc(req)
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
