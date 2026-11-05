"""
01 · A virtual object

Throughout this tutorial we build a wallet. Every user has one, and Restate
finds it by key: ``wallet01/alice`` and ``wallet01/bob`` are two instances of
the same object. Restate runs the requests for one key one at a time, so a
wallet never handles two of them at once.

Every lesson's objects carry its number (``wallet01``, ``wallet02``, …), so
all the lessons are served together. Include them in src/app.py (its comment
shows how: two lines to uncomment), run it, and call any lesson through Restate::

    curl localhost:8080/wallet01/alice/hello   # "Hello, alice!"
"""

from restate import sessions

# A session object: a virtual object that gets a database in the next lesson.
wallet = sessions.SessionObject("wallet01")


@wallet.handler
async def hello(ctx: sessions.SessionContext) -> str:
    # `ctx.key` is the key the request was sent to: the wallet's owner.
    return f"Hello, {ctx.key}!"


services = [wallet]
