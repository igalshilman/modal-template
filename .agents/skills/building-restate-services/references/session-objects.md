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

What you must do instead: **make every handler safe to run twice** ("Delivery semantics",
below).

## Semantics: what holds, and what you handle

A session object is a **virtual object whose state is a SQL database, and whose handlers
recover from that database's commits instead of a journal**. Everything Restate defines for
virtual objects holds; only how a handler recovers differs.

- **An object per key.** A session object is addressed by its name and a key
  (`Ledger/acme`). Each key is an isolated entity with its own state, here its own database
  (`ctx.db`), kept in the object's Restate state and retained indefinitely. Keys share
  nothing: no data, no queue.
- **Durable invocations.** Each request is an _invocation_: Restate stores it before a
  handler runs, gives it an id (`ctx.request.id`, the same on every attempt), and tracks it
  until it completes. A caller can wait for its answer, attach to it later by id or by
  idempotency key, or cancel it.
- **Exclusive handlers, shared views.** `handlers` are the object's _exclusive_ handlers, a
  single writer per key: Restate queues the key's invocations and runs them one at a time,
  in order, each to its end before the next starts. `views` are its _shared_ handlers:
  read-only, and run at once, beside a running handler, without queueing.
- **Durable execution, without a journal.** An invocation runs in _attempts_: a crash, a
  retryable error or a suspension ends one, and Restate starts another. A virtual object's
  handler replays its journal; a session handler runs again from its first line (_explicit
  recovery_), against what earlier attempts committed. A commit (a statement, or a
  transaction) is durable once its promise resolves, and every later attempt sees it; what
  an attempt didn't commit is as if it never happened. Attempts go on until the handler
  returns, throws a `TerminalError`, or its retry policy gives up.

|                      | What holds                                                                                                                                                                                                                                                                                                                               | So                                                                                                                                                                                                                                                                                                                                                                |
| -------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **The request**      | Stored before it runs, and answered once: the handler's result, or its terminal error. A crash isn't an answer: Restate runs the handler again while the caller waits, or attaches later. Out of retries, Restate pauses it: no answer until it is resumed or killed                                                                     | A caller sends a request again only if it lost its own connection to Restate, and then with an idempotency key                                                                                                                                                                                                                                                    |
| **Execution**        | At least once, from the first line each time, partly or to the end                                                                                                                                                                                                                                                                       | Every write and call is safe to run twice ("Delivery semantics", below)                                                                                                                                                                                                                                                                                           |
| **Isolation**        | One exclusive handler per key, for the whole invocation: through every `await`, a model's answer or an HTTP call included. No other exclusive handler of the key starts until it ends; views run beside it                                                                                                                               | A read, an outside call, and a write based on the read can't race with another request for the key: the key's own data needs no locks and no re-checks                                                                                                                                                                                                            |
| **Blocking**         | The key's other requests wait behind it, in order, however long it takes. A handler that calls and awaits a handler of its own key, directly or through a cycle of calls, waits forever                                                                                                                                                  | Keep handlers short. A long wait goes to a workflow, an agent's `signal()`, or a delayed send. `ctx.send` (no wait) breaks a cycle; views don't queue                                                                                                                                                                                                             |
| **Reads**            | A handler reads every commit, its own included. A view (a shared handler) reads the database as committed when it started, never a transaction in progress                                                                                                                                                                               | Each view call reads the latest commit, and one call reads one snapshot: a view that polls in a loop never sees a newer commit, and one that outlives 16 of the handler's commits fails and is retried                                                                                                                                                            |
| **Atomicity**        | Per commit (a statement, or a transaction), not per invocation: what committed before a crash, an error or a `TerminalError` stays                                                                                                                                                                                                       | What must be all or nothing goes in one transaction. A `TerminalError` thrown after a commit doesn't undo it                                                                                                                                                                                                                                                      |
| **Order of effects** | An attempt's writes, calls and sends are stored in the order it issued them to Restate, a commit's writes as it commits: a crash loses the last ones, never one without those before it. A `tx.send` goes out if and only if its transaction commits                                                                                     | Await a commit before a send or call that depends on it (a send made before the commit's promise resolves can be stored without it), or make it a `tx.send`. A rejected `transaction()` may still have committed (a cancellation, or the attempt replaced as it made the sends): never compensate as if it rolled back. Nothing holds back an outside call (HTTP) |
| **State**            | The database, and nothing else. Each attempt gets a new context, and the key's next invocation may run in another process                                                                                                                                                                                                                | No per-key state in module variables: store it, or compute it again                                                                                                                                                                                                                                                                                               |
| **Time**             | No timers inside a handler. Delayed sends are durable, any number of them per key                                                                                                                                                                                                                                                        | "Later" is a delayed `ctx.send` or `tx.send`                                                                                                                                                                                                                                                                                                                      |
| **Cancellation**     | Its pending awaits on Restate (`ctx.db`, `ctx.rpc`) reject with `CancelledError`; an outside call (HTTP, a model) runs on, and the handler's next `ctx.db` or `ctx.rpc` call fails. Its commits stay, and a commit the cancellation interrupted may be stored too; in 0.2.0, that commit's `tx.send`s wait for the key's next invocation | A cancelled invocation is one that stopped anywhere and won't run again: its work may be partly committed. A Stop button doesn't stop a model call in flight: the handler stops at its next `ctx` call                                                                                                                                                            |
| **Versions**         | An invocation runs on the deployment it started on, retries included, and every version shares the key's database                                                                                                                                                                                                                        | A new schema step keeps the previous version's code working: add tables and columns, don't drop or rename what it uses                                                                                                                                                                                                                                            |

In short: **you never handle two requests for a key racing each other. You always handle a
handler that runs twice, and a handler that holds its key.**

Running twice is where most bugs are. A rerun starts from the top and finds its earlier
commits, so it must still do what came after them:

```ts
// ❌ A crash after the insert commits: the rerun returns early, and the confirmation is never sent
const done = await ctx.db.get('SELECT 1 FROM orders WHERE id = ?', [order.id]);
if (done) return;
await ctx.db.execute('INSERT INTO orders (id, sku) VALUES (?, ?)', [order.id, order.sku]);
await ctx.rpc(mailer, { idempotencyKey: `${order.id}:confirmation` }).confirm(order);

// ✅ The send commits with the insert: made once, after the commit, even across a crash
await ctx.db.transaction(async (tx) => {
  const done = await tx.get('SELECT 1 FROM orders WHERE id = ?', [order.id]);
  if (done) return;
  await tx.execute('INSERT INTO orders (id, sku) VALUES (?, ?)', [order.id, order.sku]);
  tx.send(mailer).confirm(order);
});
```

Or don't return early: each step checks for itself (`INSERT OR IGNORE`, then the call with
its idempotency key), so a rerun skips what is done and does what isn't.

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
- [ ] A rerun that finds its earlier commits still does what came after them: no early
      return past a send or call that follows a write (make it a `tx.send`, or let each step
      check for itself)
- [ ] No handler holds its key for a long wait, or calls and awaits a handler of its own key;
      no per-key state in module variables
- [ ] New schema steps keep the previous deployment's code working (add, don't drop or rename)
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
