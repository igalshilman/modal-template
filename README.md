# Restate on Modal: Starter Kit

A [Restate](https://restate.dev) app that runs on [Modal](https://modal.com) and connects to
[Restate Cloud](https://cloud.restate.dev), plus a tutorial and pointers to the libraries
you can build on. It comes in two languages, each a complete project of its own: pick one,
and follow its README.

| Project                        | Language                 | Run it with     | Built on                                                                                |
| ------------------------------ | ------------------------ | --------------- | --------------------------------------------------------------------------------------- |
| [`typescript/`](typescript)    | TypeScript, on Node 24   | pnpm            | `@restatedev/sessions`, `@restatedev/agents` (pi, OpenCode, LangGraph, Claude, DeepSeek) |
| [`python/`](python)            | Python 3.13              | uv              | `restate-sdk`: `restate.sessions`, `restate.agents` (OpenAI Agents SDK, LangGraph, Pydantic AI, Google ADK) |

Both have the same shape:

```
<language>/
├── README.md        how to run it locally, connect it to Restate Cloud, deploy it on Modal
├── AGENTS.md        instructions for coding agents (CLAUDE.md points to it)
├── .agents/skills/  skills for coding agents: building Restate services, deploying on Modal
├── <the app>        notes per user, a session object with a SQL database per key
├── <the tutorial>   a wallet per user, from a database per key to agents
└── modal/on_modal.py  the Modal app: one always-on container that runs the app
```

In TypeScript, the app is `src/app.ts` and the tutorial `src/tutorial/`. In Python, the app
is `app/__main__.py` (with an assistant beside the notes), the tutorial `tutorial/`, and
`examples/` holds complete examples, each ending with an ASGI app; only `app/` is deployed.

## What's in it

- **Session objects**: the Cloudflare Durable Objects / celld-like construct. Each key of a
  session object (`alice`, `bob`, …) gets its own SQLite-compatible database, stored in
  Restate's state, so there is no separate database to run. Handlers run one at a time per
  key; views read at any time; after a failure a handler runs again from its first line.
- **Agents**: durable agents on session objects, each conversation in its key's database.
  A crash, a restart, or a person who takes a day to approve something changes nothing, and
  tools can be Restate itself: calls, sends with a delay, workflows, other agents, signals.
- **Services, virtual objects and workflows**: Restate's journaled handlers, which replay
  their journal after a failure. They live in the same app as the rest, and everything calls
  everything with exactly-once RPC.

## How it runs

The app connects out to Restate Cloud with `restate.connect` and a connect key, rather than
Restate Cloud calling it. On Modal, one always-on container runs it, with its keys in a
Modal secret (`restate-template`, which both projects can share):

1. Sign in to [cloud.restate.dev](https://cloud.restate.dev) and create a connect key
   ([**Configure SDK -> Create connect key**](https://cloud.restate.dev/to/developers/integration#configure-sdk)).
2. Run the app on your machine with `RESTATE_CONNECT_KEY` set, or deploy it on Modal.
3. Register its deployment once in the Cloud UI (`connect://notes-v1` for TypeScript,
   `connect://notes-python-v1` for Python).

No account needed to start: each README also shows how to run against a Restate server on
your machine.

Both apps serve the same `notes` object, so in one Restate Cloud environment, register one
of them at a time, or rename the object in the other.
