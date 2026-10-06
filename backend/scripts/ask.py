"""Run questions through the agent workflow from the CLI.

Usage: python -m scripts.ask "Who funds OpenAI competitors?" [--json]
"""

import asyncio
import json
import logging
import sys

from app.agents.workflow import initial_state
from app.container import Container

DEMO_QUESTIONS = [
    "Which startups compete with OpenAI?",
    "Which investors actively fund AI startups?",
    "Show AI startups founded by ex-Google employees.",
    "Which startups are similar to Anthropic but funded by different investors?",
    "Which companies raised Series B after 2024 and operate in Computer Vision?",
    "Show the relationship between OpenAI, Anthropic, Microsoft, and Google.",
    "Who funds OpenAI competitors?",
    "What is OpenAI?",
    "Compare OpenAI and Anthropic",
    "Find promising Computer Vision startups.",
]


async def main(questions: list[str], as_json: bool) -> None:
    logging.basicConfig(level=logging.WARNING)
    c = Container.from_settings()
    await c.start()
    try:
        for q in questions:
            s = await c.workflow.ainvoke(initial_state(q))
            if as_json:
                print(json.dumps({k: v for k, v in s.items() if k != "graph"}, default=str, indent=2))
                continue
            print("=" * 100)
            print(f"Q: {q}")
            print(f"   type={s['query_type']} intent={s['intent']} confidence={s['confidence']['score']} "
                  f"({s['confidence']['level']}) nodes={len(s.get('graph', {}).get('nodes', {}))} "
                  f"edges={len(s.get('graph', {}).get('edges', {}))} docs={len(s.get('documents') or [])}")
            if s.get("errors"):
                print(f"   ERRORS: {s['errors']}")
            print(s["answer"])
    finally:
        await c.stop()


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--json"]
    asyncio.run(main(args or DEMO_QUESTIONS, "--json" in sys.argv))
