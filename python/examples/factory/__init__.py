"""
A software factory: a new Linear issue, through a webhook, starts a triage
agent, which has the planner plan it, a coder per part build it and open its
pull request, and a reviewer review each one. GitHub's webhook brings people's
comments and reviews, and failed CI runs, to the coder of the pull request.
How it fits together, and how to set it up: README.md.

It works on your Linear workspace and a GitHub repository, and needs
LINEAR_API_KEY, GITHUB_REPO and GITHUB_TOKEN to start::

    uv run python -m restate serve examples.factory:app

The coders run real commands, on this machine: use a sandbox.
"""

from examples.factory.factory import app

__all__ = ["app"]
