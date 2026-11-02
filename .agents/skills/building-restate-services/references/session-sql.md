# SQL and transactions in session objects

Each key of a session object has its own SQLite-compatible database (Turso's engine), as
`ctx.db`. Write **SQLite SQL**, not Postgres or MySQL. The SQL, parameters and transaction
behaviour below were checked against the engine of `@restatedev/sessions` 0.1.0; the schema,
view and size rules come from the package's README. When in doubt about a feature, test it
the same way (see the end of this page) rather than assuming SQLite or Postgres behaviour.

## One database per key

`notes/alice` and `notes/bob` are two separate databases. **There is no query across keys**:
"all users' notes" or "the top 10 wallets" cannot be a SQL query. For that, keep a second
object that the handlers update (with an idempotency key), or send the data to a store
built for it. Choose the key so that what one query needs is in one key's database.

## The API

```ts
await ctx.db.execute(sql, params?);              // one or more statements; no rows
const rows = await ctx.db.query<Row>(sql, params?); // rows as objects keyed by column name
const row = await ctx.db.get<Row>(sql, params?);    // the first row, or undefined
const tuples = await ctx.db.values(sql, params?);   // rows as arrays, in column order
```

- **Parameters are positional:** `?`, or `?1` to reuse one. Named parameters (`:name` with
  an object) are not supported.
- **Parameter types:** string, number, bigint, boolean (stored as 1 or 0), `null`
  (`undefined` becomes `NULL`), and `Uint8Array` (a blob). **A `Date` or an object fails**
  (with "Get TypedArray info failed"): pass `date.toISOString()` or `date.getTime()`, and
  `JSON.stringify(object)`.
- **Results:** integers above 2^53 come back as bigints, booleans as 0 or 1, blobs as
  Buffers. A column's name is its alias, so give expressions one (`SELECT count(*) AS n`):
  without it, the key is the expression's text. Two columns with the same name are an
  error in `query` and `get`; use `values`, or alias them.
- `T` in `query<T>` and `get<T>` describes a row, but isn't checked at runtime.
- In a query with several statements, only the last one's rows come back.

## What works, and what doesn't

| Works                                                                                         | Instead of (doesn't work, or misleads)                                                                                               |
| --------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| `id INTEGER PRIMARY KEY` (auto-assigned), `AUTOINCREMENT`                                     | `id SERIAL PRIMARY KEY`: accepted, but the id stays `NULL`                                                                           |
| `datetime('now')`, `unixepoch()`, `strftime(...)`, `DEFAULT CURRENT_TIMESTAMP`                | `NOW()`: no such function                                                                                                            |
| `INSERT ... RETURNING id`, `last_insert_rowid()`, `changes()`                                 |                                                                                                                                      |
| `INSERT OR IGNORE`, `INSERT OR REPLACE`, `ON CONFLICT(col) DO UPDATE SET n = n + excluded.n`  |                                                                                                                                      |
| `json_extract`, `->>`, `json_each`, `json_object`, `json_group_array` (JSON stored as `TEXT`) | Postgres's `jsonb` operators and functions (`@>`, `?`, `jsonb_set`): not SQLite's (untested)                                         |
| `WITH RECURSIVE`, window functions (`ROW_NUMBER() OVER (...)`), views, triggers               |                                                                                                                                      |
| `CREATE INDEX`, `UNIQUE`, partial indexes (`... WHERE n > 0`), `STRICT` tables                |                                                                                                                                      |
| `ALTER TABLE ... ADD COLUMN`, `RENAME COLUMN`, `DROP COLUMN`                                  |                                                                                                                                      |
| Checks in your code, or `UNIQUE` and `CHECK` constraints                                      | Foreign keys: **not enforced**. `PRAGMA foreign_keys = ON` lasts only until the database is reopened, which happens on every attempt |
|                                                                                               | Generated columns, FTS5 full-text search (`CREATE VIRTUAL TABLE ... USING fts5`), `ATTACH`: not supported                            |

## Idempotent writes

A handler can run again from its first line (no journal replay), so make writes safe to
repeat. The usual pattern is a unique id that is the same on every attempt:

```ts
schema: [
  'CREATE TABLE entries (id TEXT PRIMARY KEY, amount INTEGER NOT NULL, note TEXT)',
],
handlers: {
  deposit: async (ctx, { amount, note }: { amount: number; note?: string }) => {
    await ctx.db.execute('INSERT OR IGNORE INTO entries (id, amount, note) VALUES (?, ?, ?)', [
      ctx.request.id, // the same on every attempt of this invocation
      amount,
      note ?? null,
    ]);
  },
},
```

Use an id from the input when the caller may send the same request twice as separate
invocations (an order id, a transfer id). Don't use `Date.now()`, `Math.random()` or
`randomUUID()` as such an id: a new attempt gets a new value.

## Transactions

Outside a transaction, **each statement is its own commit**: durable once it returns, and
one round trip to Restate. `ctx.db.transaction` commits its body's statements together when
the body resolves, and rolls them all back if it throws (an SQL error inside included):

```ts
const balance = await ctx.db.transaction(async (tx) => {
  await tx.execute('INSERT OR IGNORE INTO entries (id, amount) VALUES (?, ?)', [ctx.request.id, -amount]);
  const { total } = (await tx.get<{ total: number }>('SELECT coalesce(sum(amount), 0) AS total FROM entries'))!;
  if (total < 0) throw new restate.TerminalError('Not enough money'); // rolls back the insert
  return total; // transaction() resolves with the body's value
});
```

Rules (the first four, and reads seeing the body's writes, checked against the engine):

- **Use `tx` inside the body.** A call to `ctx.db` there fails ("inside a transaction, use
  the transaction handle its body gets").
- **Never write `COMMIT` or `ROLLBACK` in the body.** Either one ends the transaction under
  `transaction()`, and **closes the database for the rest of the attempt**: every later
  call fails. Throw to roll back; return to commit.
- **No nested transactions:** `tx` has no `transaction()`.
- **Don't open transactions with raw `BEGIN`.** It is accepted outside `transaction()`, but
  one left open makes the next `transaction()` fail, and a transaction still open when the
  handler returns is a terminal error. `tx.send` exists only in `transaction()`.
- **Always `await` (or return) `transaction()`.** Later `ctx.db` calls wait for it, but a
  handler that returns before it resolves leaves it open, which is an error.
- **Reads inside the body see the body's own writes.**
- **Keep the body to database work and `tx.send`.** Make calls whose result you need
  _before_ the transaction (with an idempotency key), and record the outcome inside it.
  `tx.send` goes out once, after the commit, and never on a rollback.
- **Group writes.** A transaction is atomic, and cheaper than the same statements one by
  one: one commit instead of many.

Statements that must succeed or fail together belong in one transaction. A crash between
two separate statements keeps the first one.

## Schema changes

`schema` is a list of steps, applied in order, once per key, in one transaction the first
time a handler opens that key's database:

```ts
schema: [
  'CREATE TABLE notes (text TEXT NOT NULL)',                // step 1: ran on every existing key
  'ALTER TABLE notes ADD COLUMN created TEXT',              // step 2: added later; runs once per key
  async (tx) => {                                           // step 3: a data migration, as a function
    await tx.execute("UPDATE notes SET created = datetime('now') WHERE created IS NULL");
  },
],
```

- **Never edit, reorder or remove a step that may have run.** Each key's database
  remembers how many steps it ran, so an edited step never runs again on existing keys,
  and a removed one shifts the rest. Add a new step at the end.
- A view of a key that was never written sees empty tables.
- Don't name tables `restate_…`: `@restatedev/agents` keeps its tables under that prefix
  in the same database.

## Views and reads

A view reads a snapshot of the database as committed when it started, even while a handler
writes. It can't write: no `execute`, no `transaction`, and a write through `query` fails.
A view still running after 16 of the handlers' commits fails, and is retried: keep views
short.

## Errors

- An SQL error (a bad statement, a constraint violation, a parameter that can't be bound)
  rejects with a `TerminalError` whose `cause` is the SQL error: Restate does not retry it,
  because a retry would fail the same way. Catch it to handle it, such as a `UNIQUE`
  violation meaning "already exists".
- A database past 10 GiB fails a write with "database or disk is full", also terminal.

## Testing SQL

Test SQL through the object, against a Restate server on this machine (deploying-on-modal):
call the handler that runs it, then a view that reads what it wrote. That runs the
object's `schema`, its transactions and its retries as they will run deployed. Use only
the public API (`ctx.db`, `restate.Database`): don't import the package's internal
modules or open its storage yourself.
