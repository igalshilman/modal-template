"""
12 · A tool that moves money

Tools can write too. The ``transfer`` tool is lesson 08's transfer, taken out
of the handler into a function. Like any handler, ``chat`` may be retried,
and a crash in the middle of a tool call runs that tool call again. So a tool
that changes something needs an id that is the same each time it runs, just
like a handler (06). A parameter named ``idempotency_key`` gets one, made of
the request's id and the model's id for the tool call::

    curl localhost:8080/wallet12/alice/deposit --json '{"id": "d1", "amount": 100}'
    curl localhost:8080/wallet12/alice/chat -d 'Send 20 to bob for the pizza.'
    curl localhost:8080/wallet12/bob/history                              # ends with 20, from alice
    curl localhost:8080/wallet12/alice/chat -d 'Now send him a million.'  # the tool answers "Not enough money"
"""

import restate
from pydantic import BaseModel, PositiveInt
from restate import sessions
from restate.agents import openai, tool


class Deposit(BaseModel):
    id: str
    amount: int
    note: str | None = None


async def balance_of(db: sessions.DatabaseReader) -> int:
    row = await db.get("SELECT coalesce(sum(amount), 0) AS balance FROM entries")
    return int(row["balance"] or 0) if row else 0


async def transfer(ctx: sessions.SessionContext, transfer_id: str, to: str, amount: int) -> int:
    """Move ``amount`` to the wallet ``to``, once per ``transfer_id``, and return the balance left (08)."""
    async with ctx.db.transaction() as tx:
        if await tx.get("SELECT 1 FROM entries WHERE id = ?", [transfer_id]) is None:
            await tx.execute(
                "INSERT INTO entries (id, amount, note) VALUES (?, ?, ?)", [transfer_id, -amount, f"to {to}"]
            )
            if await balance_of(tx) < 0:
                raise restate.TerminalError("Not enough money")
            tx.send(deposit, Deposit(id=transfer_id, amount=amount, note=f"from {ctx.key}"), key=to)
        return await balance_of(tx)


@tool(name="transfer")
async def transfer_tool(ctx: sessions.SessionContext, idempotency_key: str, to: str, amount: PositiveInt) -> str:
    """Send money from the user's wallet to another wallet, by its owner's name."""
    left = await transfer(ctx, idempotency_key, to, amount)
    return f"Sent {amount} to {to}. The balance is now {left}."


@tool(name="balance")
async def balance_tool(ctx: sessions.SessionContext) -> int:
    """The current balance of the wallet."""
    return await balance_of(ctx.db)


wallet = openai.agent(
    "wallet12",
    system="You are the assistant of the user's wallet. Keep your answers short.",
    tools=[balance_tool, transfer_tool],
    migrations=[
        "CREATE TABLE entries (amount INTEGER NOT NULL)",
        "ALTER TABLE entries ADD COLUMN note TEXT",
        "ALTER TABLE entries ADD COLUMN id TEXT",
        "CREATE UNIQUE INDEX entries_by_id ON entries (id)",
    ],
)


@wallet.handler
async def deposit(ctx: sessions.SessionContext, money: Deposit) -> int:
    await ctx.db.execute(
        "INSERT OR IGNORE INTO entries (id, amount, note) VALUES (?, ?, ?)", [money.id, money.amount, money.note]
    )
    return await balance_of(ctx.db)


@wallet.view
async def balance(ctx: sessions.ViewContext) -> int:
    return await balance_of(ctx.db)


@wallet.view
async def history(ctx: sessions.ViewContext) -> list[sessions.Row]:
    return await ctx.db.query("SELECT amount, note FROM entries ORDER BY rowid")


services = [wallet]
