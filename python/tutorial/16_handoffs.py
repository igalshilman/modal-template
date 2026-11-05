"""
16 · Appendix: an Agent of your own

``openai.agent(name, system=..., tools=...)`` builds an ``Agent`` of the
OpenAI Agents SDK for you. For more of the SDK, such as handoffs or
guardrails, give it an ``Agent`` of your own instead.

Here the assistant hands saving plans off to a coach. A handoff is not a
subagent (15): the coach takes over this turn of the wallet's own
conversation, and answers alice itself, rather than doing a task in a
conversation of its own and reporting back. The SDK's agents get Restate's
tools through ``openai.tools([...])``: the coach reads the balance with the
same tool as the assistant::

    curl localhost:8080/wallet16/alice/deposit --json '{"id": "d1", "amount": 120, "note": "birthday"}'
    curl localhost:8080/wallet16/alice/chat -d 'I want a bike, 600, by June. How do I get there?'   # the coach answers
    curl localhost:8080/wallet16/alice/messages                                                      # the handoff, and who answered
"""

from agents import Agent
from pydantic import BaseModel
from restate import sessions
from restate.agents import openai, tool


async def balance_of(db: sessions.DatabaseReader) -> int:
    row = await db.get("SELECT coalesce(sum(amount), 0) AS balance FROM entries")
    return int(row["balance"] or 0) if row else 0


@tool(name="balance")
async def balance_tool(ctx: sessions.SessionContext) -> int:
    """The current balance of the wallet."""
    return await balance_of(ctx.db)


coach = Agent(
    name="coach",
    handoff_description="A savings coach, for plans to save up for a goal.",
    instructions="You are a savings coach. Read the balance, then answer with a short, realistic plan: "
    "how much to put aside each week, and one tip.",
    tools=openai.tools([balance_tool]),
)

assistant = Agent(
    name="assistant",
    instructions="You are the assistant of the user's wallet. Keep your answers short. "
    "Hand plans to save up for something to the coach.",
    handoffs=[coach],
)

wallet = openai.agent(
    "wallet16",
    assistant,
    tools=[balance_tool],  # beside the assistant's own tools; the coach has its own (above)
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
