"""Typed research CLI. Spark is not called until MODEL_API_KEY is present."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

from app.envfile import load_env, write_key
from app.law_gateway import DEFAULT_MCP_URL
from app.muse_client import CreditNotReady, spark_ready
from app.research import research


async def run(question: str, as_of: str | None, url: str, mode: str) -> int:
    try:
        result = await research(question, as_of=as_of, mode=mode, url=url)
    except CreditNotReady as exc:
        print(exc, file=sys.stderr)
        return 3
    print(result.disclaimer)
    print("planner:", result.planner, "spark_ready:", result.spark_ready)
    if result.tool_names:
        print("tools:", ", ".join(result.tool_names))
    for step in result.steps:
        print("tool", step["tool"], json.dumps(step["arguments"], sort_keys=True))
    if result.catch:
        print("catch:", result.catch)
    print("quotes_ok:", result.quotes_ok)
    if result.quote_failures:
        print("quote_failures:", result.quote_failures)
    for card in result.source_cards:
        print("card:", card.get("role"), card.get("title") or card.get("section_id"), card.get("url") or "")
    print()
    print(result.summary)
    return 0 if result.found or result.catch else 2


def main(argv: list[str] | None = None) -> int:
    load_env()
    parser = argparse.ArgumentParser(description="Ask an unofficial Indiana Code question.")
    parser.add_argument("question", nargs="?", default="What does IC 31-16-15-25 say about income withholding?")
    parser.add_argument("--as-of", dest="as_of", default=None)
    parser.add_argument("--mode", choices=("auto", "fixture", "spark"), default="auto")
    parser.add_argument("--url", default=os.environ.get("INDIANA_MCP_URL", DEFAULT_MCP_URL))
    parser.add_argument("--serve", action="store_true", help="Run the loopback page on 127.0.0.1:8767")
    parser.add_argument("--preflight", action="store_true", help="Check hosted MCP tools. No Muse call.")
    parser.add_argument("--eval-golden", action="store_true", help="Run the four demo questions over the hosted MCP.")
    parser.add_argument(
        "--set-key",
        action="store_true",
        help="Prompt for MODEL_API_KEY on this machine and write a gitignored .env.",
    )
    args = parser.parse_args(argv)
    if args.set_key:
        return _set_key()
    if args.serve:
        from app.server import main as serve

        serve()
        return 0
    if args.preflight:
        from app.preflight import preflight

        report = asyncio.run(preflight(args.url))
        print(json.dumps(report, indent=2))
        return 0 if report.get("ok") else 2
    if args.eval_golden:
        from app.preflight import eval_golden

        report = asyncio.run(eval_golden(args.url))
        print(json.dumps(report, indent=2))
        return 0 if report.get("ok") else 2
    if args.mode == "spark" and not spark_ready():
        print("MODEL_API_KEY is unset; event credits are not applied yet.", file=sys.stderr)
        return 3
    return asyncio.run(run(args.question, args.as_of, args.url, args.mode))


def _set_key() -> int:
    import getpass

    secret = getpass.getpass("Paste MODEL_API_KEY (hidden, stays on this Mac): ")
    try:
        write_key(secret)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    print("Wrote gitignored .env (mode 600). Key not printed.")
    print("spark_ready:", spark_ready())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
