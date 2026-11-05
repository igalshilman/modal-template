"""
01 · A virtual object

Throughout this tutorial we build a wallet. Every user has one, and Restate
finds it by key: ``wallet01/alice`` and ``wallet01/bob`` are two instances of
the same object. Restate runs the requests for one key one at a time, so a
wallet never handles two of them at once.

The lessons are for reading and copying, not served on their own. To try one,
copy it into app/__main__.py and add its objects (the ``services`` at the end
of each lesson) to ``restate.app([...])`` there. Each lesson's objects carry
its number (``wallet01``, ``wallet02``, …), so several can sit in the app side
by side.
Run the app (``uv run app``) and call the lesson through Restate::

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
