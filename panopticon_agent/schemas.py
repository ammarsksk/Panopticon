from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AgentRequest:
    question: str
    project_id: int | None = None
    project_path: str = ""
    trace_id: str = ""


@dataclass(frozen=True)
class ToolCallResult:
    tool_name: str
    arguments: dict[str, Any]
    result: dict[str, Any]


@dataclass(frozen=True)
class AgentResponse:
    answer: str
    trace_id: str
    tool_calls: list[ToolCallResult] = field(default_factory=list)
    runtime: str = "panopticon-agent-builder-runtime"
