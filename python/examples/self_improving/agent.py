"""
The agent: its harness, its loop, and how it improves itself.
"""

import difflib
import itertools
from typing import Annotated

import restate
from pydantic import BaseModel, Field
from restate import sessions
from restate.agents import AgentObject, ToolCall, tool
from restate.agents.internal import Call, Conversation, answer_once, run_tool

from examples.self_improving import responses

# --- The harness: the agent's instructions, one version after another, in each user's database ------

FIRST = "You are a helpful travel assistant. Answer questions about trips."

MIGRATIONS = [
    "CREATE TABLE harness (version INTEGER PRIMARY KEY, system TEXT NOT NULL, why TEXT NOT NULL, request TEXT UNIQUE)",
    f"INSERT INTO harness (version, system, why) VALUES (1, '{FIRST}', 'The first version.')",
]

COLUMNS = "version, system, why"


class Version(BaseModel):
    version: int
    system: str
    why: str
    diff: str = ""
    """What changed since the version before, as a unified diff."""


class History(BaseModel):
    versions: list[Version]


def version_of(row: sessions.Row) -> Version:
    return Version(version=int(row["version"] or 0), system=str(row["system"]), why=str(row["why"]))


async def latest(db: sessions.DatabaseReader) -> Version:
    row = await db.get(f"SELECT {COLUMNS} FROM harness ORDER BY version DESC LIMIT 1")
    assert row is not None  # the migration stored the first version
    return version_of(row)


async def stored_by(db: sessions.DatabaseReader, request: str) -> Version | None:
    """The version that request ``request`` stored, if it did."""
    row = await db.get(f"SELECT {COLUMNS} FROM harness WHERE request = ?", [request])
    return version_of(row) if row else None


async def add(ctx: sessions.SessionContext, system: str, why: str) -> Version:
    """Store ``system`` as the next version, once for this request: a retry gets the version it stored."""
    await ctx.db.execute(
        "INSERT OR IGNORE INTO harness (version, system, why, request) SELECT max(version) + 1, ?, ?, ? FROM harness",
        [system, why, ctx.request.id],
    )
    stored = await stored_by(ctx.db, ctx.request.id)
    assert stored is not None
    return stored


def diff(before: Version, after: Version) -> str:
    lines = difflib.unified_diff(
        before.system.splitlines(), after.system.splitlines(), f"v{before.version}", f"v{after.version}", lineterm=""
    )
    return "\n".join(lines)


# --- The loop: the model and its tools, until it answers ----------------------------------------------


@tool
def get_weather(city: str) -> str:
    """The current weather in a city."""
    return f"Sunny and 21°C in {city}"  # a stand-in for a real weather API


TOOLS = {t.name: t for t in [get_weather]}
ITEMS = responses.Items()


async def use_tool(ctx: sessions.SessionContext, call: Call) -> str:
    found = TOOLS.get(call.name)
    if found is None:
        return f"Error: there is no tool named {call.name}"
    return await run_tool(found, call.input, ToolCall(ctx, call.id))


async def answer(ctx: sessions.SessionContext, text: str) -> str:
    """Answer a message: ask the model with the latest harness, and run the tools it calls, until it answers."""
    instructions = (await latest(ctx.db)).system  # read every turn: the agent may have changed it

    async def run(conversation: Conversation) -> str:
        if (final := conversation.final_reply()) is not None:
            return final  # a crash came after the final reply was stored, before the turn ended
        while True:
            # The tool calls that have no output yet: the last reply's, or those a crash cut short.
            for call in conversation.unanswered():
                await conversation.append(responses.output(call.id, await use_tool(ctx, call)))
            reply = await responses.complete(instructions, [e.item for e in conversation.entries], list(TOOLS.values()))
            await conversation.append_reply(*reply)  # stored before its tools run
            if not responses.calls_tools(reply):
                return conversation.final_reply() or ""

    return await answer_once(ctx, text, ITEMS, run)


learner = AgentObject("learner", migrations=MIGRATIONS)
learner.chat(answer, items=ITEMS)


# --- Improving itself ---------------------------------------------------------------------------------

REFLECT = """You improve the instructions (the harness) of an assistant, from its conversation with one user.
Find what the user corrected, asked for, or complained about, that should hold for every later answer:
length, format, tone, what to include or leave out. Rewrite the harness to include it, keeping what still
holds. Change nothing the conversation gives no reason to change. If there is nothing to learn, return
the harness as it is."""


class Revision(BaseModel):
    system: Annotated[str, Field(description="The harness, rewritten")]
    why: Annotated[str, Field(description="What in the conversation made it change, in a sentence or two")]


async def transcript(db: sessions.Database) -> str:
    """The conversation's messages, as text: the tool calls and reasoning left out."""
    conversation = await Conversation.load(db, ITEMS)
    return "\n".join(f"{e.said[0]}: {e.said[1]}" for e in conversation.entries if e.said is not None)


@learner.handler
async def reflect(ctx: sessions.SessionContext) -> Version:
    """Have the model rewrite the harness from what the user corrected: the agent improving itself."""
    if (stored := await stored_by(ctx.db, ctx.request.id)) is not None:
        return stored  # a retry: this request stored its version already, so the model isn't asked again
    current = await latest(ctx.db)
    said = await transcript(ctx.db)
    if not said:
        return current
    revision = await responses.parse(
        REFLECT, f"<harness>\n{current.system}\n</harness>\n\n<conversation>\n{said}\n</conversation>", Revision
    )
    if revision.system.strip() == current.system.strip():
        return current  # nothing to learn
    return await add(ctx, revision.system, revision.why)


@learner.handler
async def rollback(ctx: sessions.SessionContext, version: int) -> Version:
    """Go back to an earlier version, as a new one: the history keeps every change."""
    row = await ctx.db.get("SELECT system FROM harness WHERE version = ?", [version])
    if row is None:
        raise restate.TerminalError(f"There is no version {version}")
    return await add(ctx, str(row["system"]), f"Rolled back to version {version}.")


@learner.view
async def harness(ctx: sessions.ViewContext) -> History:
    """Every version of the harness, oldest first, each with what changed since the one before."""
    versions = [version_of(row) for row in await ctx.db.query(f"SELECT {COLUMNS} FROM harness ORDER BY version")]
    for before, after in itertools.pairwise(versions):
        after.diff = diff(before, after)
    return History(versions=versions)


app = restate.app([learner])
