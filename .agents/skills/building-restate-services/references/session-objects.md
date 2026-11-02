# Session objects (`@restatedev/sessions`)

A session object is a Restate virtual object where each key has its own SQL database,
`ctx.db` (SQLite-compatible, up to 10 GiB per key). The database lives in the object's
Restate state, so there is no database server to run. You still get one writer per key,
retries, and calls to other services.

The full documentation ships with the package: `node_modules/@restatedev/sessions/README.md`.
Read it for anything this page doesn't cover.

## The one rule that changes everything: no journal replay

Journaled handlers (`restate.service`, `restate.object`, `restate.workflow`) replay their
journal after a failure. **Session handlers don't.** When an attempt fails (a crash, a
retryable error, a suspension), Restate runs the handler again **from its first line**,
against whatever its database holds by then.

So, in a session object, **none** of the journaled-SDK rules apply:

| Journaled handlers (`ts/api-and-pitfalls.md`)                           | Session objects                                                                                          |
| ----------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| Wrap side effects and DB calls in `ctx.run`                             | There is no `ctx.run`. State is `ctx.db`; each statement is durable once it returns                      |
| Combine with `RestatePromise.all/race`, never native `Promise.all`      | Native `Promise.all` and `Promise.race` are fine: the package drives every awaited promise with one loop |
| No `Date.now()`, `Math.random()` or UUIDs: replay must be deterministic | There is no replay to break, but a new attempt computes new values, so never use them as idempotency ids |
| State in `ctx.get`/`ctx.set`                                            | No key/value state: the database is the session's only state                                             |
| `ctx.sleep`                                                             | Not available. For "later", a delayed send: `ctx.send(target, key, { delay: { minutes: 5 } })`           |
| Awakeables, durable promises                                            | Not available. An agent waits with a `signal()` tool; otherwise put the wait in a journaled workflow     |
| Add an always-replay Testcontainers test                                | Not applicable. Test what happens when an attempt runs twice                                             |
| `ctx.serviceClient(x)` / `ctx.objectClient(x, key)`                     | `ctx.rpc(service, options?)`, `ctx.rpc(object, key, options?)`, and `ctx.send(...)` likewise             |

What you must do instead: **make every handler safe to run twice** (next section).

## Delivery semantics: at least once, so idempotency matters

Restate delivers each invocation of a session object **at least once**, and may run its
handler more than once: every attempt (after a crash, a retryable error, a suspension, a lost
connection) runs it from its first line, partly or to the end. A journaled handler turns at
least once into effectively once by replaying its journal. A session handler has no journal
to replay, so:

> **Effectively once = at-least-once delivery + idempotent handlers.** A second run must find
> the first run's work, and do nothing more.

What runs how often:

|                                                   | Runs or is delivered                                                           | So                                                                              |
| ------------------------------------------------- | ------------------------------------------------------------------------------ | ------------------------------------------------------------------------------- |
| The handler's code                                | At least once per invocation, partly or fully                                  | Every write and call must be safe to repeat                                     |
| A statement or transaction that committed         | Durable once it returns; a new attempt executes the same code again            | Record a stable id with the write, and check for it first (`INSERT OR IGNORE`)  |
| `ctx.rpc` / `ctx.send` without an idempotency key | Again on every attempt that reaches it                                         | Give a call or send that changes something a key                                |
| `ctx.rpc` / `ctx.send` with an idempotency key    | Once per key: a repeat reaches the first invocation, and gets its result       | Build the key from `ctx.request.id` and what the call is for                    |
| `tx.send`                                         | Exactly once per committed transaction, never on a rollback                    | Needs no key of its own (the package gives each one `transaction/<id>/<index>`) |
| A view                                            | At least once (a view is retried, after 16 commits for example); it only reads | Nothing to do                                                                   |
| An outside API call (HTTP, email, payment)        | As often as the handler runs                                                   | See "Side effects outside Restate" below                                        |

### Three things can repeat, and each has its protection

| What repeats                                                                   | Its `ctx.request.id`                                                              | Protect with                                                                                                    | Protection lasts                                                                                                |
| ------------------------------------------------------------------------------ | --------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| An attempt of the same invocation (crash, retry)                               | The same                                                                          | Writes keyed by `ctx.request.id`; calls and sends with keys built from it; `tx.send`                            | Rows in `ctx.db`: as long as the data. Keys: the target's idempotency retention                                 |
| The same request, sent again by its caller (a client retrying after a timeout) | **New**: it is a new invocation, so writes keyed by `ctx.request.id` happen again | An idempotency key from the caller, at the ingress; or an id from the input (an order id), recorded in `ctx.db` | The ingress key: the handler's idempotency retention, a day by default. The id in `ctx.db`: as long as the data |
| The same business operation, later (the same order next week)                  | New                                                                               | An id from the input, recorded in `ctx.db`                                                                      | As long as the data                                                                                             |

- **Callers that may send a request again give it an idempotency key.** The repeat then
  starts no new invocation: Restate answers it with the first one's result, or attaches it to
  the one still running.

  ```sh
  curl localhost:8080/orders/alice/place -H 'idempotency-key: order-1042' --json '{"sku": "apple"}'
  curl localhost:8080/restate/invocation/orders/alice/place/order-1042/attach   # its result, by the key
  ```

  (On Restate Cloud: your ingress URL instead of `localhost:8080`, and
  `-H "Authorization: Bearer <ingress API key>"`; see the deploying-on-modal skill.)

  From code: `client.place(input, clients.rpc.opts({ idempotencyKey: 'order-1042' }))`, or
  `clients.rpc.sendOpts({ idempotencyKey })` for a one-way send.

- **A key names one request, whatever its input.** A repeat with another input silently gets
  the earlier result. Build keys from what makes the request unique, and never reuse one for
  a different request.
- **Keys expire** after the idempotency retention (a day by default): a repeat after that is
  a new invocation. For "never twice, ever" (a payment, a transfer), record the business id in
  `ctx.db` and check it, whatever the caller sends.
- **A delayed send repeated with the same key keeps its first timer**: Restate drops the
  repeat, and does not restart the delay.
- **Related writes go in one `ctx.db.transaction`.** A crash between two separate statements
  keeps the first one, and the next attempt runs both again.
- **A send that must happen only if a write commits is a `tx.send`** inside that transaction.

### Agents: the same three layers

An agent's `chat` is a session handler, so the table above applies to it:

- **A retried attempt** of a message: `@restatedev/agents` answers each message once per
  invocation. A model call already answered isn't made again, and a completed tool call isn't
  repeated (see [restate-agents.md](restate-agents.md) for a tool call a crash cut off).
- **A caller that sends the same message again without an idempotency key** starts a new
  invocation: the agent answers it again, model calls and tool calls included. A UI or
  client that may resend a message gives it an idempotency key
  (`curl …/chat/send -H 'idempotency-key: msg-1'`, or `clients.rpc.sendOpts({ idempotencyKey })`).
- **Tools run at least once:** a tool that changes something outside passes its
  `idempotencyKey` on, or takes `retryOf` on OpenCode and the DeepSeek Harness
  ([restate-agents.md](restate-agents.md), "Tools that must not run twice"). A tool's own
  "never twice, ever" needs a business id recorded in `ctx.db`, as above.

### Side effects outside Restate (an HTTP API, an email, a payment)

This is where the journaled habit of `ctx.run` comes back. Don't follow it:

```ts
// ❌ In a session object or an agent tool: there is no ctx.run (SessionContext has none, so it doesn't compile)
await ctx.run('charge', () => stripe.paymentIntents.create(params));

// ✅ Call it directly, and make a repeat harmless
await stripe.paymentIntents.create(params, { idempotencyKey: `${ctx.request.id}:charge` });
```

Make the repeat harmless in one of three ways, the first that fits:

1. **The API takes an idempotency key** (Stripe, most payment and email APIs): pass one that
   is the same on every attempt: `` `${ctx.request.id}:<what>` ``, or in an agent tool, the
   tool's own `idempotencyKey`.
2. **Record the result in `ctx.db`**, keyed by a stable id, and check for it before calling.
   A crash between the call and the record makes the call again, so this alone fits only
   calls that are harmless to repeat (a lookup, a translation).
3. **The call must happen once and the API can't deduplicate it**: move it into a journaled
   `restate.service` whose handler wraps it in `ctx.run`, and call that from the session
   object with an idempotency key:
   ``await ctx.rpc(payments, { idempotencyKey: `${ctx.request.id}:charge` }).charge(params)``
   (a service takes no key; an object's is `ctx.rpc(target, key, options)`). `ctx.run` lives
   in that journaled service, never in the session object.

Throw a `TerminalError` for failures a retry can't fix (a 4xx, a declined card), and let
other errors throw, so Restate retries the attempt.

## Defining one

Everything comes from `@restatedev/sessions`. It re-exports the Restate SDK at the version
it pins, so import `TerminalError`, `service`, `workflow` and the rest from it too. Don't
add a second `@restatedev/restate-sdk` version: the package relies on SDK internals and
refuses to run on another.

```ts
import * as restate from '@restatedev/sessions';

const notes = restate.sessionObject({
  name: 'notes',
  // Steps that create each key's database. Each runs once per key. Append; never edit one that ran.
  schema: ['CREATE TABLE notes (text TEXT NOT NULL)'],
  handlers: {
    // One at a time per key; the only ones that write. ctx: SessionContext.
    add: async (ctx, note: string) => {
      await ctx.db.execute('INSERT INTO notes (text) VALUES (?)', [note]);
    },
  },
  views: {
    // Run at any time, even beside a handler; read only. ctx: ViewContext.
    list: async (ctx) => {
      const rows = await ctx.db.query<{ text: string }>('SELECT text FROM notes ORDER BY rowid');
      return rows.map(({ text }) => text);
    },
  },
});
```

- Annotate only the input; `ctx` is inferred. A name is a handler or a view, not both.
- A handler or view is a function, or `{ handler, ...options }` with the SDK's usual
  options (`input`, `output`, `description`, `ingressPrivate`, …).
- SDK handler wrappers (`restate.handlers.*`) aren't accepted. Journaled work belongs in
  a regular `restate.object`, `service` or `workflow`, which the session object calls.

### The contexts

|                          | Handlers: `SessionContext`              | Views: `ViewContext`         |
| ------------------------ | --------------------------------------- | ---------------------------- |
| `ctx.key`, `ctx.request` | Yes                                     | Yes                          |
| `ctx.db`                 | `Database`: reads, writes, transactions | `DatabaseReader`: reads only |
| `ctx.rpc`, `ctx.cancel`  | Yes                                     | Yes                          |
| `ctx.send`               | Yes                                     | No                           |

`ctx.request.id` is the same on every attempt of an invocation. There is no `run`, `sleep`,
`rand`, `date`, awakeable, promise, or key/value state.

### Views

A view reads a snapshot of the database as committed when it started, while a handler may
be writing. A chat UI can read a conversation while the agent works on it, for example. A
view's `db` has no `execute` or `transaction`, and a write through `query` fails. A view
still running after 16 of the handlers' commits fails, and is retried.

## The database

The SQL dialect (SQLite, not Postgres), what works and what doesn't, and every transaction
rule, all tested: [session-sql.md](session-sql.md). Read it before writing SQL.

- `query<T>(sql, params)` returns rows as objects keyed by column name. `get<T>` returns
  the first row or `undefined`. `values` returns rows as arrays. `execute` runs statements
  and returns nothing. `T` isn't checked at runtime.
- Give an expression an alias (`SELECT count(*) AS n`): without one, its column is named
  after the expression's text. Integers above 2^53 come back as bigints, and booleans as 0
  or 1.
- Outside a transaction, each statement is a commit of its own: one round trip to Restate.
  `ctx.db.transaction(async (tx) => …)` commits its body together when it resolves, and
  rolls back if it rejects. Group writes in one transaction: it is cheaper and atomic.
- Inside a transaction body, use `tx`: a call to `ctx.db` is refused. Calls to `ctx.db` run
  one at a time in the order you make them, even when awaited together.
- An SQL error rejects with a `TerminalError` (a retry would fail the same way). So does a
  `COMMIT` or `ROLLBACK` inside a transaction body, which also closes the database for the
  rest of the attempt, and returning with a transaction still open.

### The schema

`schema` lists the steps that create each key's database, in order. A step is an SQL
statement, or an async function that gets the transaction. The database records how far it
got, so a step added later (a column, an index) runs once on each key's database, the next
time that key is used. **Never change or remove a step that may have run; add a new one.**
Don't name your tables `restate_…`: `@restatedev/agents` uses that prefix for its own.

## Calls, sends and cancellation

```ts
const owner = await ctx.rpc(handle, name, { idempotencyKey: `${ctx.request.id}:claim` }).claim(ctx.key);
ctx.send(audit).record(entry); // one-way
ctx.send(reminders, key, { delay: { hours: 1 } }).ping(); // delayed
ctx.rpc({ service: 'other', key, handler: 'h', input }); // a target known only at runtime
ctx.cancel(invocationId); // handlers and views
```

- Objects and workflows need a key; services don't. Getting it wrong throws a `TerminalError`.
- The SDK never makes up idempotency keys. A key names one call, so if an invocation makes
  the same call several times, add what tells them apart. Restate remembers keys for the
  target's idempotency retention, a day by default.
- Sends in a transaction (`tx.send`) go out right after it commits, and never if it rolls
  back, each exactly once, even across crashes. `tx.send` takes the same options as
  `ctx.send`, a `delay` included: `tx.send(target, key, { delay: { hours: 24 } }).handler(input)`.

```ts
await ctx.db.transaction(async (tx) => {
  await tx.execute('INSERT INTO entries (id, amount, note) VALUES (?, ?, ?)', [id, -amount, `to ${to}`]);
  if ((await balanceOf(tx)) < 0) throw new restate.TerminalError('Not enough money'); // rolls back, sends nothing
  tx.send(wallet, to).deposit({ id, amount, note: `from ${ctx.key}` }); // delivered once this commits
});
```

A send returns no result. When you need a call's result, make the call before the
transaction, with an idempotency key, and record its outcome in the transaction.

## Mixing with journaled services

Session objects sit beside journaled services, objects and workflows in one deployment,
and call each other:

- From a session object: `ctx.rpc(service).handler(input)`, `ctx.rpc(object, key).handler(input)`.
  Use journaled handlers for awakeables, durable promises, long waits, and multi-step side
  effects that need `ctx.run`.
- From a journaled handler: a session object is a virtual object, so call it with
  `ctx.objectClient(sessionObject, key).handler(input)`. The journaled handler follows the
  journaled rules.
- Each handler follows the rules of the kind it is: decide per handler, not per file.

## Not supported

- Key/value state, `ctx.run`, `ctx.sleep`, awakeables and durable promises in a session
  object. Later work is a delayed `ctx.send`; a wait is an agent's `signal()` or a journaled
  workflow.
- Request/response deployments such as AWS Lambda: they suspend at every await, and for a
  session object a suspension is a restart. Run on a long-lived process: a server with
  `restate.serve`, or a container connected with `restate.connect`.

## Before finishing (session objects)

- [ ] Every handler is safe to run twice (delivery is at least once): writes keyed by a
      stable id, calls and sends that change something carry an idempotency key, related
      writes in one transaction
- [ ] Callers that may send a request again use an idempotency key, and an operation that
      must never happen twice ("ever") records its business id in `ctx.db`
- [ ] Schema changes are new steps appended at the end; no step that may have run was edited
- [ ] Views only read; writes are in handlers
- [ ] The SQL is SQLite's, and follows [session-sql.md](session-sql.md): `INTEGER PRIMARY KEY`,
      no `NOW()`, no `Date` or object parameters, no `COMMIT`/`ROLLBACK` in a transaction body,
      `transaction()` awaited, no reliance on foreign keys
- [ ] No `ctx.run`, `ctx.sleep`, `ctx.get/set` or awakeables: later work is a delayed
      `ctx.send`, a wait is an agent's `signal()` or a journaled workflow, and a once-only
      outside call is a journaled service that the session object calls
- [ ] The SDK is imported from `@restatedev/sessions`, with no second SDK version added
- [ ] The service is in `services` in `src/app.ts`, and was called through Restate (curl or
      the UI), including a request sent twice where it matters
