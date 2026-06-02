import argparse
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from panopticon_agent.env import load_local_env


def deployment_config() -> dict:
    load_local_env()
    project = os.getenv("GOOGLE_CLOUD_PROJECT", "")
    location = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
    api_base_url = os.getenv("PANOPTICON_API_BASE_URL", "") or os.getenv("APP_API_URL", "")
    agent_token = os.getenv("PANOPTICON_AGENT_TOKEN", "") or os.getenv("AGENT_RUNTIME_TOKEN", "")
    token_configured = bool(agent_token)
    service_account = os.getenv("AGENT_ENGINE_SERVICE_ACCOUNT", "")

    missing = [name for name, value in {
        "GOOGLE_CLOUD_PROJECT": project,
        "PANOPTICON_API_BASE_URL": api_base_url,
        "PANOPTICON_AGENT_TOKEN": "configured" if token_configured else "",
    }.items() if not value]
    if missing:
        raise RuntimeError("Missing required environment variables: " + ", ".join(missing))

    config = {
        "source_packages": ["panopticon_agent", "requirements-agent.txt"],
        "entrypoint_module": "panopticon_agent.agent",
        "entrypoint_object": "root_agent",
        "class_methods": [
            {
                "name": "query",
                "api_mode": "",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "question": {"type": "string"},
                        "project_id": {"type": "integer"},
                        "project_path": {"type": "string"},
                        "trace_id": {"type": "string"}
                    },
                    "required": ["question"]
                }
            },
            {"name": "list_tools", "api_mode": "", "parameters": {"type": "object", "properties": {}}},
            {
                "name": "call_tool",
                "api_mode": "",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "arguments": {"type": "object"},
                        "trace_id": {"type": "string"}
                    },
                    "required": ["name"]
                }
            },
            {"name": "smoke_check", "api_mode": "", "parameters": {"type": "object", "properties": {}}}
        ],
        "requirements_file": "requirements-agent.txt",
        "display_name": "panopticon-agent-runtime",
        "description": "Panopticon managed agent runtime that calls workspace-scoped MCP tools.",
        "env_vars": {
            "PANOPTICON_API_BASE_URL": api_base_url,
            "PANOPTICON_AGENT_TOKEN": agent_token,
        },
    }
    if service_account:
        config["service_account"] = service_account
    return {"project": project, "location": location, "config": config}


def deploy() -> dict:
    try:
        from google.cloud.aiplatform import vertexai
    except ImportError as exc:
        raise RuntimeError("Install Agent Engine dependencies first: python -m pip install -r requirements-agent.txt") from exc

    payload = deployment_config()
    client = vertexai.Client(project=payload["project"], location=payload["location"])
    remote_agent = client.agent_engines.create(config=payload["config"])
    api_resource = getattr(remote_agent, "api_resource", None)
    resource_name = getattr(api_resource, "name", "") or getattr(remote_agent, "resource_name", "")
    return {"resource_name": resource_name, "display_name": payload["config"]["display_name"]}


def main() -> int:
    parser = argparse.ArgumentParser(description="Deploy Panopticon to Vertex AI Agent Engine.")
    parser.add_argument("--dry-run", action="store_true", help="Validate and print deployment config without calling Google Cloud.")
    args = parser.parse_args()

    os.chdir(ROOT)
    payload = deployment_config()
    if args.dry_run:
        printable = dict(payload)
        printable["config"] = dict(payload["config"])
        printable["config"]["env_vars"] = {
            "PANOPTICON_API_BASE_URL": payload["config"]["env_vars"]["PANOPTICON_API_BASE_URL"],
            "PANOPTICON_AGENT_TOKEN": "configured",
        }
        print(json.dumps(printable, indent=2))
        return 0

    print(json.dumps(deploy(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
