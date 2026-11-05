# Restate on Modal: Python

A [Restate](https://restate.dev) app in Python that runs on [Modal](https://modal.com), plus
pointers to the libraries you can build on. Run every command below from this directory,
`python/`. The TypeScript version is in [`../typescript`](../typescript).

## A quick outline of the relevant resources

- **[Connecting your code to Restate & Modal](#connecting-your-code-to-restate--modal)**:
  run locally, connect to Restate Cloud, deploy on Modal.
- **[Agents](#agents)** (`restate.agents`): durable agents on session objects, with the
  OpenAI Agents SDK, LangGraph, Pydantic AI and Google ADK, or a loop of your own.
- **[Session Objects](#session-objects)** (`restate.sessions`): the Cloudflare Durable
  Objects / celld-like construct, with a SQLite database per key.

All of these are part of the Restate Python SDK
([`restate-sdk`](https://pypi.org/project/restate-sdk/)), and they are Restate services, so
they mix freely with its services, virtual objects and workflows, and call each other with
exactly-once RPC.

## Connecting your code to Restate & Modal

You need Python 3.13 and [uv](https://docs.astral.sh/uv/). The demo app in
[`src/app.py`](src/app.py) is a template / hello-world example.

### Local Restate Server (OSS, for development)

In [`src/app.py`](src/app.py), swap `restate.connect(…)` for the `restate.serve(…)` line in
its comment. Then:

```sh
uv sync
uv run src/app.py                                 # your services, on port 9080
npx @restatedev/restate-server@1.8.1              # Restate, in another terminal (UI on localhost:9070)
npx @restatedev/restate@1.8.1 deployments register http://localhost:9080
curl localhost:8080/notes/alice/add --json '"Buy milk"'
curl localhost:8080/notes/alice/list
```

Binaries and Docker images: [Restate 1.8.1](https://github.com/restatedev/restate/releases/tag/v1.8.1).

### Connecting a service to Restate Cloud

Sign in to [cloud.restate.dev](https://cloud.restate.dev) with your `@modal.com` email. You
are added to the Modal org, which can create environments on the smaller tiers for free.

Get a connect key from
[**Configure SDK -> Create connect key**](https://cloud.restate.dev/to/developers/integration#configure-sdk).
`restate.connect` at the end of [`src/app.py`](src/app.py) reads it from `RESTATE_CONNECT_KEY`
and connects as the deployment `notes-python-v1`:

```sh
uv sync
RESTATE_CONNECT_KEY=… uv run src/app.py
```

Once, [register `connect://notes-python-v1`](https://cloud.restate.dev/to/overview?register-deployment=connect://notes-python-v1)
in the Cloud UI, or with the CLI:

```sh
npx @restatedev/restate@1.8.1-hotfix.2 deployments register connect://notes-python-v1
```

Send requests from the [playground](https://cloud.restate.dev/to/overview?servicePlayground=notes),
or with the SDK's client (a dev dependency here) and an ingress key
([**Configure SDK -> Create ingress key**](https://cloud.restate.dev/to/developers/integration#configure-sdk)),
typed by the handlers themselves:

```python
import restate
from app import add, list_notes  # the handlers of src/app.py

async with restate.create_client() as client:  # reads RESTATE_INGRESS_KEY
    await client.object_call(add, key="alice", arg="Buy milk")
    print(await client.object_call(list_notes, key="alice", arg=None))  # ["Buy milk"]
```

### Deploy on Modal

[`modal/on_modal.py`](modal/on_modal.py) builds the image on Modal and runs `src/app.py` in one
always-on container, which connects to Restate Cloud[^push]. Your keys come from a Modal secret.
`modal` is a dev dependency of this project, so `uv run modal` runs it:

```sh
uv sync && uv run modal setup
uv run modal secret create restate-template RESTATE_CONNECT_KEY=${RESTATE_CONNECT_KEY}
uv run modal deploy modal/on_modal.py
```

Register `connect://notes-python-v1` as above. `uv run modal app logs restate-template-python`
follows the app. Model API keys (such as `OPENAI_API_KEY`) go in the same secret. The image
installs the dependencies of [`pyproject.toml`](pyproject.toml) at the versions of `uv.lock`:
after adding one, run `uv lock`.

[^push]:
    **Why not "push" to Modal?** We suspect an edge case with long-lived HTTP/2 connections
    between Restate Cloud and Modal, possibly an interaction between HTTP clients and API
    gateways or load balancers: longer-running functions sometimes get stuck. While we
    investigate, and to save you the friction, your code connects to Restate Cloud instead
    of Restate Cloud pushing to Modal. Push is what we want in the future.

## Agents

`restate.agents` runs agents of the OpenAI Agents SDK, LangGraph, Pydantic AI or Google ADK
on session objects. Each agent is a session object, with each conversation (key) in its own
database: a crash, a restart, or a person who takes a day to approve something changes
nothing, and each tool call is made once. Tools can be Restate itself: a call to a service, a
one-way send with a delay, a workflow, another agent, or a wait for a signal.

```python
from restate.agents import openai, tool


@tool
async def get_weather(city: str) -> str:
    """The current weather in a city."""
    return f"Sunny and 21°C in {city}"


assistant = openai.agent("assistant", system="Answer briefly.", tools=[get_weather])
```

To serve agents, add them to `services` in [`src/app.py`](src/app.py) (`sessions.app` adds
what they need beside them), and put your model's API key (`OPENAI_API_KEY`) in the
environment, and on Modal in its secret. Chat with one with
`curl localhost:8080/assistant/alice/chat -d 'What is the weather in Lisbon?'`. The
OpenAI Agents SDK is installed already (`restate-sdk[serve,openai]` in
[`pyproject.toml`](pyproject.toml)); for another framework, add its extra (`langgraph`,
`pydantic-ai`, `adk`) and its model provider's package, then `uv lock`.

The tutorial's agents (lessons 09–16, below) are a walk through all of this, on the OpenAI
Agents SDK.

More examples, one per file: [`examples-agents`](https://github.com/restatedev/sdk-python/tree/main/examples-agents)
of the Python SDK, from a basic agent per framework to agents whose tools are Restate itself,
a person in the loop, teams of agents on different frameworks, and an agent loop of your own.

## Session Objects

A session object is a virtual object with `migrations` and a database, `ctx.db`: the
Cloudflare Durable Objects / celld-like API. Each key (`alice`, `bob`, …) gets its own
SQLite-compatible database of up to 10 GiB, stored in Restate's state, so there is no separate
database to run. This is what agents are built on.

```python
from restate import sessions

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
```

- Handlers run one at a time per key and are the only ones that write. Views read committed
  data at any time.
- `async with ctx.db.transaction() as tx:` commits several statements at once; `tx.send`
  messages go out only if it commits.
- No journal replay: after a failure the handler runs again from the start, so make it safe
  to run twice (for example, record `ctx.request.id` with its writes).

**Tutorial:** [`src/tutorial`](src/tutorial), one idea per file: a database per key (01–04),
changes that happen once (05–08), agents (09–15), and an `Agent` of your own with handoffs
(16). To run it, uncomment the two lines below `services = [notes]` in
[`src/app.py`](src/app.py). Lessons 09–16 need `OPENAI_API_KEY`.
