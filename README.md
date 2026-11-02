# A Restate application on Modal

A Restate application using SQLite running on [Modal](https://modal.com), connected to
[Restate Cloud](https://cloud.restate.dev). It serves a tutorial: a wallet per user, from
a SQL database per key to agents, one idea per lesson.

## Before you start

Get the connect key of your Restate Cloud environment from
[**Configure SDK -> Create connect key**](https://cloud.restate.dev/to/developers/integration#configure-sdk).
Lessons 09 to 16 ask OpenAI's models, so get an OpenAI API key too.

## Run it locally

With Node 24 or later and pnpm:

```sh
pnpm install
RESTATE_CONNECT_KEY=… OPENAI_API_KEY=… node src/app.ts
```

Then, once, [register `connect://tutorial-v1`](https://cloud.restate.dev/to/overview?register-deployment=connect://tutorial-v1)
in the Cloud UI (the application prints this link too), or with the CLI:

```sh
npx @restatedev/restate@1.8.1-hotfix.2 deployments register connect://tutorial-v1
```

Send requests from the [playground](https://cloud.restate.dev/to/overview?servicePlayground=wallet01).

To use a Restate server on your machine instead of Cloud, swap `restate.connect` for
`restate.serve` in [`src/app.ts`](src/app.ts): its comment shows both.

## Run it on Modal

[`modal/on_modal.py`](modal/on_modal.py) builds the image on Modal and runs `src/app.ts` in
one container, with your keys from a Modal secret:

```sh
pip install modal python-dotenv && modal setup
modal secret create restate-template RESTATE_CONNECT_KEY=${RESTATE_CONNECT_KEY} OPENAI_API_KEY=${OPENAI_API_KEY}
modal deploy modal/on_modal.py
```

Register `connect://tutorial-v1` as above, and send requests the same way.
`modal app logs restate-template` follows it.

## The tutorial

Each lesson in [`src/tutorial`](src/tutorial) is one file: the wallet so far, plus one new
idea, explained in the comment at its top with the requests to try it.
[`src/tutorial/index.ts`](src/tutorial/index.ts) collects them all into one array,
`tutorial`, which `src/app.ts` serves. Every lesson's objects carry its number
(`wallet01`, `wallet02`, …), so they live side by side in one deployment.

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

The lessons' requests use `curl localhost:8080/...`, a local Restate server's ingress. With
Restate Cloud, use your environment's ingress URL and an ingress key instead, or a client
(below).

## Using client to send requests

Get the ingress key of your Restate Cloud environment from
[**Configure SDK -> Create ingress key**](https://cloud.restate.dev/to/developers/integration#configure-sdk).

Then send requests using `@restatedev/restate-sdk-clients`:

```ts
import * as clients from '@restatedev/restate-sdk-clients';

const rs = clients.connect();
const alice = rs.objectClient({ name: 'wallet01' }, 'alice');
console.log(await alice.hello()); // "Hello, alice!"
```

## Development

```sh
pnpm typecheck   # tsc
pnpm lint        # tsc, oxlint (type-aware) and oxfmt --check
pnpm format      # oxfmt
```
