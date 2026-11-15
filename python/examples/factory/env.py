"""
The factory's environment:

- Linear, with LINEAR_API_KEY (and LINEAR_WEBHOOK_SECRET, its webhook's signing secret).
- The project on GitHub, with GITHUB_REPO (owner/name) and GITHUB_TOKEN (and
  GITHUB_WEBHOOK_SECRET, its webhook's secret).
- WORKSPACE, where the coders work (/tmp/restate-factory by default).
- CODER_MODEL, the coders' model (Claude by default). Triage, the planner and
  the reviewer run on $RESTATE_AGENT_MODEL, else OpenAI's default.

LINEAR_MCP_URL, GITHUB_MCP_URL and GITHUB_REMOTE point it elsewhere, such as to
GitHub Enterprise; they default to Linear's and GitHub's.
"""

import asyncio
import os
from pathlib import Path

from restate import sessions

from examples.factory.mcp_client import McpClient
from examples.factory.workspace import clone, project


def required(name: str, what: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"The factory needs {name}: {what} (see examples/factory/README.md)")
    return value


LINEAR_API_KEY = required("LINEAR_API_KEY", "a Linear API key it acts with")
LINEAR_WEBHOOK_SECRET = os.environ.get("LINEAR_WEBHOOK_SECRET")
GITHUB_REPO = required("GITHUB_REPO", "the GitHub repository it builds in, as owner/name")
GITHUB_TOKEN = required("GITHUB_TOKEN", f"a token that can push to {GITHUB_REPO}, and open its pull requests")
GITHUB_WEBHOOK_SECRET = os.environ.get("GITHUB_WEBHOOK_SECRET")
WORKSPACE = os.environ.get("WORKSPACE", "/tmp/restate-factory")
CODER_MODEL = os.environ.get("CODER_MODEL", "anthropic/claude-sonnet-5-5")

linear = McpClient(
    os.environ.get("LINEAR_MCP_URL", "https://mcp.linear.app/mcp"), {"authorization": f"Bearer {LINEAR_API_KEY}"}
)
github = McpClient(
    os.environ.get("GITHUB_MCP_URL", "https://api.githubcopilot.com/mcp/"), {"authorization": f"Bearer {GITHUB_TOKEN}"}
)
REMOTE = os.environ.get("GITHUB_REMOTE", f"https://github.com/{GITHUB_REPO}.git")
OWNER, REPO = GITHUB_REPO.split("/", 1)

_project: str | None = None
_project_lock = asyncio.Lock()


async def remote() -> str:
    """The project's repository, with a first commit if it is empty: made ready once, when first needed.

    One at a time: two coders starting at once on an empty repository would both push its first commit.
    """
    global _project  # a cache: made again next time if it failed
    async with _project_lock:
        if _project is None:
            _project = await project(REMOTE)
    return _project


async def folder_of(ctx: sessions.SessionContext) -> Path:
    """The agent's clone of the project, on its task's branch: made the first time it needs it.

    ``coder/ENG-1.parser`` and ``reviewer/ENG-1.parser`` share one, ``WORKSPACE/ENG-1.parser``.
    """
    return await clone(WORKSPACE, await remote(), ctx.key)
