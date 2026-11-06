---
name: building-restate-services
description: >
  Design, build, run and test Restate services in the Python project (python/): session
  objects with a SQL database per key (restate.sessions), durable AI agents on them
  (restate.agents: OpenAI Agents SDK, LangGraph, Pydantic AI, Google ADK, or a loop of your
  own), and journaled Restate services, virtual objects and workflows (restate). Use when
  the user mentions Restate, session objects, SessionObject, ctx.db, durable agents, virtual
  objects, workflows, durable execution, or edits app/, tutorial/ or examples/.
---

# Restate in this project

Restate is a durable execution runtime: services run behind a Restate Server (ingress on
port 8080, admin and UI on 9070), which retries them through crashes. This project uses
**two execution models side by side**, and their rules contradict each other. **Before
writing or changing a handler, decide which model it uses, and follow only that model's
rules.**

If another Restate skill is loaded too (such as the restatedev plugin's own
`building-restate-services`), its mandatory rules, `ctx.run_typed` around every side effect,
`restate.gather` instead of `asyncio.gather`, and replay tests, are for journaled handlers
only. For session objects and agents, this skill's rules take precedence: never suggest
`ctx.run`, `ctx.sleep`, `ctx.get`/`ctx.set` or awakeables there.

## Step 1: which model is this handler?

|                                      | **Session object**                                                                                                                                       | **Journaled handler**                                                                         |
| ------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------- |
| Defined with                         | `sessions.SessionObject(...)` of `restate.sessions`; `openai.agent(...)`, `langgraph.agent(...)`, `pydantic_ai.agent(...)`, `adk.agent(...)`, `AgentObject(...)` of `restate.agents` | `restate.Service(...)`, `restate.VirtualObject(...)`, `restate.Workflow(...)`                 |
| Handlers                             | `@obj.handler` (one at a time per key, writes) and `@obj.view` (beside them, reads)                                                                     | `@svc.handler()`, `@wf.main()`                                                                |
| Context                              | `sessions.SessionContext`, `sessions.ViewContext`                                                                                                       | `restate.Context`, `restate.ObjectContext`, `restate.WorkflowContext`, ...                     |
| After a failure                      | Runs again **from its first line**, against its database. No journal replay                                                                              | **Replays its journal**: completed steps return their recorded results                         |
| State                                | `ctx.db`: a SQL database per key                                                                                                                         | `ctx.get` / `ctx.set` key/value state                                                          |
| Side effects                         | Directly; make them safe to run twice (stable ids such as `ctx.request.id`, idempotency keys)                                                            | Inside `ctx.run_typed(...)`                                                                    |
| Concurrency                          | `asyncio.gather` / `asyncio.wait` are fine                                                                                                               | `restate.gather`, `restate.select`, `restate.as_completed`; never `asyncio` combinators        |
| Time, random, ids                    | Allowed, but never as idempotency ids                                                                                                                    | Only `await ctx.time()`, `ctx.random()`, `ctx.uuid()`                                          |
| Timers, awakeables, durable promises | Not available: a delayed `ctx.send(..., delay=...)` for later work, a `wait_for_signal` tool for an agent's wait, a journaled workflow for the rest       | `ctx.sleep`, `ctx.awakeable`, `ctx.promise`                                                   |
| Calls                                | `await ctx.call(handler, arg, key=..., idempotency_key=...)`, `ctx.send(...)`, `tx.send(...)`; `generic_call` / `generic_send` by name                   | `ctx.service_call`, `ctx.object_call`, `ctx.workflow_call` and their `_send` variants          |
| Testing rule                         | Show that a handler run twice does its work once                                                                                                         | A replaying test (the project has no test setup yet: ask before adding one)                    |

**For new code, choose the type first.** In short:

- **An AI agent or LLM conversation**: `restate.agents` (`openai.agent(...)` or another
  framework's `agent(...)`). Add handlers of your own beside `chat` with `@agent.handler`, and
  ask a model once from one with `pydantic_ai.prompt(ctx, text)`.
- **Data per key that you insert, update and query** (a list, a history, a ledger, a cart):
  a **session object**.
- **A process with a start and an end that waits** (for a person, a callback, a timer), once
  per id: a **workflow**.
- **A few values per key, with timers or awakeables inside the handlers**: a **virtual
  object**. **No state per key**: a **service**.
- All of them live in one deployment and call each other. A file can hold several: decide
  per handler, never per file.

Never carry a rule across: don't wrap `ctx.db` in `ctx.run_typed` (a session object has no
`ctx.run`), and don't use `asyncio.gather` in a journaled handler.

## Step 2: the project

- `app/__main__.py` is the application, and the only folder deployed on Modal: its services
  go in `app = restate.app([...])`, the ASGI app, and it ends with
  `restate.serve(app)` under `if __name__ == "__main__"`. `uv run app` serves it on `PORT`
  (9080 by default); `python -m restate connect app.__main__:app --name notes-python-v1`
  connects the same `app` to Restate Cloud, which is what Modal runs (`modal/on_modal.py`;
  `modal/on_modal_push.py` runs `python -m restate serve app.__main__:app` instead, for
  Restate Cloud to call). Don't add a `connect` call or a switch to the file.
- `restate.app([...])` serves everything: services, virtual objects, workflows, session
  objects and agents. An agent brings along what it needs (the `signals` object its tools
  wait on), served once however many agents there are. Anything with a
  `__restate_services__()` method (`restate.Servable`) can be listed, such as a group of
  services.
- `tutorial/`: the tutorial, one idea per lesson, for reading and copying into
  `app/__main__.py`; nothing serves it, and it has no `__init__.py`. Each lesson ends with its
  `services`. Lessons 01–08 are session objects; 09–15 agents on the OpenAI Agents SDK
  (`openai.prompt`, `openai.agent`, `@tool`, tools that write, `call`, `wait_for_signal`,
  `subagent`), and 16 an `Agent` of the SDK of your own, with handoffs. Read the closest
  lesson before writing similar code; list a new one in `tutorial/README.md`.
- `examples/`: complete examples, one module each, ending with `app = restate.app([...])`:
  `chat` (OpenAI Agents SDK), `langgraph_agent`, `models` (LangChain chat models of your
  own), `memory` (an agent with a table of its own) and `support` (a service, a workflow and
  a signal as tools). `uv run python -m restate serve examples.<name>:app`
  serves one on this machine. Their extra dependencies are in the `examples` group of
  `pyproject.toml`, which Modal doesn't install.
- From `python/`: check with `uv run ruff check && uv run ruff format --check && uv run pyright` (strict),
  and format with `uv run ruff format`.
- To run it locally, connect it to Restate Cloud, or deploy it on Modal: the
  **deploying-on-modal** skill.
- The examples call a local server, `curl localhost:8080/…`. On Restate Cloud, the same paths
  work at your environment's ingress (`https://<environment id>.env.<region>:8080`) with
  `-H "Authorization: Bearer <ingress API key>"`: see deploying-on-modal, "Calling handlers".

## Session objects (`restate.sessions`)

```python
from pydantic import BaseModel

import restate
from restate import sessions

wallet = sessions.SessionObject(
    "wallet",
    migrations=[
        "CREATE TABLE entries (id TEXT UNIQUE, amount INTEGER NOT NULL)",
        # Append steps later; never edit or remove one that has run.
    ],
)


class Transfer(BaseModel):
    to: str
    amount: int


@wallet.handler
async def deposit(ctx: sessions.SessionContext, amount: int) -> None:
    # ctx.request.id is the same on every attempt: a retry inserts nothing new.
    await ctx.db.execute("INSERT OR IGNORE INTO entries (id, amount) VALUES (?, ?)", [ctx.request.id, amount])


@wallet.handler
async def transfer(ctx: sessions.SessionContext, money: Transfer) -> None:
    async with ctx.db.transaction() as tx:  # commits when the body ends, rolls back if it raises
        if await tx.get("SELECT 1 FROM entries WHERE id = ?", [ctx.request.id]) is None:
            await tx.execute("INSERT INTO entries (id, amount) VALUES (?, ?)", [ctx.request.id, -money.amount])
            row = await tx.get("SELECT coalesce(sum(amount), 0) AS balance FROM entries")
            if row is not None and int(row["balance"] or 0) < 0:
                raise restate.TerminalError("Not enough money")  # not retried; rolls back
            tx.send(deposit, money.amount, key=money.to)  # delivered only if the transaction commits


@wallet.view
async def balance(ctx: sessions.ViewContext) -> int:
    row = await ctx.db.get("SELECT coalesce(sum(amount), 0) AS b FROM entries")
    return int(row["b"] or 0) if row else 0
```

- `ctx.db` (`Database`): `execute`, `query` (rows as dicts), `get` (first row or `None`),
  `values`, `query_columns`, and `transaction()`. Each statement outside a transaction
  commits on its own. Inside `async with ctx.db.transaction() as tx`, use `tx`, never
  `ctx.db`. A helper that only reads takes a `sessions.DatabaseReader`, so it works with a
  handler's, a view's and a transaction's database.
- The database is SQLite-compatible (Turso's engine), stored in the object's Restate state.
  SQL expressions need `AS` to name their column.
- Handlers run one at a time per key; a view runs at once, reads what was committed when it
  started, can't write or send, and may call.
- `ctx.key`, `ctx.request.id` (stable across attempts), `ctx.cancel(invocation_id)`.
- `ctx.call(handler, arg, key=, idempotency_key=)` is typed by the handler function and is
  made right away, awaited or not. A call that changes something needs an idempotency key
  that is the same on every attempt (`f"{ctx.request.id}:claim"`). `ctx.send(..., delay=)`
  is one-way; `tx.send` goes out with its transaction's commit.
- Two session objects that call each other and wait can deadlock (each runs one request at a
  time per key): send instead.
- Handler inputs and outputs are JSON; Pydantic models work as both.

## Agents (`restate.agents`)

```python
from restate.agents import call, openai, subagent, tool, wait_for_signal


@tool
async def get_weather(city: str) -> str:
    """The current weather in a city."""  # the docstring is the tool's description
    return f"Sunny and 21°C in {city}"


assistant = openai.agent(
    "assistant",
    system="Answer briefly.",
    tools=[
        get_weather,
        call(status, description="The status of an order."),  # a Restate handler as a tool
        wait_for_signal("approval", description="Wait for a manager's approval.", input=Refund),
        subagent(researcher),  # another agent as a tool
    ],
)
```

- Every framework's `agent(name, ..., model=, system=, tools=, **options)` returns an
  `AgentObject`: a session object whose key is a conversation, stored in its database.
  `openai` (OpenAI Agents SDK), `langgraph`, `pydantic_ai` and `adk` each need their extra
  (`restate-sdk[openai]`, ...) and their model provider's package.
- The model is `"<provider>/<model-id>"`, else `$RESTATE_AGENT_MODEL`. `system`, `model` and
  `tools` may be functions of the context, for values per user.
- Tools: `@tool` for your own functions (typed parameters, docstring); `call`, `send`
  (with `delay=`), `workflow`, `subagent` and `wait_for_signal`, built on Restate, work with
  every framework. A tool may run again after a crash mid-call: make it safe to run twice
  (a tool function's `idempotency_key` parameter).
- Built-in handlers and views of every agent: `chat` (takes plain text: `curl -d 'Hi'`),
  `messages`, `status`, `pending`, `signal`, `stop`, `clear`, `sync`, `watch`,
  `notifications`. These names are reserved.
- Resolve a wait: `curl localhost:8080/assistant/alice/signal --json '{"name": "approval", "value": "approved"}'`.
- Follow an agent from a terminal: `uv run python -m restate.agents chat assistant/alice`
  (needs the `client` extra).
- An agent loop of your own, with no framework: `restate.agents.internal`
  (`answer_once`, `Conversation`, `run_tool`) on an `AgentObject`.

## Where to read more

| Task                                                                    | Where                                                                                                         |
| ----------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| Everything about session objects                                        | The docstrings of `restate.sessions` (`.venv/lib/python3.13/site-packages/restate/sessions/__init__.py`, `_api.py`) |
| Everything about agents, a framework's options                          | The docstrings of `restate.agents` and of its framework's subpackage (`restate/agents/openai/__init__.py`, ...) |
| Examples of agents: Restate tools, signals, subagents, routers, loops   | https://github.com/restatedev/sdk-python/tree/main/examples-agents                                            |
| Journaled services, objects and workflows                               | https://docs.restate.dev (Python SDK), and `restate/context.py`                                               |
| Server configuration, deployment, advanced topics                       | https://docs.restate.dev (or the `restate-docs` MCP server at https://docs.restate.dev/mcp, if configured)    |

## Restate CLI

Operate a running Restate Server with the CLI (`npx @restatedev/restate@1.8.1 …`, or
`restate` if installed): register deployments, inspect and manage invocations, read state,
query the server with SQL. It describes itself, so ask it instead of guessing:

- `restate --help`, `restate <command> --help`, and `restate search <what you want to do>`.
- `restate sql --help` lists the introspection tables; `restate sql describe <table>`.
- Always pass `--json`. A command that changes something (register, cancel, kill, purge,
  state edits) prints its plan with `"applied": false` and exits with code 3: show the plan
  to the user, and only then run it again with `--yes`.
- `restate whoami --json` says which server it talks to (by default `localhost:9070`).

## Before finishing

- Session objects and agents:
  - [ ] Every handler is safe to run twice: stable ids (`ctx.request.id`, a caller's id),
        `INSERT OR IGNORE`, idempotency keys on calls that change something
  - [ ] Writes that belong together are in one `transaction()`, and its sends are `tx.send`
  - [ ] Migrations only appended to, never edited
  - [ ] No `ctx.run`, `ctx.sleep`, `ctx.get`/`ctx.set` or awakeables
- Journaled handlers:
  - [ ] Side effects, external I/O and database calls inside `ctx.run_typed`; no Restate
        context operation inside a `run` callback
  - [ ] No `time.time()`, `random`, `asyncio.sleep` or `uuid4()`: `ctx.time()`,
        `ctx.random()`, `ctx.sleep()`, `ctx.uuid()`
  - [ ] `restate.gather` / `restate.select`, not `asyncio` combinators
  - [ ] `TerminalError` for failures that must not be retried
  - [ ] No deadlock cycles between virtual objects calling each other
- Always: lint passes, the service is in `restate.app([...])` in `app/__main__.py` (or an
  example's `app`), and it was called
  through Restate (curl, the playground, or the UI).
