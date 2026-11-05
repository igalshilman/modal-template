"""
An agent with a memory

An assistant with a memory: the facts it learns about you go into a table of
its own SQL database, next to its conversation. Its tools write and read them
through ``ctx.db``, and a view of your own serves them, for a profile page
say::

    uv run python -m restate serve examples.memory:app
    curl localhost:8080/memory/alice/chat -d 'I am vegetarian, and I live in Lisbon.'
    curl localhost:8080/memory/alice/chat -d 'Suggest a restaurant for tonight.'
    curl localhost:8080/memory/alice/facts
    curl localhost:8080/memory/alice/forget --json '"The user lives in Lisbon."'   # a fact, as /facts shows it
"""

import restate
from restate import sessions
from restate.agents import openai, tool


async def facts_of(db: sessions.DatabaseReader) -> list[str]:
    return [str(row["fact"]) for row in await db.query("SELECT fact FROM facts ORDER BY rowid")]


@tool
async def remember(ctx: sessions.SessionContext, fact: str) -> str:
    """Remember a fact about the user, for this conversation and later ones."""
    # Safe to run twice: a fact is stored once.
    await ctx.db.execute("INSERT OR IGNORE INTO facts (fact) VALUES (?)", [fact])
    return f"Remembered: {fact}"


@tool
async def recall(ctx: sessions.SessionContext) -> list[str]:
    """Everything remembered about the user."""
    return await facts_of(ctx.db)


memory = openai.agent(
    "memory",
    system="You are a helpful assistant. Remember what you learn about the user, and recall it when it helps.",
    tools=[remember, recall],
    # Your own table, in each user's database next to the agent's tables.
    migrations=["CREATE TABLE facts (fact TEXT PRIMARY KEY)"],
)


@memory.handler
async def forget(ctx: sessions.SessionContext, fact: str) -> None:
    """Forget a fact. A handler of your own, beside the agent's ``chat``."""
    await ctx.db.execute("DELETE FROM facts WHERE fact = ?", [fact])


@memory.view
async def facts(ctx: sessions.ViewContext) -> list[str]:
    """What the assistant knows about the user. A view, so it answers even while the agent is busy."""
    return await facts_of(ctx.db)


app = restate.app([memory])
