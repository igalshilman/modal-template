"""
10 · An agent

``openai.agent(...)`` is an ``AgentObject`` that is an agent: its ``chat``
handler answers a message, and its ``messages`` view shows the conversation
so far. Give it the wallet's tables and handlers, and every wallet has an
assistant whose conversation is stored in that wallet's database, next to its
entries. Like any handler, ``chat`` answers one message per wallet at a time;
``messages`` is a view, so it answers even while the assistant is busy.

``chat`` takes the message as plain text (``-d``), and answers with a JSON
string. The assistant can't see the wallet yet: that is the next lesson::

    curl localhost:8080/wallet10/alice/chat -d 'Hi! I am saving up for a bike.'
    curl localhost:8080/wallet10/alice/chat -d 'What am I saving for?'     # it remembers
    curl localhost:8080/wallet10/bob/chat -d 'What am I saving for?'       # bob's wallet has a conversation of its own
    curl localhost:8080/wallet10/alice/messages                            # alice's conversation so far
"""

from pydantic import BaseModel
from restate import sessions
from restate.agents import openai

wallet = openai.agent(
    "wallet10",
    system="You are the assistant of the user's wallet. Keep your answers short.",
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
