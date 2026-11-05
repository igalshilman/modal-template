"""
04 · Migrations: changing the tables

Once alice's database exists, editing its CREATE TABLE statement would change
nothing for her. That's why ``migrations`` is a list of steps: to change the
tables, add a step at the end. Each key's database runs the steps it hasn't
run yet, the next time it is used. Never edit or remove a step that may have
run somewhere; add a new one instead.

Here, deposits get a note. (``wallet04`` is new, so its databases run both
steps on first use; a wallet released before the note would run only the
second.)::

    curl localhost:8080/wallet04/alice/deposit --json '{"amount": 20}'
    curl localhost:8080/wallet04/alice/deposit --json '{"amount": 50, "note": "birthday"}'
    curl localhost:8080/wallet04/alice/history                                          # the first deposit has no note
"""

from pydantic import BaseModel
from restate import sessions

wallet = sessions.SessionObject(
    "wallet04",
    migrations=[
        "CREATE TABLE entries (amount INTEGER NOT NULL)",  # from lesson 02
        "ALTER TABLE entries ADD COLUMN note TEXT",  # new: runs once on each wallet's database
    ],
)


class Deposit(BaseModel):
    amount: int
    note: str | None = None


async def balance_of(db: sessions.DatabaseReader) -> int:
    row = await db.get("SELECT coalesce(sum(amount), 0) AS balance FROM entries")
    return int(row["balance"] or 0) if row else 0


@wallet.handler
async def deposit(ctx: sessions.SessionContext, money: Deposit) -> int:
    await ctx.db.execute("INSERT INTO entries (amount, note) VALUES (?, ?)", [money.amount, money.note])
    return await balance_of(ctx.db)


@wallet.view
async def balance(ctx: sessions.ViewContext) -> int:
    return await balance_of(ctx.db)


@wallet.view
async def history(ctx: sessions.ViewContext) -> list[sessions.Row]:
    return await ctx.db.query("SELECT amount, note FROM entries ORDER BY rowid")


services = [wallet]
