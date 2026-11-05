"""
14 · A person in the loop

Large transfers should wait until the owner confirms them in their app. A
``wait_for_signal`` tool waits for a value from outside, for as long as it
takes: no process is held while it waits, and a crash or a restart changes
nothing. ``pending`` lists what the agent is waiting for, and ``signal``
answers it. Both are views every agent has.

Here the model asks for the confirmation because the tools' descriptions tell
it to::

    curl localhost:8080/wallet14/alice/deposit --json '{"id": "d3", "amount": 200, "note": "salary"}'
    curl localhost:8080/wallet14/alice/chat/send -d 'Send 150 to bob for the rent.'
    curl localhost:8080/wallet14/alice/pending                                     # the confirmation it waits for
    curl localhost:8080/wallet14/alice/signal --json '{"name": "confirmation", "value": "confirmed"}'
    curl localhost:8080/wallet14/alice/messages                                    # the transfer, and the answer

``/send`` sends the message without waiting for the answer, which waits for
the confirmation.
"""

import restate
from pydantic import BaseModel, PositiveInt
from restate import sessions
from restate.agents import openai, tool, wait_for_signal


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
    """Send money from the user's wallet to another wallet, by its owner's name.

    A transfer over 100 needs a confirmation first.
    """
    left = await transfer(ctx, idempotency_key, to, amount)
    return f"Sent {amount} to {to}. The balance is now {left}."


class Confirmation(BaseModel):
    """The transfer to confirm, which ``pending`` shows."""

    to: str
    amount: int


confirmation = wait_for_signal(
    "confirmation",
    description='Ask the owner to confirm a transfer over 100 in their app, and wait for their answer: "confirmed" or "declined".',
    input=Confirmation,
)

wallet = openai.agent(
    "wallet14",
    system="You are the assistant of the user's wallet. Keep your answers short.",
    tools=[confirmation, transfer_tool],
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
