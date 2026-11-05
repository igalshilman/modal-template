"""
The app: notes per user, and an assistant that keeps them.

Each key of a session object (``alice``, ``bob``, …) has its own SQLite
database, ``ctx.db``, stored in Restate together with the object's state. The
assistant is an agent, a session object too: each user's conversation is kept
in its own database, and it takes notes by calling ``notes`` through Restate.

Run it with a Restate server on this machine (see README.md)::

    uv run app                                                  # serves `app` on PORT, 9080 by default
    curl localhost:8080/notes/alice/add --json '"Buy milk"'
    curl localhost:8080/notes/alice/list                        # ["Buy milk"]
    curl localhost:8080/assistant/alice/chat -d 'Remind me to call the bank.'
    curl localhost:8080/notes/alice/list                        # ["Buy milk", "Call the bank"]

Or chat with the assistant from a terminal, and see its tool calls as they happen::

    uv run python -m restate.agents chat assistant/alice

The assistant needs OPENAI_API_KEY. On Modal, the same ``app`` connects to
Restate Cloud instead (modal/on_modal.py): ``python -m restate connect app.__main__:app``,
or Restate Cloud calls it there (modal/on_modal_push.py):
``python -m restate serve app.__main__:app``.
"""

import asyncio

import restate
from restate import sessions
from restate.agents import call, openai

notes = sessions.SessionObject(
    "notes",
    # Creates each key's database. Each step runs once per key; append new ones later as needed.
    migrations=["CREATE TABLE notes (text TEXT NOT NULL)"],
)


@notes.handler
async def add(ctx: sessions.SessionContext, note: str) -> None:
    await ctx.db.execute("INSERT INTO notes (text) VALUES (?)", [note])


@notes.view(name="list")
async def list_notes(ctx: sessions.ViewContext) -> list[str]:
    """A view only reads, so it can run while ``add`` is writing."""
    return [str(row["text"]) for row in await ctx.db.query("SELECT text FROM notes ORDER BY rowid")]


def same_user(ctx: sessions.SessionContext) -> str:
    """The assistant of ``alice`` keeps the notes of ``alice``: the model doesn't pick the key."""
    return ctx.key


assistant = openai.agent(
    "assistant",
    system="You keep the user's notes. Write each note short, as a reminder. Keep your answers short.",
    tools=[
        # Handlers as tools: each call goes through Restate, once, however often `chat` is retried.
        call(add, description="Add a note.", key=same_user),
        call(list_notes, description="The user's notes, oldest first.", key=same_user),
    ],
)

app = restate.app([notes, assistant])

if __name__ == "__main__":
    asyncio.run(restate.serve(app))
