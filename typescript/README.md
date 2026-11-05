# Restate on Modal: TypeScript

A [Restate](https://restate.dev) app in TypeScript that runs on [Modal](https://modal.com),
plus pointers to the libraries you can build on. Run every command below from this
directory, `typescript/`. The Python version is in [`../python`](../python).

## A quick outline of the relevant resources

- **[Connecting your code to Restate & Modal](#connecting-your-code-to-restate--modal)**:
  run locally, connect to Restate Cloud, deploy on Modal.
- **[Agent SDK](#agent-sdk)** (`@restatedev/agents`): a high-level agent SDK on session
  objects, with pi, OpenCode, LangGraph, Claude and the DeepSeek Harness.
- **[Session Objects](#session-objects)** (`@restatedev/sessions`): the Cloudflare Durable
  Objects / celld-like construct, with SQLite database per key.
- **[Restate agentlib](#restate-agentlib)** (`@restatedev/agentlib`): an agent harness built
  on journaling (not session objects).

All of these are Restate services, so they mix freely and call each other with exactly-once
RPC.

## Connecting your code to Restate & Modal

You need Node 24 or later and pnpm. The demo app in [`src/app.ts`](src/app.ts) is a template / hello-world example.

### Local Restate Server (OSS, for development)

In [`src/app.ts`](src/app.ts), swap `restate.connect(…)` for the `restate.serve(…)` line in
its comment. Then:

```sh
pnpm install
node src/app.ts                                   # your services, on port 9080
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
`restate.connect` at the end of [`src/app.ts`](src/app.ts) reads it from `RESTATE_CONNECT_KEY`
and connects as the deployment `notes-v1`:

```sh
pnpm install
RESTATE_CONNECT_KEY=… node src/app.ts
```

Once, [register `connect://notes-v1`](https://cloud.restate.dev/to/overview?register-deployment=connect://notes-v1)
in the Cloud UI (the app prints this link too), or with the CLI:

```sh
npx @restatedev/restate@1.8.1-hotfix.2 deployments register connect://notes-v1
```

Send requests from the [playground](https://cloud.restate.dev/to/overview?servicePlayground=notes),
or with a client and an ingress key
([**Configure SDK -> Create ingress key**](https://cloud.restate.dev/to/developers/integration#configure-sdk)):

```ts
import * as clients from '@restatedev/restate-sdk-clients';

const rs = clients.connect();
const alice = rs.objectClient({ name: 'notes' }, 'alice');
await alice.add('Buy milk');
console.log(await alice.list()); // ["Buy milk"]
```

### Deploy on Modal

[`modal/on_modal.py`](modal/on_modal.py) builds the image on Modal and runs `src/app.ts` in one
always-on container, which connects to Restate Cloud[^push]. Your keys come from a Modal secret:

```sh
pip install modal python-dotenv && modal setup
modal secret create restate-template RESTATE_CONNECT_KEY=${RESTATE_CONNECT_KEY}
modal deploy modal/on_modal.py
```

Register `connect://notes-v1` as above. `modal app logs restate-template` follows the app.
Model API keys (such as `OPENAI_API_KEY`) go in the same secret.

[^push]:
    **Why not "push" to Modal?** We suspect an edge case with long-lived HTTP/2 connections
    between Restate Cloud and Modal, possibly an interaction between HTTP clients and API
    gateways or load balancers: longer-running functions sometimes get stuck. While we
    investigate, and to save you the friction, your code connects to Restate Cloud instead
    of Restate Cloud pushing to Modal. Push is what we want in the future.

## Agent SDK

[`@restatedev/agents`](https://github.com/restatedev/sdk-sessions/tree/main/packages/agents)
shows how to structure a high-level agent SDK on session objects. It adds integrations for
pi, OpenCode, LangGraph, Claude and the DeepSeek Harness. Each agent is a session object
with its conversation in its own database. You can still write workflows as plain Restate
handlers and call other services.

```ts
import { tool } from '@restatedev/agents';
import * as pi from '@restatedev/agents/pi';
import { z } from 'zod';

const weather = tool({
  name: 'get_weather',
  description: 'The current weather in a city.',
  input: z.object({ city: z.string() }),
  run: ({ city }) => `Sunny and 21°C in ${city}`,
});

const assistant = pi.agent({ name: 'assistant', tools: [weather] });
```

To serve agents, add them to `services` in [`src/app.ts`](src/app.ts), together with `signals`
from `@restatedev/agents`.

## Session Objects

A session object is a virtual object with a `schema` and a database, `ctx.db`: the Cloudflare
Durable Objects / celld-like API. Each key (`alice`, `bob`, …) gets its own SQLite-compatible
database of up to 10 GiB, stored in Restate's state, so there is no separate database to run.
This is what powers the pi and OpenCode integrations.

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

- Handlers run one at a time per key and are the only ones that write. Views read committed
  data at any time.
- `ctx.db.transaction(tx => …)` commits several statements at once; `tx.send` messages go out
  only if it commits.
- No journal replay: after a failure the handler runs again from the start, so make it safe
  to run twice (for example, record a request id with its writes).

**Dependency:** [`@restatedev/sessions`](https://www.npmjs.com/package/@restatedev/sessions),
from [restatedev/sdk-sessions](https://github.com/restatedev/sdk-sessions) (a staging ground;
it moves into the main SDK soon). Docs: the
[`@restatedev/sessions` README](https://github.com/restatedev/sdk-sessions/blob/main/packages/sessions/README.md).

**Tutorial:** [`src/tutorial`](src/tutorial), one idea per file: a database per key (01–04),
changes that happen once (05–08), agents (09–16). To run it, in [`src/app.ts`](src/app.ts)
comment out `const services = [notes];` and uncomment the two lines below it. Lessons 09–16
need `OPENAI_API_KEY`.

## Restate agentlib

[`@restatedev/agentlib`](https://github.com/restatedev/agentlib) is an agent SDK (harness)
built directly on Restate functions and virtual objects. Model calls, tool results and approvals are journaled,
and on recovery Restate replays the journal, skipping completed steps. It does not use
session objects.

```sh
npm install @restatedev/agentlib @restatedev/restate-sdk @restatedev/restate-sdk-gen
```

Start from the [agentlib template](https://github.com/restatedev/agentlib-template) or the
[numbered examples](https://github.com/restatedev/agentlib/blob/main/packages/examples/README.md).

To build your own harness, [restatedev/agent](https://github.com/restatedev/agent) is an even
more detailed reference: steerable, concurrent agents with approvals, sandboxed code,
sub-agents, schedules and memory.
