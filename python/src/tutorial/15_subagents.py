"""
15 · Agents that delegate

``subagent(coach)`` makes another agent a tool. The wallet's assistant hands
the coach a task with a name, and gets the coach's answer. Each task is a
conversation of the coach of its own, keyed by the wallet and the task's name
(such as ``coach15/alice.bike``), so the assistant can come back to it later,
and a crash anywhere resumes where it stopped::

    curl localhost:8080/wallet15/alice/chat -d 'I want the bike, 600, by June. Ask the coach for a plan.'
    curl localhost:8080/wallet15/alice/messages                           # the task it gave the coach, and the plan
"""

from pydantic import BaseModel
from restate import sessions
from restate.agents import openai, subagent, tool


async def balance_of(db: sessions.DatabaseReader) -> int:
    row = await db.get("SELECT coalesce(sum(amount), 0) AS balance FROM entries")
    return int(row["balance"] or 0) if row else 0


@tool(name="balance")
async def balance_tool(ctx: sessions.SessionContext) -> int:
    """The current balance of the wallet."""
    return await balance_of(ctx.db)


coach = openai.agent(
    "coach15",
    description="A savings coach. Give it a goal, a deadline and the current balance, and it answers with a plan.",
    system="You are a savings coach. Answer with a short, realistic plan: how much to put aside each week, and one tip.",
)

wallet = openai.agent(
    "wallet15",
    system="You are the assistant of the user's wallet. Keep your answers short.",
    tools=[balance_tool, subagent(coach)],
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


services = [wallet, coach]
