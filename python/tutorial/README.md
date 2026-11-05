# The tutorial

A wallet per user, from a SQL database per key to agents, one idea per lesson. The docstring
at the top of each lesson explains its idea, and lists the requests to try it.

The lessons are for reading and copying. None of them is served on its own. To try one, copy
it into [`app/__main__.py`](../app/__main__.py), add its objects to `restate.app([...])` there (each
lesson ends with its `services`), and run the app with `uv run app`. Every lesson's objects
carry its number (`wallet01` … `wallet16`, `handle07`, `coach15`, …), so several lessons can
sit in the app side by side.

**Part 1 · A database per key**

- [01 · A virtual object](01_object.py)
- [02 · A database per key](02_database.py)
- [03 · Views](03_views.py)
- [04 · Migrations: changing the tables](04_migrations.py)

**Part 2 · Changes that happen once**

- [05 · Transactions](05_transaction.py)
- [06 · Retries](06_retries.py)
- [07 · Calling another object](07_calls.py)
- [08 · Sends that commit with the transaction](08_sends.py)

**Part 3 · Agents**: these ask OpenAI's models, with your key in `OPENAI_API_KEY`.

- [09 · A model in a handler](09_prompt.py)
- [10 · An agent](10_agent.py)
- [11 · Tools](11_tools.py)
- [12 · A tool that moves money](12_tool_writes.py)
- [13 · Handlers as tools](13_restate_tools.py)
- [14 · A person in the loop](14_approval.py)
- [15 · Agents that delegate](15_subagents.py)

**Appendix**

- [16 · An Agent of your own](16_handoffs.py): an `Agent` of the OpenAI Agents SDK, with handoffs.
