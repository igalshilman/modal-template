"""
The tutorial: a wallet per user, from a SQL database per key to agents, one
idea per lesson. The docstring at the top of each lesson explains its idea,
and lists the requests to try it.

Every lesson's objects carry its number (``wallet01`` … ``wallet16``,
``handle07``, ``coach15``, …), so they can all be served by one deployment:
``tutorial`` is all of them, in order. It is off by default: the comment in
src/app.py shows how to include it. ``sessions.app`` adds what the agents need
beside them (the ``signals`` object that answers lesson 14's waits).

Lessons 09 to 16 ask OpenAI's models, with your key in ``OPENAI_API_KEY``.
"""

import importlib

import restate

LESSONS = [
    # Part 1 · A database per key
    "01_object",
    "02_database",
    "03_views",
    "04_migrations",
    # Part 2 · Changes that happen once
    "05_transaction",
    "06_retries",
    "07_calls",
    "08_sends",
    # Part 3 · Agents
    "09_prompt",
    "10_agent",
    "11_tools",
    "12_tool_writes",
    "13_restate_tools",
    "14_approval",
    "15_subagents",
    # Appendix
    "16_handoffs",
]

# A lesson's file name starts with its number, which `import` can't spell: import it by name instead.
tutorial: list[restate.VirtualObject | restate.Service | restate.Workflow] = [
    service for lesson in LESSONS for service in importlib.import_module(f"{__name__}.{lesson}").services
]
