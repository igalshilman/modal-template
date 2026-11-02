# Session objects and agents on Modal

A template for a [Restate](https://restate.dev) application that runs on
[Modal](https://modal.com) and connects to [Restate Cloud](https://cloud.restate.dev). It
is built on two libraries for the Restate TypeScript SDK:

- **[`@restatedev/sessions`](https://github.com/restatedev/sdk-sessions/blob/main/packages/sessions/README.md)**
  gives every key of a virtual object its own SQL database. We call these _session
  objects_, or _sessions_ for short. The database lives in Restate's state, so there is
  no separate database to run.
- **[`@restatedev/agents`](https://github.com/restatedev/sdk-sessions/blob/main/packages/agents/README.md)**
  runs AI agents inside sessions, with each conversation stored in its session's
  database. It supports pi, OpenCode, LangGraph, Claude and the DeepSeek Harness.

The app in [`src/app.ts`](src/app.ts) is a demo: notes per user, each user's notes in their
own database. Replace it with your own services. To learn sessions and agents step by
step, try [the tutorial](#the-tutorial).

## Before you start

Get the connect key of your Restate Cloud environment from
[**Configure SDK -> Create connect key**](https://cloud.restate.dev/to/developers/integration#configure-sdk).

The app connects to your Restate Cloud environment with `restate.connect`, at the end of
[`src/app.ts`](src/app.ts). It reads the key from `RESTATE_CONNECT_KEY`, and connects as
the deployment `notes-v1`, the name you register once (below).

## Run it locally

With Node 24 or later and pnpm:

```sh
pnpm install
RESTATE_CONNECT_KEY=… node src/app.ts
```

Then, once, [register `connect://notes-v1`](https://cloud.restate.dev/to/overview?register-deployment=connect://notes-v1)
in the Cloud UI (the application prints this link too), or with the CLI:

```sh
npx @restatedev/restate@1.8.1-hotfix.2 deployments register connect://notes-v1
```

Send a request from the [playground](https://cloud.restate.dev/to/overview?servicePlayground=notes).

To use a Restate server on your machine instead of Cloud, swap `restate.connect` for
`restate.serve` in [`src/app.ts`](src/app.ts): its comment shows both.

## Run it on Modal

[`modal/on_modal.py`](modal/on_modal.py) builds the image on Modal and runs `src/app.ts` in
one container, with your keys from a Modal secret:

```sh
pip install modal python-dotenv && modal setup
modal secret create restate-template RESTATE_CONNECT_KEY=${RESTATE_CONNECT_KEY}
modal deploy modal/on_modal.py
```

Register `connect://notes-v1` as above, and send requests the same way.
`modal app logs restate-template` follows it.

## Using client to send requests

Get the ingress key of your Restate Cloud environment from
[**Configure SDK -> Create ingress key**](https://cloud.restate.dev/to/developers/integration#configure-sdk),
and send requests with `@restatedev/restate-sdk-clients`:

```ts
import * as clients from '@restatedev/restate-sdk-clients';

const rs = clients.connect();
const alice = rs.objectClient({ name: 'notes' }, 'alice');
await alice.add('Buy milk');
console.log(await alice.list()); // ["Buy milk"]
```

## Session objects

A session object is a virtual object with a `schema` and a database, `ctx.db`. Each key
(`alice`, `bob`, …) gets its own SQLite-compatible database of up to 10 GiB. The demo app,
[`src/app.ts`](src/app.ts), keeps notes per user:

```ts
import * as restate from '@restatedev/sessions';

const notes = restate.sessionObject({
  name: 'notes',
  // Creates each key's database. Each statement runs once per key; append new ones later as needed.
  schema: ['CREATE TABLE notes (text TEXT NOT NULL)'],
  handlers: {
    add: async (ctx, note: string) => {
      await ctx.db.execute('INSERT INTO notes (text) VALUES (?)', [note]);
    },
  },
  views: {
    /** A view only reads, so it can run while `add` is writing. */
    list: async (ctx) => {
      const rows = await ctx.db.query<{ text: string }>('SELECT text FROM notes ORDER BY rowid');
      return rows.map(({ text }) => text);
    },
  },
});
```

The requests here go to a local Restate server's ingress; with Restate Cloud, send them
from the playground or with a client:

```sh
curl localhost:8080/notes/alice/add --json '"Buy milk"'
curl localhost:8080/notes/alice/list
```

Handlers run one at a time per key, and they are the only ones that write. Views can run at
any time, even while a handler is running, and only read what has been committed.

Each statement is durable once it returns. To commit several statements at once, put them
in `ctx.db.transaction(tx => …)`. Messages you send with `tx.send` inside a transaction go
out only if it commits.

Session handlers don't replay a journal after a failure. Restate simply runs the handler
again from the start, against whatever the database holds by then. That means a handler
should be safe to run twice, for example by recording a request or transfer id with its
writes. The
[`@restatedev/sessions` README](https://github.com/restatedev/sdk-sessions/blob/main/packages/sessions/README.md)
covers this, and how the storage works.

## Agents

An agent is a session whose conversation is stored in its database. If the process
crashes, or a tool waits a day for a person to answer, the agent picks up where it left
off.

Tools can be Restate itself. This support agent looks up orders with a service, waits for a
manager to approve a refund, and runs the refund as a workflow
([`examples/intermediate/support.ts`](https://github.com/restatedev/sdk-sessions/blob/main/packages/examples/intermediate/support.ts)):

```ts
const support = pi.agent({
  name: 'support',
  tools: [
    call(orders, 'status', {
      description: 'The status of an order.',
      input: z.object({ order: z.string() }),
    }),
    signal('approval', {
      description: "Wait for a manager to decide on a refund. Answers with the manager's decision.",
    }),
    workflow(refund, {
      description: 'Refund an order. Only once a manager approved it.',
      input: z.object({ order: z.string(), amount: z.number() }),
    }),
  ],
});
```

```sh
curl localhost:8080/support/alice/chat -d 'Order 103 arrived broken, can I get my $30 back?'
curl localhost:8080/support/alice/signal --json '{"name": "approval", "value": "approved"}'
```

To serve agents, add them to `services` in [`src/app.ts`](src/app.ts), together with `signals` from `@restatedev/agents`,
which their `signal` tools are answered through (as
[`src/tutorial/index.ts`](src/tutorial/index.ts) does). The models need their API key in the
environment, such as `OPENAI_API_KEY`: on Modal, add it to the secret.

The same agent runs on any of the supported frameworks. See
[`@restatedev/agents`](https://github.com/restatedev/sdk-sessions/blob/main/packages/agents/README.md)
and [the examples](https://github.com/restatedev/sdk-sessions/blob/main/packages/examples/README.md).

### Your own tools and tables

A tool is a function that gets the session's `ctx`, so it can use the same database as the
agent. This assistant stores what it learns about each user in a `facts` table next to the
conversation, and exposes the table through a view that a profile page could call
([`examples/basic/memory.ts`](https://github.com/restatedev/sdk-sessions/blob/main/packages/examples/basic/memory.ts)).
It is defined with `sessionObject` from `@restatedev/agents`: `restate.sessionObject` plus
the handlers every agent has (`status`, `stop`, `signal` and a few more):

```ts
import { sessionObject, tool } from '@restatedev/agents';
import * as pi from '@restatedev/agents/pi';
import { z } from 'zod';

const remember = tool({
  name: 'remember',
  description: 'Remember a fact about the user, for this conversation and later ones.',
  input: z.object({ fact: z.string() }),
  run: async ({ fact }, { ctx }) => {
    await ctx.db.execute('INSERT OR IGNORE INTO facts (fact) VALUES (?)', [fact]);
    return `Remembered: ${fact}`;
  },
});

const recall = tool({
  name: 'recall',
  description: 'Everything remembered about the user.',
  input: z.object({}),
  run: async (_input, { ctx }) => {
    const rows = await ctx.db.query<{ fact: string }>('SELECT fact FROM facts ORDER BY rowid');
    return rows.map(({ fact }) => fact);
  },
});

const assistant = sessionObject({
  name: 'assistant',
  // Your own table, in each user's database next to the agent's tables.
  schema: ['CREATE TABLE facts (fact TEXT PRIMARY KEY)'],
  handlers: {
    chat: pi.chat({
      system: 'You are a helpful assistant. Remember what you learn about the user, and recall it when it helps.',
      tools: [remember, recall],
    }),
  },
  views: {
    messages: pi.messages(),

    /** What the assistant knows about the user. A view, so it answers even while the agent is busy. */
    facts: async (ctx) => {
      const rows = await ctx.db.query<{ fact: string }>('SELECT fact FROM facts ORDER BY rowid');
      return rows.map(({ fact }) => fact);
    },
  },
});
```

```sh
curl localhost:8080/assistant/alice/chat -d 'I am vegetarian, and I live in Lisbon.'
curl localhost:8080/assistant/alice/chat -d 'Suggest a restaurant for tonight.'
curl localhost:8080/assistant/alice/facts
```

## The tutorial

Each lesson in [`src/tutorial`](src/tutorial) is one file: the wallet so far, plus one new
idea, explained in the comment at its top with the requests to try it.
[`src/tutorial/index.ts`](src/tutorial/index.ts) collects them all into one array,
`tutorial`. Every lesson's objects carry its number (`wallet01`, `wallet02`, …), so they
live side by side in one deployment, next to the notes.

The tutorial is off by default. To try it, include it in [`src/app.ts`](src/app.ts), as the
comment at its bottom shows:

```ts
import { tutorial } from './tutorial/index.ts';

const services = [notes, ...tutorial];
```

Lessons 09 to 16 ask OpenAI's models, so add `OPENAI_API_KEY` too: to your environment
locally, and on Modal to the secret (`modal secret create restate-template
RESTATE_CONNECT_KEY=… OPENAI_API_KEY=… --force`).

| Lesson                                                    | You learn                                                     |
| --------------------------------------------------------- | ------------------------------------------------------------- |
| **Part 1 · A database per key**                           |                                                               |
| [`01_object.ts`](src/tutorial/01_object.ts)               | A virtual object: handlers that Restate calls by key          |
| [`02_database.ts`](src/tutorial/02_database.ts)           | `ctx.db`: every wallet has its own SQL database               |
| [`03_views.ts`](src/tutorial/03_views.ts)                 | Views: reading the database while a handler is running        |
| [`04_schema.ts`](src/tutorial/04_schema.ts)               | Changing the tables of databases that already exist           |
| **Part 2 · Changes that happen once**                     |                                                               |
| [`05_transaction.ts`](src/tutorial/05_transaction.ts)     | Transactions: spending fails as a whole, leaving no trace     |
| [`06_retries.ts`](src/tutorial/06_retries.ts)             | Retries run a handler again: an id makes a deposit count once |
| [`07_calls.ts`](src/tutorial/07_calls.ts)                 | Calling another object, with an idempotency key               |
| [`08_sends.ts`](src/tutorial/08_sends.ts)                 | Transfers: a send that is delivered only if the debit commits |
| **Part 3 · Agents**                                       |                                                               |
| [`09_prompt.ts`](src/tutorial/09_prompt.ts)               | Asking a model from a handler, once                           |
| [`10_agent.ts`](src/tutorial/10_agent.ts)                 | An assistant in every wallet, with its own conversation       |
| [`11_tools.ts`](src/tutorial/11_tools.ts)                 | Tools that read the wallet's database                         |
| [`12_tool_writes.ts`](src/tutorial/12_tool_writes.ts)     | A tool that moves money, once per tool call                   |
| [`13_restate_tools.ts`](src/tutorial/13_restate_tools.ts) | Handlers as tools: paying a friend by their handle            |
| [`14_approval.ts`](src/tutorial/14_approval.ts)           | A person in the loop: confirming large transfers              |
| [`15_subagents.ts`](src/tutorial/15_subagents.ts)         | Delegating to another agent: a savings coach                  |
| **Appendix**                                              |                                                               |
| [`16_pi_durable.ts`](src/tutorial/16_pi_durable.ts)       | What `pi.prompt` does, written out with pi-durable            |

## Repository layout

- [`src/app.ts`](src/app.ts): the demo app, notes per user, and how it reaches Restate
  (Restate Cloud, or a local server).
- [`src/tutorial`](src/tutorial): the tutorial's lessons, off by default.
- [`modal/on_modal.py`](modal/on_modal.py): the Modal app, which builds the image and runs
  `src/app.ts` in one always-on container.

## Requirements

- Restate Cloud, or a Restate server 1.8 or later. To run one locally in Docker:

  ```sh
  docker run --rm -p 8080:8080 -p 9070:9070 --add-host=host.docker.internal:host-gateway \
    ghcr.io/restatedev/restate:1.8.0
  ```

- Node 24 or later (the code is TypeScript that Node runs directly), and pnpm.
- To deploy: a Modal account, and Python with `pip install modal python-dotenv`.

## Development

```sh
pnpm typecheck   # tsc
pnpm lint        # tsc, oxlint (type-aware) and oxfmt --check
pnpm format      # oxfmt
```

The libraries themselves, their examples and tests are in
[restatedev/sdk-sessions](https://github.com/restatedev/sdk-sessions).
