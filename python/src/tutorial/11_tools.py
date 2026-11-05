"""
11 · Tools

A tool is a function the model can decide to call. ``@tool`` makes one of a
function: its name, its docstring and its parameters' types tell the model
what it is for and what to give it. A parameter named ``ctx`` isn't the
model's to fill in: it gets the wallet's ``ctx``, so the tool reads the same
database the conversation is stored in.

When a tool raises a ``TerminalError``, the model gets the error message as
the tool's answer, and can correct itself. Restate retries any other error,
as in any handler::

    curl localhost:8080/wallet11/alice/deposit --json '{"id": "d1", "amount": 40, "note": "salary"}'
    curl localhost:8080/wallet11/alice/deposit --json '{"id": "d2", "amount": -12, "note": "lunch"}'
    curl localhost:8080/wallet11/alice/chat -d 'How much do I have, and what did I spend money on?'
"""

from typing import Annotated

import restate
from pydantic import BaseModel, Field
from restate import sessions
from restate.agents import openai, tool


async def balance_of(db: sessions.DatabaseReader) -> int:
    row = await db.get("SELECT coalesce(sum(amount), 0) AS balance FROM entries")
    return int(row["balance"] or 0) if row else 0


async def history_of(db: sessions.DatabaseReader) -> list[sessions.Row]:
    return await db.query("SELECT amount, note FROM entries ORDER BY rowid")


@tool(name="balance")
async def balance_tool(ctx: sessions.SessionContext) -> int:
    """The current balance of the wallet."""
    return await balance_of(ctx.db)


@tool(name="history")
async def history_tool(
    ctx: sessions.SessionContext, count: Annotated[int, Field(description="How many entries, at most 100.")]
) -> list[sessions.Row]:
    """The latest entries of the wallet, newest first. Negative amounts are spending."""
    if count > 100:
        raise restate.TerminalError("At most 100 entries at a time")
    return list(reversed(await history_of(ctx.db)))[:count]


wallet = openai.agent(
    "wallet11",
    system="You are the assistant of the user's wallet. Keep your answers short.",
    tools=[balance_tool, history_tool],
    migrations=[
        "CREATE TABLE entries (amount INTEGER NOT NULL)",
        "ALTER TABLE entries ADD COLUMN note TEXT",
        "ALTER TABLE entries ADD COLUMN id TEXT",
        "CREATE UNIQUE INDEX entries_by_id ON entries (id)",
    ],
)


class Deposit(BaseModel):
    id: str
    amount: int
    note: str | None = None


@wallet.handler
async def deposit(ctx: sessions.SessionContext, money: Deposit) -> int:
    await ctx.db.execute(
        "INSERT OR IGNORE INTO entries (id, amount, note) VALUES (?, ?, ?)", [money.id, money.amount, money.note]
    )
    return await balance_of(ctx.db)


@wallet.view
async def balance(ctx: sessions.ViewContext) -> int:
    return await balance_of(ctx.db)


services = [wallet]
