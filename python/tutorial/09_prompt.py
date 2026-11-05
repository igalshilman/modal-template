"""
09 · A model in a handler

From here on, the wallet talks to a model, so it is an ``AgentObject`` of
``restate.agents``: a session object with what agents need set up, their
tables in the same database and a few built-in handlers you will meet in the
next lessons.

``openai.prompt(ctx, text)`` asks a model from a handler and returns the
answer. The prompt and the answer are stored in the wallet's database, so if
Restate retries the handler, the model isn't asked a second time.

Lessons 09 to 16 ask OpenAI's models, with your key in ``OPENAI_API_KEY``::

    curl localhost:8080/wallet09/alice/deposit --json '{"id": "d1", "amount": 40, "note": "salary"}'
    curl localhost:8080/wallet09/alice/deposit --json '{"id": "d2", "amount": -12, "note": "lunch"}'
    curl localhost:8080/wallet09/alice/summary                                                      # a few words on alice's money
"""

import json

from pydantic import BaseModel
from restate import sessions
from restate.agents import AgentObject, openai

wallet = AgentObject(
    "wallet09",
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


async def balance_of(db: sessions.DatabaseReader) -> int:
    row = await db.get("SELECT coalesce(sum(amount), 0) AS balance FROM entries")
    return int(row["balance"] or 0) if row else 0


async def history_of(db: sessions.DatabaseReader) -> list[sessions.Row]:
    return await db.query("SELECT amount, note FROM entries ORDER BY rowid")


@wallet.handler
async def deposit(ctx: sessions.SessionContext, money: Deposit) -> int:
    await ctx.db.execute(
        "INSERT OR IGNORE INTO entries (id, amount, note) VALUES (?, ?, ?)", [money.id, money.amount, money.note]
    )
    return await balance_of(ctx.db)


@wallet.handler
async def summary(ctx: sessions.SessionContext) -> str:
    entries = json.dumps(await history_of(ctx.db))
    return await openai.prompt(
        ctx,
        f"These are the entries of a wallet, oldest first; negative amounts are spending.\n{entries}\n"
        "Describe them to the owner in two short sentences.",
    )


@wallet.view
async def balance(ctx: sessions.ViewContext) -> int:
    return await balance_of(ctx.db)


@wallet.view
async def history(ctx: sessions.ViewContext) -> list[sessions.Row]:
    return await history_of(ctx.db)


services = [wallet]
