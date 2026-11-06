"""
An agent that improves its own harness

An ``AgentObject`` with an agent loop of your own: no framework's ``agent()``.
The model is asked explicitly (OpenAI's Responses API) and the loop is written
out, which gives you full control of what the model sees each turn, which tools
it has, and what is stored.

The harness, the agent's instructions, lives in each user's database, one
version after another, and every turn reads the latest. ``reflect`` has the
model read the conversation, find what the user corrected or kept asking for,
and rewrite the harness to match, with the reason. So the agent changes itself
per user, and ``harness`` shows every change as a diff::

    uv run python -m restate serve examples.self_improving:app
    curl localhost:8080/learner/alice/chat -d 'What should I pack for a weekend in Lisbon?'
    curl localhost:8080/learner/alice/chat -d 'Way too long. Three bullets at most, please.'
    curl -X POST localhost:8080/learner/alice/reflect                    # version 2, and why
    curl localhost:8080/learner/alice/harness                            # every version, with its diff
    curl localhost:8080/learner/alice/chat -d 'And for Oslo in winter?'  # answered by version 2
    curl localhost:8080/learner/alice/rollback --json 1                  # back to version 1, as version 3

Or chat from a terminal: ``uv run python -m restate.agents chat learner/alice``.

The files: ``agent.py`` is the agent (its harness, its loop, and how it
improves itself), and ``responses.py`` the Responses API plumbing that a
framework would otherwise hide.
"""

from examples.self_improving.agent import app

__all__ = ["app"]
