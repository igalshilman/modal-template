"""
A demo app: notes per user.

Each key of a session object (``alice``, ``bob``, …) has its own SQLite
database, ``ctx.db``, stored in Restate together with the object's state.
"""

import asyncio

import restate
from restate import sessions

# from tutorial import tutorial  # the tutorial: see `services` below

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


services: list[restate.VirtualObject | restate.Service | restate.Workflow] = [notes]
# To try the tutorial (src/tutorial), uncomment the line below and the import of `tutorial` at
# the top. Lessons 09 to 16 also need OPENAI_API_KEY.
# services += tutorial

if __name__ == "__main__":
    asyncio.run(restate.connect(sessions.app(*services), name="notes-python-v1"))
    # To run locally, with a Restate server on this machine, use this instead:
    # asyncio.run(restate.serve(sessions.app(*services)))  # on PORT, 9080 by default
