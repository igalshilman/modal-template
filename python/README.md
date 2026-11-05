# Restate on Modal: Python

A [Restate](https://restate.dev) app in Python that runs on [Modal](https://modal.com),
plus pointers to the libraries you can build on. Run every command below from this
directory, `python/`. The TypeScript version is in [`../typescript`](../typescript).

## A quick outline of the relevant resources

- **[Connecting your code to Restate & Modal](#connecting-your-code-to-restate--modal)**:
  run locally, connect to Restate Cloud, deploy on Modal.
- **[Agent SDK](#agent-sdk)** (`restate.agents`): a high-level agent SDK on session
  objects, with the OpenAI Agents SDK, LangGraph, Pydantic AI and Google ADK.
- **[Session Objects](#session-objects)** (`restate.sessions`): the Cloudflare Durable
  Objects / celld-like construct, with a SQLite database per key.

All of these are part of the Restate Python SDK
([`restate-sdk`](https://pypi.org/project/restate-sdk/)), and they are all Restate services,
so they mix freely and call each other with exactly-once RPC.

## Connecting your code to Restate & Modal

You need Python 3.13 and [uv](https://docs.astral.sh/uv/); `uv sync` installs everything
else. The demo app in [`app/__main__.py`](app/__main__.py) is a template / hello-world
example: a `notes` session object, and an `assistant` agent that keeps them (it needs
`OPENAI_API_KEY`).

```
python/
├── app/__main__.py         the app, deployed on Modal: `app = restate.app([...])`, then restate.serve
├── tutorial/               a wallet per user, from a database per key to agents: to read and copy from
├── examples/               complete examples, each ending with an ASGI app, `app`
├── modal/on_modal.py       the Modal app: one always-on container that connects app/ to Restate Cloud
└── modal/on_modal_push.py  the other way round: Restate Cloud calls app/ on a Modal endpoint
```

### Local Restate Server (OSS, for development)

```sh
uv sync
uv run app                                        # your services, on port 9080
npx @restatedev/restate-server                    # Restate, in another terminal (UI on localhost:9070)
npx @restatedev/restate@next deployments register http://localhost:9080
curl localhost:8080/notes/alice/add --json '"Buy milk"'
curl localhost:8080/notes/alice/list
uv run python -m restate.agents chat assistant/alice   # chat with the assistant, and watch its tool calls
```

Binaries and Docker images: [Restate 1.8.1](https://github.com/restatedev/restate/releases/tag/v1.8.1).

### Connecting a service to Restate Cloud

Sign in to [cloud.restate.dev](https://cloud.restate.dev) with your `@modal.com` email. You
are added to the Modal org, which can create environments on the smaller tiers for free.

Get a connect key from
[**Configure SDK -> Create connect key**](https://cloud.restate.dev/to/developers/integration#configure-sdk).
The SDK's `python -m restate connect` connects the same `app` to Restate Cloud, as the
deployment `notes-python-v1`, with the key from `RESTATE_CONNECT_KEY`:

```sh
uv sync
RESTATE_CONNECT_KEY=… uv run python -m restate connect app.__main__:app --name notes-python-v1
```

Once, [register `connect://notes-python-v1`](https://cloud.restate.dev/to/overview?register-deployment=connect://notes-python-v1)
in the Cloud UI (the app prints this link too), or with the CLI, once it is signed in
(`cloud login` also asks which environment to use):

```sh
npx @restatedev/restate@next cloud login
npx @restatedev/restate@next deployments register connect://notes-python-v1
```

Send requests from the [playground](https://cloud.restate.dev/to/overview?servicePlayground=notes),
or with the SDK's client (a dev dependency here) and an ingress key
([**Configure SDK -> Create ingress key**](https://cloud.restate.dev/to/developers/integration#configure-sdk)),
typed by the handlers themselves:

```python
import restate
from app.__main__ import add, list_notes  # the handlers of app/__main__.py

async with restate.create_client() as client:  # reads RESTATE_INGRESS_KEY
    await client.object_call(add, key="alice", arg="Buy milk")
    print(await client.object_call(list_notes, key="alice", arg=None))  # ["Buy milk"]
```

### Deploy on Modal

[`modal/on_modal.py`](modal/on_modal.py) builds the image on Modal and runs
`python -m restate connect app.__main__:app` in one always-on container, which connects to
Restate Cloud. Only `app/` goes into the image. Your keys come from a Modal secret, and
`modal` is a dev dependency of this project, so `uv run modal` runs it:

```sh
uv sync && uv run modal setup
uv run modal secret create restate-template RESTATE_CONNECT_KEY=… OPENAI_API_KEY=…
uv run modal deploy modal/on_modal.py
```

Register `connect://notes-python-v1` as above. `uv run modal app logs restate-template-python`
follows the app. Model API keys (such as `OPENAI_API_KEY`) go in the same secret. The image
installs the `[project] dependencies` of [`pyproject.toml`](pyproject.toml) at the versions of
`uv.lock`, and none of its groups (`dev`, `examples`): after adding one, run `uv lock`.

### Or let Restate Cloud call Modal

[`modal/on_modal_push.py`](modal/on_modal_push.py) runs the same `app` the other way round:
`python -m restate serve app.__main__:app` on a [Modal Server](https://modal.com/docs/guide/servers),
and Restate Cloud calls its URL over HTTP/2. Same image and secret (no `RESTATE_CONNECT_KEY`
needed), plus a Modal [proxy auth token](https://modal.com/settings/proxy-auth-tokens) so that
only Restate can call it:

```sh
uv run modal deploy modal/on_modal_push.py        # prints the app's URL
npx @restatedev/restate@next deployments register --force --yes \
  https://<workspace>--restate-template-python-push-app.us-east.modal.direct \
  --extra-header Modal-Key=wk-… --extra-header Modal-Secret=ws-…
```

Register the URL that `modal deploy` prints, again after each deploy.
`uv run modal app logs restate-template-python-push` follows the app.

## Agent SDK

`restate.agents` shows how to structure a high-level agent SDK on session objects. It adds
integrations for the OpenAI Agents SDK, LangGraph, Pydantic AI and Google ADK, and you can
also write an agent loop of your own. Each agent is a session object with its conversation
in its own database: a crash, a restart, or a person who takes a day to approve something
changes nothing, and each tool call is made once. Tools can be Restate itself (a call to a
service, a send with a delay, a workflow, another agent, a wait for a signal), and you can
still write workflows as plain Restate handlers and call other services.

```python
from restate.agents import openai, tool


@tool
async def get_weather(city: str) -> str:
    """The current weather in a city."""
    return f"Sunny and 21°C in {city}"


assistant = openai.agent("assistant", system="Answer briefly.", tools=[get_weather])
```

To serve agents, add them to `restate.app([...])` in [`app/__main__.py`](app/__main__.py).
Each brings along what it needs (the `signals` object its waits use). Put your model's API key
(`OPENAI_API_KEY`) in the environment, and on Modal in its secret. Chat with
`curl localhost:8080/assistant/alice/chat -d 'Hi'`, or from a terminal with
`uv run python -m restate.agents chat assistant/alice`. The chat client shows each tool call
as it happens, answers an agent's waits (`/pending`, `/signal <name> <value>`), and talks to
Restate Cloud when `RESTATE_INGRESS_KEY` is set.

The OpenAI Agents SDK is installed already (`restate-sdk[serve,openai]` in
[`pyproject.toml`](pyproject.toml)). For another framework, add its extra (`langgraph`,
`pydantic-ai`, `adk`) and its model provider's package, then `uv lock`.

### Examples

[`examples/`](examples): complete agents, each a module that ends with an ASGI app, `app`.
Serve one with the SDK's `python -m restate serve`, register it with your local Restate
server (`--force` when you switch from another), and try the requests in its docstring:

```sh
uv run python -m restate serve examples.chat:app
npx @restatedev/restate deployments register --force --yes http://localhost:9080
```

| Example                                          | What it shows                                                               |
| ------------------------------------------------ | --------------------------------------------------------------------------- |
| [`chat`](examples/chat.py)                       | A chat agent on the OpenAI Agents SDK, with a tool                          |
| [`langgraph_agent`](examples/langgraph_agent.py) | The same agent on LangGraph                                                 |
| [`models`](examples/models.py)                   | LangChain chat models you set up yourself: a gateway, no client retries     |
| [`memory`](examples/memory.py)                   | An agent with a table of its own: tools that write `ctx.db`, and a view     |
| [`support`](examples/support.py)                 | Restate as tools: a service, a person's approval (a signal), and a workflow |

They need `OPENAI_API_KEY`. LangGraph and `langchain-openai` are in the `examples` group of
`pyproject.toml`, which `uv sync` installs and the Modal image doesn't. Any example connects
to Restate Cloud too: `uv run python -m restate connect examples.chat:app --name chat-python-v1`.

More, one per file: [`examples-agents`](https://github.com/restatedev/sdk-python/tree/main/examples-agents)
of the Python SDK, from a basic agent per framework to agents whose tools are Restate itself,
a person in the loop, teams of agents on different frameworks, and an agent loop of your own.

To build your own harness, `restate.agents.internal` has the building blocks of the Agent
SDK's loop (`answer_once`, `Conversation`, `run_tool`), on an `AgentObject`.
[restatedev/agent](https://github.com/restatedev/agent) is an even more detailed reference, in
TypeScript: steerable, concurrent agents with approvals, sandboxed code, sub-agents, schedules
and memory.

## Session Objects

A session object is a virtual object with `migrations` and a database, `ctx.db`: the
Cloudflare Durable Objects / celld-like API. Each key (`alice`, `bob`, …) gets its own
SQLite-compatible database of up to 10 GiB, stored in Restate's state, so there is no separate
database to run. This is what powers the Agent SDK.

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

**Dependency:** part of [`restate-sdk`](https://pypi.org/project/restate-sdk/), from
[restatedev/sdk-python](https://github.com/restatedev/sdk-python). Docs: the docstrings of
`restate.sessions` and `restate.agents`, which an editor shows on hover.

**Tutorial:** [`tutorial/`](tutorial), one idea per file: a database per key (01–04),
changes that happen once (05–08), agents (09–15), and an `Agent` of your own with handoffs
(16). The lessons are for reading and copying: to try one, copy it into
[`app/__main__.py`](app/__main__.py) and add its objects to `restate.app([...])` there.
Lessons 09–16 need `OPENAI_API_KEY`.

