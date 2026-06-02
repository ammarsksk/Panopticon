import json
import os
import uuid
from typing import Any
from urllib import error, request

from panopticon_agent.env import load_local_env


load_local_env()


class PanopticonToolClient:
    """Small HTTP/MCP client used by the managed agent runtime."""

    def __init__(self, *, base_url: str | None = None, token: str | None = None, trace_id: str | None = None) -> None:
        self.base_url = (base_url or os.getenv("PANOPTICON_API_BASE_URL") or os.getenv("APP_API_URL") or "http://127.0.0.1:8000").rstrip("/")
        self.token = token if token is not None else (os.getenv("PANOPTICON_AGENT_TOKEN", "") or os.getenv("AGENT_RUNTIME_TOKEN", ""))
        self.trace_id = trace_id or os.getenv("PANOPTICON_AGENT_TRACE_ID") or str(uuid.uuid4())

    def list_tools(self) -> list[dict[str, Any]]:
        response = self._mcp("tools/list", {})
        return response.get("tools", [])

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        response = self._mcp("tools/call", {"name": name, "arguments": arguments or {}})
        content = response.get("content") or []
        if not content:
            return response
        text = content[0].get("text", "{}")
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return {"text": text}
        return parsed if isinstance(parsed, dict) else {"result": parsed}

    def _mcp(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        payload = {"jsonrpc": "2.0", "id": str(uuid.uuid4()), "method": method, "params": params}
        response = self._post_json("/mcp", payload)
        if "error" in response:
            message = response["error"].get("message", "MCP tool call failed")
            raise RuntimeError(message)
        return response.get("result", {})

    def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        data = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "X-Panopticon-Agent-Runtime": "vertex-agent-engine",
            "X-Panopticon-Agent-Trace-Id": self.trace_id,
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = request.Request(f"{self.base_url}{path}", data=data, headers=headers, method="POST")
        try:
            with request.urlopen(req, timeout=30) as response:
                body = response.read().decode("utf-8")
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Panopticon API returned HTTP {exc.code}: {detail}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"Panopticon API is unreachable at {self.base_url}: {exc}") from exc
        return json.loads(body or "{}")
