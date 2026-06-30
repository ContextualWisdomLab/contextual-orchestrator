"""Command-line entrypoint for routing prompts or serving the orchestration API."""

from __future__ import annotations

import argparse
import json

from .orchestrator import TaskOrchestrator, load_agents
from .server import serve


def main() -> None:
    """Parse CLI options and run either prompt completion or the HTTP server."""
    parser = argparse.ArgumentParser(description="Route or conduct chat requests across model agents.")
    parser.add_argument("prompt", nargs="?", help="User prompt for CLI mode.")
    parser.add_argument("--agents", default="examples/agents.mock.json", help="Agent config JSON.")
    parser.add_argument("--mode", choices=["auto", "route", "conduct"], default="auto")
    parser.add_argument("--serve", action="store_true", help="Run the chat completions HTTP server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    orchestrator = TaskOrchestrator(load_agents(args.agents))

    if args.serve:
        serve(orchestrator, host=args.host, port=args.port)
        return

    if not args.prompt:
        parser.error("prompt is required unless --serve is set")

    result = orchestrator.complete([{"role": "user", "content": args.prompt}], mode=args.mode)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
