import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from panopticon_agent.runtime import PanopticonAgentRuntime


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test the Panopticon Agent Builder runtime.")
    parser.add_argument("--list-tools", action="store_true", help="List tools exposed through Panopticon MCP.")
    parser.add_argument("--question", default="", help="Ask one question through the runtime.")
    parser.add_argument("--project-id", type=int, default=None)
    parser.add_argument("--project-path", default="")
    args = parser.parse_args()

    runtime = PanopticonAgentRuntime()
    if args.list_tools:
        print(json.dumps(runtime.list_tools(), indent=2, default=str))
        return 0
    if args.question:
        print(json.dumps(runtime.query(args.question, project_id=args.project_id, project_path=args.project_path), indent=2, default=str))
        return 0
    print(json.dumps(runtime.smoke_check(), indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
