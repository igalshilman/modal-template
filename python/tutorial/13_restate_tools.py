"""
13 · Handlers as tools

A handler or a view of any Restate object can be a tool, without writing a
function: ``call(owner, description=...)`` lets the model look up who owns a
handle (07). The model picks the key, here the handle's name, and the agent
calls it through Restate: once, however often ``chat`` is retried.

With it, alice can pay friends by their handle::

    curl localhost:8080/wallet13/alice/deposit --json '{"id": "d1", "amount": 100}'
    curl localhost:8080/handle13/bobby/claim --json '"bob"'               # bob claims @bobby
    curl localhost:8080/wallet13/alice/chat -d 'Send 15 to @bobby for the tickets.'
    curl localhost:8080/wallet13/alice/messages                           # the lookup, then the transfer
"""

import restate
from pydantic import BaseModel, PositiveInt
from restate import sessions
from restate.agents import call, openai, tool

handle = sessions.SessionObject("handle13", migrations=["CREATE TABLE owner (wallet TEXT NOT NULL)"])


@handle.handler
async def claim(ctx: sessions.SessionContext, wallet: str) -> str:
    await ctx.db.execute("INSERT INTO owner (wallet) SELECT ? WHERE NOT EXISTS (SELECT 1 FROM owner)", [wallet])
    owner = await ctx.db.get("SELECT wallet FROM owner")
    assert owner is not None  # the insert above made sure there is one
    return str(owner["wallet"])


@handle.view
async def owner(ctx: sessions.ViewContext) -> str | None:
    row = await ctx.db.get("SELECT wallet FROM owner")
    return str(row["wallet"]) if row else None


class Deposit(BaseModel):
    id: str
    amount: int
    note: str | None = None


async def balance_of(db: sessions.DatabaseReader) -> int:
    row = await db.get("SELECT coalesce(sum(amount), 0) AS balance FROM entries")
    return int(row["balance"] or 0) if row else 0


async def transfer(ctx: sessions.SessionContext, transfer_id: str, to: str, amount: int) -> int:
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
    """Send money from the user's wallet to another wallet, by its owner's name (not a handle)."""
    left = await transfer(ctx, idempotency_key, to, amount)
    return f"Sent {amount} to {to}. The balance is now {left}."


owner_tool = call(
    owner, description='The owner of a handle: for @bobby, call it with the key "bobby". Null if nobody has it.'
)

wallet = openai.agent(
    "wallet13",
    system="You are the assistant of the user's wallet. Keep your answers short.",
    tools=[owner_tool, transfer_tool],
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


services = [wallet, handle]
