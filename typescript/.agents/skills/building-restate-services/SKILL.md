---
name: building-restate-services
description: >
  Design, build, run and test Restate services in the TypeScript project (typescript/): session
  objects with a SQL database per key (@restatedev/sessions), durable AI agents on them
  (@restatedev/agents: pi, LangGraph, Claude, DeepSeek), and journaled Restate
  services, virtual objects and workflows (@restatedev/restate-sdk). Use when the user
  mentions Restate, session objects, sessionObject, ctx.db, durable agents, virtual objects,
  workflows, durable execution, or edits src/app.ts, src/tutorial or src/examples.
---

# Restate in this repository

Restate is a durable execution runtime: services run behind a Restate Server (ingress on
port 8080, admin and UI on 9070), which retries them through crashes. This repository uses
**two execution models side by side**, and their rules contradict each other. **Before
writing or changing a handler, decide which model it uses, and follow only that model's
rules.**

If another Restate skill is loaded too (such as the restatedev plugin's own
`building-restate-services`), its mandatory rules, `ctx.run` around every side effect,
`RestatePromise` instead of `Promise.all`, and always-replay tests, are for journaled
handlers only. For session objects and agents, this skill's rules take precedence: never
suggest `ctx.run`, `ctx.sleep`, `ctx.get`/`ctx.set` or awakeables there.

## Step 1: which model is this handler?

|                                      | **Session object**                                                                                                                                                                        | **Journaled handler**                                                                                                                              |
| ------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| Defined with                         | `restate.sessionObject(...)` of `@restatedev/sessions`; `sessionObject(...)`, `pi.agent(...)`, `langgraph.agent(...)`, `claude.agent(...)`, `deepseek.agent(...)` of `@restatedev/agents` | `restate.service(...)`, `restate.object(...)`, `restate.workflow(...)` (whether imported from `@restatedev/restate-sdk` or `@restatedev/sessions`) |
| After a failure                      | Runs again **from its first line**, against its database. No journal replay                                                                                                               | **Replays its journal**: completed steps return their recorded results                                                                             |
| Delivery                             | At least once: effectively once only with idempotent handlers ("Delivery semantics" in [session-objects.md](references/session-objects.md))                                               | At least once, made effectively once by the journal for journaled steps                                                                            |
| State                                | `ctx.db`: a SQL database per key                                                                                                                                                          | `ctx.get` / `ctx.set` key/value state                                                                                                              |
| Side effects                         | Directly; make them safe to run twice (stable ids, idempotency keys)                                                                                                                      | Inside `ctx.run(...)`                                                                                                                              |
| Concurrency                          | Native `Promise.all` / `Promise.race` are fine                                                                                                                                            | `RestatePromise.all/race/any`, never native combinators                                                                                            |
| Time, random, ids                    | Allowed, but never as idempotency ids                                                                                                                                                     | Only `ctx.date`, `ctx.rand`                                                                                                                        |
| Timers, awakeables, durable promises | Not available: a delayed `ctx.send` for later work, a `signal()` tool for an agent's wait, a journaled workflow for the rest                                                              | `ctx.sleep`, `ctx.awakeable`, `ctx.promise`                                                                                                        |
| Calls                                | `ctx.rpc(service, { idempotencyKey })`, `ctx.rpc(object, key, { idempotencyKey })`, `ctx.send(...)`, `tx.send(...)`                                                                       | `ctx.serviceClient`, `ctx.objectClient`, `ctx.workflowClient` and their send clients                                                               |
| Testing rule                         | Show that a handler run twice does its work once                                                                                                                                          | Always-replay Testcontainers test (the repository has no test setup yet: ask before adding one)                                                    |
| Reference                            | [session-objects.md](references/session-objects.md), and [restate-agents.md](references/restate-agents.md) for agents                                                                     | [ts/api-and-pitfalls.md](references/ts/api-and-pitfalls.md)                                                                                        |

**For new code, choose the type first**, with
[choosing-service-types.md](references/choosing-service-types.md): service, virtual object,
workflow, session object or agent, and how they combine. In short:

- **An AI agent or LLM conversation**: `@restatedev/agents` (`pi.agent`, or `sessionObject`
  with `pi.chat` beside your own handlers). Not a hand-written agent loop.
- **Data per key that you insert, update and query** (a list, a history, a ledger, a cart):
  a **session object**.
- **A process with a start and an end that waits** (for a person, a callback, a timer), once
  per id: a **workflow**.
- **A few values per key, with timers or awakeables inside the handlers**: a **virtual
  object**. **No state per key**: a **service**.
- All of them live in one deployment and call each other. A file can hold several: decide
  per handler, never per file.

Never carry a rule across: don't wrap `ctx.db` in `ctx.run` (a session object has no
`ctx.run`), and don't use native `Promise.all` in a journaled handler.

## Step 2: the repository

- `src/app.ts` is the application: its services go in `services`, which
  `restate.connect({ services: restate.served(services), name: 'notes-v1' })` connects to
  Restate Cloud (`served` adds what they need beside them, such as each agent's companion). For a Restate
  server on this machine, the commented `await restate.serve(...services)` line replaces it
  (on `PORT`, 9080 by default).
- `restate.serve` of `@restatedev/sessions` takes the services as arguments,
  `restate.serve(notes, orders)`, and adds what they need (an agent's companion). It is not the
  SDK's `restate.serve({ services: [...] })`, which the journaled references show: in this
  repository, `restate` is `@restatedev/sessions`.
- `src/tutorial/`: the tutorial, one idea per lesson, off by default (see the comment in
  `src/app.ts`). Lessons 01–08 are session objects, 09–16 agents. Read the closest lesson
  before writing similar code. If `src/examples/` exists, it has agents, one per file.
- Import the SDK from `@restatedev/sessions` (it re-exports `@restatedev/restate-sdk` at the
  version it pins). Don't add another `@restatedev/restate-sdk` version.
- From `typescript/`: Node 24 runs the TypeScript directly, `node src/app.ts`. Check with `pnpm lint` (tsc,
  oxlint, oxfmt) and format with `pnpm format`.
- To run it locally, connect it to Restate Cloud, or deploy it on Modal: the
  **deploying-on-modal** skill.
- The examples in the references call a local server, `curl localhost:8080/…`. On Restate
  Cloud, the same paths work at your environment's ingress
  (`https://<environment id>.env.<region>:8080`) with `-H "Authorization: Bearer <ingress API key>"`,
  or through the client with `RESTATE_INGRESS_KEY`: see deploying-on-modal, "Calling handlers".

## Step 3: load what the task needs

| Task                                                                                                   | Reference                                                                                                            |
| ------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------- |
| Choose a service type, or how to combine them                                                          | [choosing-service-types.md](references/choosing-service-types.md)                                                    |
| Write or change a session object, its views, calls                                                     | [session-objects.md](references/session-objects.md)                                                                  |
| What a session object guarantees: requests, isolation, blocking, atomicity, order of effects, versions | [session-objects.md](references/session-objects.md), "Semantics"                                                     |
| Write SQL, tables, schema steps or transactions in a session object or agent                           | [session-sql.md](references/session-sql.md)                                                                          |
| Write or change an agent (tools, signals, models, subagents, structured answers)                       | [restate-agents.md](references/restate-agents.md)                                                                    |
| A framework's options and behaviour (pi, LangGraph, Claude, DeepSeek): coding agents, `withPi`, graphs | [agents-frameworks.md](references/agents-frameworks.md)                                                              |
| Call, follow (UI), steer, stop or clear an agent; turns; failures and retries; testing and deploying   | [agents-operations.md](references/agents-operations.md)                                                              |
| Write or change a journaled service, object or workflow                                                | [ts/api-and-pitfalls.md](references/ts/api-and-pitfalls.md)                                                          |
| Concurrent routines with several durable steps each, in journaled code (`@restatedev/restate-sdk-gen`) | [ts/durable-coroutines.md](references/ts/durable-coroutines.md)                                                      |
| Design an application, choose service types and keys                                                   | [design-and-architecture.md](references/design-and-architecture.md)                                                  |
| Concurrency limits, tenant fairness, scopes, limit keys                                                | [flow-control-and-scopes.md](references/flow-control-and-scopes.md)                                                  |
| Invoke, cancel, attach, deduplicate with idempotency keys, send, Kafka                                 | [invocation-lifecycle.md](references/invocation-lifecycle.md)                                                        |
| Migrate from another orchestrator or architecture                                                      | [translate-to-restate.md](references/translate-to-restate.md)                                                        |
| Debug stuck invocations, journal mismatches (journaled handlers)                                       | [debug-applications.md](references/debug-applications.md)                                                            |
| A hand-written agent in journaled handlers, or the Vercel AI SDK                                       | [ai-agents.md](references/ai-agents.md), [ts/restate-vercel-ai-agents.md](references/ts/restate-vercel-ai-agents.md) |
| Everything about sessions or agents not covered above                                                  | `node_modules/@restatedev/sessions/README.md`, `node_modules/@restatedev/agents/README.md`                           |
| Server configuration, deployment, advanced topics                                                      | https://docs.restate.dev (or the `restate-docs` MCP server at https://docs.restate.dev/mcp, if configured)           |

The journaled references come from [restatedev/skills](https://github.com/restatedev/skills)
(MIT, see `references/LICENSE-restatedev-skills.md`), with a scope note at their top. Where
they say "the bundled MCP server", use https://docs.restate.dev if no MCP server is set up.

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

Run the checklist of each model you touched:

- Session objects and agents: the checklists at the end of
  [session-objects.md](references/session-objects.md) and
  [restate-agents.md](references/restate-agents.md).
- Journaled handlers:
  - [ ] Side effects, external I/O and database calls inside `ctx.run`; no Restate context
        operation inside a `ctx.run` callback
  - [ ] No native random, time, sleep or UUIDs: `ctx.rand`, `ctx.date`, `ctx.sleep`
  - [ ] `RestatePromise` combinators, not native `Promise` ones
  - [ ] `TerminalError` for failures that must not be retried
  - [ ] No deadlock cycles between virtual objects calling each other
  - [ ] Logic changes covered by an always-replay test (see `ts/api-and-pitfalls.md`). The
        repository has no test setup yet: propose one, and ask before adding its dependencies
- Always: `pnpm lint` passes, the service is in `services` in `src/app.ts`, and it was
  called through Restate (curl, the playground, or the UI).
