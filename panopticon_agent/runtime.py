import os
import uuid
from typing import Any

from panopticon_agent.env import load_local_env
from panopticon_agent.prompts import build_question_prompt
from panopticon_agent.schemas import AgentResponse, ToolCallResult
from panopticon_agent.tools import PanopticonToolClient


load_local_env()


class PanopticonAgentRuntime:
    """Agent Builder compatible runtime wrapper for Panopticon MCP tools."""

    def __init__(self, *, api_base_url: str | None = None, token: str | None = None) -> None:
        self.api_base_url = api_base_url or os.getenv("PANOPTICON_API_BASE_URL") or os.getenv("APP_API_URL") or "http://127.0.0.1:8000"
        self.token = token if token is not None else (os.getenv("PANOPTICON_AGENT_TOKEN", "") or os.getenv("AGENT_RUNTIME_TOKEN", ""))

    def query(
        self,
        question: str,
        project_id: int | None = None,
        project_path: str = "",
        trace_id: str = "",
    ) -> dict[str, Any]:
        trace_id = trace_id or str(uuid.uuid4())
        client = self._client(trace_id)
        tool_calls: list[ToolCallResult] = []

        scope_args = _scope_args(project_id=project_id, project_path=project_path, limit=8)
        context = client.call_tool("get_chat_context", scope_args)
        tool_calls.append(ToolCallResult("get_chat_context", scope_args, context))

        recommendation_args = {
            **_scope_args(project_id=project_id, project_path=project_path, limit=8),
            "question": build_question_prompt(question, project_id=project_id, project_path=project_path),
            "intent": _intent(question),
            "persist": "false",
        }
        recommendation = client.call_tool("generate_grounded_recommendation", recommendation_args)
        tool_calls.append(ToolCallResult("generate_grounded_recommendation", recommendation_args, recommendation))

        response = AgentResponse(
            answer=_compose_answer(question, context, recommendation),
            trace_id=trace_id,
            tool_calls=tool_calls,
        )
        return _response_dict(response)

    def list_tools(self) -> dict[str, Any]:
        return {"tools": self._client(str(uuid.uuid4())).list_tools()}

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None, trace_id: str = "") -> dict[str, Any]:
        return {
            "trace_id": trace_id or str(uuid.uuid4()),
            "tool_name": name,
            "result": self._client(trace_id or str(uuid.uuid4())).call_tool(name, arguments or {}),
        }

    def smoke_check(self) -> dict[str, Any]:
        trace_id = str(uuid.uuid4())
        client = self._client(trace_id)
        tools = client.list_tools()
        priority = client.call_tool("get_priority_context", {"limit": 3})
        return {
            "status": "ok",
            "trace_id": trace_id,
            "tool_count": len(tools),
            "priority_keys": sorted(priority.keys()),
            "api_base_url": self.api_base_url,
            "authenticated": bool(self.token),
        }

    def _client(self, trace_id: str) -> PanopticonToolClient:
        return PanopticonToolClient(base_url=self.api_base_url, token=self.token, trace_id=trace_id)


def _scope_args(*, project_id: int | None, project_path: str, limit: int) -> dict[str, Any]:
    args: dict[str, Any] = {"limit": limit}
    if project_id:
        args["project_id"] = project_id
    elif project_path:
        args["project_path"] = project_path
    return args


def _intent(question: str) -> str:
    text = question.lower()
    if any(word in text for word in ["fix", "patch", "change", "code"]):
        return "fix_plan"
    if any(word in text for word in ["pipeline", "job", "ci", "failed"]):
        return "pipeline_failure"
    if any(word in text for word in ["risk", "deploy", "deployment"]):
        return "deployment_risk"
    return "summary"


def _compose_answer(question: str, context: dict[str, Any], recommendation: dict[str, Any]) -> str:
    grounded = recommendation.get("grounded_recommendation") or {}
    summary = grounded.get("summary") or grounded.get("answer") or ""
    evidence = grounded.get("evidence") or []
    next_actions = grounded.get("next_actions") or grounded.get("recommendations") or []

    if not summary:
        project = context.get("project") or {}
        project_label = project.get("project_path") or "the synced workspace"
        summary = f"I checked Panopticon context for {project_label}, but the available evidence is not strong enough to name a specific root cause."

    lines = [summary.strip()]
    if evidence:
        lines.append("")
        lines.append("Evidence I used:")
        lines.extend(f"- {_shorten(str(item))}" for item in evidence[:5])
    if next_actions:
        lines.append("")
        lines.append("Recommended next actions:")
        lines.extend(f"- {_shorten(str(item))}" for item in next_actions[:5])
    if not evidence and not next_actions:
        lines.append("")
        lines.append("Recommended next action: sync the latest project pipelines, failed jobs, and repository context, then ask the question again.")
    return "\n".join(lines)


def _shorten(value: str, limit: int = 220) -> str:
    clean = " ".join(value.split())
    return clean if len(clean) <= limit else clean[: limit - 3].rstrip() + "..."


def _response_dict(response: AgentResponse) -> dict[str, Any]:
    return {
        "answer": response.answer,
        "trace_id": response.trace_id,
        "runtime": response.runtime,
        "tool_calls": [
            {"tool_name": call.tool_name, "arguments": call.arguments, "result": call.result}
            for call in response.tool_calls
        ],
    }
