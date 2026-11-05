"""
03 · Views

Handlers of one key run one at a time, so their writes never race. The price
is that a slow handler makes every other request to that key wait. Reading
doesn't need to wait: a view runs as soon as it is called, even while a
handler of the same key is running, and reads what has been committed so far.
A view can't write::

    curl localhost:8080/wallet03/alice/deposit --json 20
    curl localhost:8080/wallet03/alice/balance           # 20
    curl localhost:8080/wallet03/alice/history           # every deposit, oldest first
"""

from restate import sessions

wallet = sessions.SessionObject("wallet03", migrations=["CREATE TABLE entries (amount INTEGER NOT NULL)"])


async def balance_of(db: sessions.DatabaseReader) -> int:
    """The sum of the entries. A ``DatabaseReader`` is any database you can read: a handler's, a view's or a transaction's."""
    row = await db.get("SELECT coalesce(sum(amount), 0) AS balance FROM entries")
    return int(row["balance"] or 0) if row else 0


@wallet.handler
async def deposit(ctx: sessions.SessionContext, amount: int) -> int:
    await ctx.db.execute("INSERT INTO entries (amount) VALUES (?)", [amount])
    return await balance_of(ctx.db)


@wallet.view
async def balance(ctx: sessions.ViewContext) -> int:
    return await balance_of(ctx.db)


@wallet.view
async def history(ctx: sessions.ViewContext) -> list[int]:
    return [int(row["amount"] or 0) for row in await ctx.db.query("SELECT amount FROM entries ORDER BY rowid")]


services = [wallet]
