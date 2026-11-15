"""
The agents' tools, by what they work on:

- Linear's, from its MCP server, signed by the agent that writes.
- GitHub's pull requests, through its MCP server, signed: open one, comment on one.
- A coder's clone of the project: ``bash``, ``read_file``, ``write_file``.
- A reviewer's pull request, as pushed: its diff, and its files.

A tool may run again after a crash mid-call: each is safe to run twice, or says
what happens if it does (mcp_client.py).
"""

import asyncio
import os
from collections.abc import Awaitable
from pathlib import Path
from typing import Annotated, Any

import mcp_types
import restate
from pydantic import Field
from restate import sessions
from restate.agents import Tool, ToolCall, tool

from examples.factory import env
from examples.factory.github import pull_request_mark
from examples.factory.signatures import signer
from examples.factory.workspace import GitError, Pushed, pushed

# --- Linear, signed ---------------------------------------------------------------------------------


async def linear_tools(who: str) -> list[Tool]:
    """Linear's tools for the agent ``who``: what it writes opens with its name, and its part.

    The agents all write as one Linear user: this tells them apart. Asked of Linear's MCP server when an
    agent first needs them.
    """
    sign = signer(who)

    def signed(listed: mcp_types.Tool, arguments: dict[str, Any], call: ToolCall) -> dict[str, Any]:
        field = _writing(listed, arguments)
        return arguments if field is None else {**arguments, field: sign(call.ctx.key, str(arguments[field]))}

    return await env.linear.tools(signed)


def _writing(listed: mcp_types.Tool, arguments: dict[str, Any]) -> str | None:
    """The field of a Linear tool's input that an agent writes, to sign.

    A comment's ``body``, or a new issue's ``description`` (an issue with an ``id`` is updated: it is signed
    already). By the input, not the tool's name alone: Linear names its tools as it likes.
    """
    fields: dict[str, Any] = listed.input_schema.get("properties") or {}
    if "comment" in listed.name and "body" in fields and isinstance(arguments.get("body"), str):
        return "body"
    if (
        "issue" in listed.name
        and "description" in fields
        and isinstance(arguments.get("description"), str)
        and "id" not in arguments
    ):
        return "description"
    return None


# --- GitHub's pull requests, signed --------------------------------------------------------------------


def open_pull_request(who: str) -> Tool:
    """``create_pull_request`` for ``who``: its description opens with who opened it, and ends with the coder's mark."""
    sign = signer(who)

    @tool(name="create_pull_request")
    async def create_pull_request(
        ctx: sessions.SessionContext,
        title: str,
        body: Annotated[str, Field(description="What it does, and how it was tested, in Markdown")],
        head: Annotated[str, Field(description="The branch with the changes, pushed already")],
        base: Annotated[str, Field(description="The branch it goes into")],
    ) -> str:
        """Open a pull request of the project: from the branch ``head`` into ``base``. Answers with its link."""
        described = f"{sign(ctx.key, body)}\n\n{pull_request_mark(ctx.key)}"
        arguments = {
            "owner": env.OWNER,
            "repo": env.REPO,
            "title": title,
            "body": described,
            "head": head,
            "base": base,
        }
        return await env.github.call("create_pull_request", arguments)

    return create_pull_request


def comment_on_pull_request(who: str) -> Tool:
    """``comment_on_pull_request`` for ``who``: a comment on a pull request, signed, such as a review or an answer to one."""
    sign = signer(who)

    @tool(name="comment_on_pull_request")
    async def comment(
        ctx: sessions.SessionContext,
        number: Annotated[int, Field(description="The pull request's number")],
        body: Annotated[str, Field(description="The comment, in Markdown")],
    ) -> str:
        """Comment on a pull request: a review, or an answer to one."""
        arguments = {"owner": env.OWNER, "repo": env.REPO, "issue_number": number, "body": sign(ctx.key, body)}
        return await env.github.call("add_issue_comment", arguments)

    return comment


# --- A coder's clone of the project ---------------------------------------------------------------------

# The keys a coder's commands don't see. GITHUB_TOKEN stays: `git push` reads it (see workspace.py).
HIDDEN = ("LINEAR_API_KEY", "LINEAR_WEBHOOK_SECRET", "GITHUB_WEBHOOK_SECRET", "OPENAI_API_KEY", "ANTHROPIC_API_KEY")
HIDDEN_PREFIXES = ("RESTATE_",)
OUTPUT = 20_000  # characters of a command's output the model sees: the end of it


@tool
async def bash(
    ctx: sessions.SessionContext,
    command: Annotated[str, Field(description="The command, run with bash in your clone of the project")],
) -> str:
    """Run a command in your clone of the project (5 minutes at most), and get its exit code and output."""
    folder = await env.folder_of(ctx)
    variables = {k: v for k, v in os.environ.items() if k not in HIDDEN and not k.startswith(HIDDEN_PREFIXES)}
    process = await asyncio.create_subprocess_exec(
        "bash",
        "-c",
        command,
        cwd=folder,
        env=variables,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        out, _ = await asyncio.wait_for(process.communicate(), timeout=300)
    except TimeoutError:
        process.kill()
        await process.wait()
        raise restate.TerminalError("The command took more than 5 minutes, and was stopped") from None
    text = out.decode(errors="replace")
    return f"exit code {process.returncode}\n{text if len(text) <= OUTPUT else '…' + text[-OUTPUT:]}"


@tool(name="read_file")
async def read_own_file(ctx: sessions.SessionContext, path: str) -> str:
    """A file of your clone of the project, by its path in it."""
    target = _inside(await env.folder_of(ctx), path)
    if not target.is_file():
        raise restate.TerminalError(f"There is no file {path}")
    return target.read_text(errors="replace")


@tool
async def write_file(ctx: sessions.SessionContext, path: str, content: str) -> str:
    """Write a file of your clone of the project, by its path in it, all of it: made, or replaced."""
    target = _inside(await env.folder_of(ctx), path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    return f"Wrote {path}"


def _inside(folder: Path, path: str) -> Path:
    target = (folder / path).resolve()
    if not target.is_relative_to(folder):
        raise restate.TerminalError(f"{path} is outside your clone of the project")
    return target


# --- A reviewer's pull request, as pushed ---------------------------------------------------------------


@tool
async def pull_request_diff(ctx: sessions.SessionContext) -> str:
    """The pull request's changes, as pushed: the files it changes, and their diff against main."""
    return await _reading("the changes", (await _pull_request_of(ctx)).changes())


@tool(name="read_file")
async def read_pushed_file(ctx: sessions.SessionContext, path: str) -> str:
    """A file of the pull request, as pushed, by its path in the project."""
    return await _reading(path, (await _pull_request_of(ctx)).file(path))


async def _pull_request_of(ctx: sessions.SessionContext) -> Pushed:
    """The pull request a reviewer reviews: its coder's, as pushed (``reviewer/ENG-1.parser`` reviews
    ``coder/ENG-1.parser``'s), read in a clone of the project, made here if this machine has none."""
    await env.folder_of(ctx)
    return pushed(env.WORKSPACE, ctx.key)


async def _reading(what: str, read: Awaitable[str]) -> str:
    try:
        return await read
    except GitError as error:
        return f"Could not read {what} (pushed yet?): {error}"
