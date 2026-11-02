# Choosing a service type

This repository has five building blocks. They all run in one deployment, and call each
other.

| Type               | Defined with                                          | State                                       | Concurrency                                                        | After a failure                                                   |
| ------------------ | ----------------------------------------------------- | ------------------------------------------- | ------------------------------------------------------------------ | ----------------------------------------------------------------- |
| **Service**        | `restate.service`                                     | None                                        | Unlimited, in parallel                                             | Replays its journal                                               |
| **Virtual object** | `restate.object`                                      | Key/value (`ctx.get`/`ctx.set`) per key     | One exclusive handler per key at a time; shared handlers beside it | Replays its journal                                               |
| **Workflow**       | `restate.workflow`                                    | Key/value per workflow id                   | `run` once per id; interaction handlers beside it                  | Replays its journal                                               |
| **Session object** | `restate.sessionObject` (`@restatedev/sessions`)      | A SQL database per key (`ctx.db`)           | One handler per key at a time; views beside it                     | Runs again from the first line, against its database              |
| **Agent**          | `pi.agent`, `sessionObject` (`@restatedev/agents`), … | Its conversation, in a SQL database per key | As a session object: one message per key at a time                 | As a session object; each model step and tool call is stored once |

The first three follow [ts/api-and-pitfalls.md](ts/api-and-pitfalls.md); the last two
[session-objects.md](session-objects.md), [session-sql.md](session-sql.md) and
[restate-agents.md](restate-agents.md).

## Decide

Answer in order; the first "yes" is the type.

1. **Is it an AI agent or an LLM conversation?** Use `@restatedev/agents`:
   - a chat agent with tools: `pi.agent({ name, tools })` (or `opencode`, `langgraph`,
     `claude`, `deepseek`);
   - an agent beside handlers and tables of your own: `sessionObject` of
     `@restatedev/agents`, with `chat: pi.chat(...)` and `messages: pi.messages()`;
   - one model answer inside an existing session handler: `pi.prompt(ctx, text)`.

   Don't hand-write an agent loop in journaled handlers (the public `ai-agents.md`
   pattern) unless the user asks for a framework `@restatedev/agents` doesn't support.

2. **Is it a process with a start and an end, that must run once per id, and waits** (for
   a person, a callback, a timer)? An onboarding, a refund, an approval chain, a pipeline
   that calls agents step by step. **Workflow**: `run` runs once per id, durable promises
   connect it to its interaction handlers, and `ctx.sleep` waits as long as it takes.
3. **Does each key keep data that you insert, update and query**, more than a few values:
   a list, a history, a ledger, a cart with items, a document's revisions, anything you'd
   put in tables? **Session object.** SQL, transactions over many rows, up to 10 GiB per
   key, and views that read the committed data while a handler writes.
4. **Does each key keep a few values, and need timers, awakeables or multi-step side
   effects inside its own handlers** (a counter with a timeout, a device twin that waits for
   an ack)? **Virtual object.**
5. **Otherwise, no state per key**: an API call, a fan-out, a saga, a wrapper around an
   outside system. **Service.**

When 3 and 4 both fit, prefer the **session object** if its data will grow or be queried,
and the **virtual object** if its handlers need to wait (sleep, awakeables) or run several
side effects each exactly once.

## Session object or virtual object?

Both are keyed, with one writer per key and concurrent readers. The difference:

|              | Session object                                                                                            | Virtual object                                          |
| ------------ | --------------------------------------------------------------------------------------------------------- | ------------------------------------------------------- |
| State        | Tables, queried with SQL; transactions; up to 10 GiB per key                                              | A few JSON values by name                               |
| Readers      | Views: a snapshot of what's committed, while a handler writes                                             | Shared handlers: `ctx.get`                              |
| Side effects | Direct calls, made safe to repeat (idempotency keys, stable ids)                                          | Exactly once, in `ctx.run`                              |
| Waiting      | None inside a handler: a delayed `ctx.send`, a signal (agents), or a workflow                             | `ctx.sleep`, awakeables, inside the handler             |
| Recovery     | Runs again from the first line; correctness comes from the data                                           | Replays the journal; correctness comes from determinism |
| Costs        | Every read is journaled with its value; one round trip per commit; a suspension restarts the handler      | The journal of each invocation                          |
| Deployment   | A long-lived process (`restate.serve`, or `restate.connect` as on Modal), never request/response (Lambda) | Any                                                     |

## Combine them

Most applications use several types. The session object holds the data, a journaled
service or workflow does what a session object can't:

| Need                                                                                | Pattern                                                                                                        | Example                                                                                        |
| ----------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| Data per user, plus an outside call that must happen once and can't be deduplicated | Session object calls a **service** whose handler wraps the call in `ctx.run`, with an idempotency key          | `tx.send(mailer).send(...)` after the insert commits                                           |
| An agent that needs a person's approval                                             | `signal()` tool on the agent; no workflow needed                                                               | `src/tutorial/14_approval.ts`                                                                  |
| An agent whose tools are your business logic                                        | `call()` a service or object, `workflow()` a workflow, `send()` one-way                                        | `src/tutorial/13_restate_tools.ts`; support agent with an orders service and a refund workflow |
| A multi-step process that uses agents                                               | **Workflow** that calls agents with `ctx.objectClient(agent, key).chat(...)`                                   | Triage: classify, draft, wait for a person's review                                            |
| Later work from a session object                                                    | A delayed `ctx.send` (to itself or another handler), with an idempotency key                                   | A reminder in N minutes                                                                        |
| Money moving between two keys                                                       | Session object, debit and `tx.send` of the credit in one transaction                                           | `src/tutorial/08_sends.ts`                                                                     |
| Something across all keys (totals, a leaderboard, search)                           | A second object, or an outside store, that handlers update with an idempotency key; there's no SQL across keys |                                                                                                |

## Keys

The key is the unit of state, of queueing, and for a session object, of a database. Pick
it so that one handler's work and one query's data are in one key: a user, a cart, a
conversation, an order, a document. Avoid keys with few values ("region", "global"): every
request for one key waits in line. See
[design-and-architecture.md](design-and-architecture.md) for keying in general.

## Deadlocks apply to session objects too

Session handlers are exclusive per key, like a virtual object's. A handler that calls
(`ctx.rpc`, waiting for the answer) a handler of the same key waits forever, and so does a
cycle of calls between keys. Use `ctx.send` (no wait) to break a cycle, as
[design-and-architecture.md](design-and-architecture.md) describes. Views don't queue.
