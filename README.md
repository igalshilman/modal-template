# A Restate application on Modal

This is the [`@restatedev/sessions` tutorial](https://github.com/restatedev/sdk-sessions/tree/main/packages/template),
deployed on [Modal](https://modal.com) and connected to
[Restate Cloud](https://cloud.restate.dev). You build one application step by
step: a wallet for every user. It starts as a Restate virtual object, gets its
own SQL database, learns to move money safely between wallets, and ends with
an AI assistant that pays your friends, asks you before large transfers, and
delegates to a savings coach.

Each lesson is one file that runs on its own: the wallet so far, trimmed to
what the lesson needs, plus one new idea. The comment at the top of each file
explains the idea, and lists the requests to try it.

## How it runs

The lesson connects *out* to Restate Cloud with `restate.connect` (the last
line of each lesson), so Modal exposes no port and no URL: one container runs
the lesson, always up, and Restate Cloud reaches it over that connection.
[`on_modal.py`](on_modal.py) builds the image on Modal (`pnpm install`) and
runs `node src/<lesson>.ts` in it.

## Before you start

You need a [Restate Cloud](https://cloud.restate.dev) environment and a
[Modal](https://modal.com) account.

In the Cloud UI, Development → Configure SDK, download your environment's
keys as a file, and save it here as `restate.env` (it is in `.gitignore`).
Then make it a Modal secret, once, with your OpenAI API key for lessons 09
to 16:

```sh
pip install modal python-dotenv && modal setup
modal secret create restate-template --from-dotenv restate.env OPENAI_API_KEY=sk-…
```

`on_modal.py` gives the secret to the container.

## Run a lesson

```sh
modal deploy on_modal.py                            # builds the image, runs lesson 01
LESSON=15_subagents modal deploy on_modal.py        # another lesson takes its place
```

Then, once, tell Restate Cloud about the deployment, named `template` in
`on_modal.py`: in the Cloud UI, register `connect://template`, or with the
[CLI](https://docs.restate.dev/develop/local_dev#running-restate-server--cli-locally)
logged into your environment:

```sh
restate deployments register connect://template
```

Now call the wallet through your environment's ingress: from the Cloud UI's
playground, or from code with the ingress key (Cloud UI → Development →
Configure Client) in `RESTATE_INGRESS_KEY`:

```ts
import * as clients from '@restatedev/restate-sdk-clients';

const rs = clients.connect({}); // the environment and the key from RESTATE_INGRESS_KEY
const alice = rs.objectClient({ name: 'wallet' }, 'alice');
console.log(await alice.hello()); // "Hello, alice!"
```

The requests to try are at the top of each lesson, as `curl` against a local
Restate: on Cloud, send the same paths and bodies through the ingress. The
Cloud UI shows every request and what it did.

To move on, deploy the next lesson and register again: the wallets you filled
in one lesson are still there in the next, just as a real application keeps
its data across releases. `modal app logs restate-template` follows the
lesson, and `modal app stop restate-template` stops it.

## Run it locally instead

Every lesson ends with the `restate.serve` line to use instead of
`restate.connect`, commented out. With it, and Node 24 or later:

```sh
pnpm install
node src/01_object.ts                                                           # the lesson, on port 9080
npx @restatedev/restate-server                                                  # Restate, in another terminal
npx @restatedev/restate -y deployments register --force http://localhost:9080   # tell Restate where it is
curl localhost:8080/wallet/alice/hello
```

## The lessons

### Part 1 · A database per key

| Lesson                                 | You learn                                              |
| -------------------------------------- | ------------------------------------------------------ |
| [`01_object.ts`](src/01_object.ts)     | A virtual object: handlers that Restate calls by key   |
| [`02_database.ts`](src/02_database.ts) | `ctx.db`: every wallet has its own SQL database        |
| [`03_views.ts`](src/03_views.ts)       | Views: reading the database while a handler is running |
| [`04_schema.ts`](src/04_schema.ts)     | Changing the tables of databases that already exist    |

### Part 2 · Changes that happen once

| Lesson                                       | You learn                                                     |
| -------------------------------------------- | ------------------------------------------------------------- |
| [`05_transaction.ts`](src/05_transaction.ts) | Transactions: spending fails as a whole, leaving no trace     |
| [`06_retries.ts`](src/06_retries.ts)         | Retries run a handler again: an id makes a deposit count once |
| [`07_calls.ts`](src/07_calls.ts)             | Calling another object, with an idempotency key               |
| [`08_sends.ts`](src/08_sends.ts)             | Transfers: a send that is delivered only if the debit commits |

### Part 3 · Agents

| Lesson                                           | You learn                                               |
| ------------------------------------------------ | ------------------------------------------------------- |
| [`09_prompt.ts`](src/09_prompt.ts)               | Asking a model from a handler, once                     |
| [`10_agent.ts`](src/10_agent.ts)                 | An assistant in every wallet, with its own conversation |
| [`11_tools.ts`](src/11_tools.ts)                 | Tools that read the wallet's database                   |
| [`12_tool_writes.ts`](src/12_tool_writes.ts)     | A tool that moves money, once per tool call             |
| [`13_restate_tools.ts`](src/13_restate_tools.ts) | Handlers as tools: paying a friend by their handle      |
| [`14_approval.ts`](src/14_approval.ts)           | A person in the loop: confirming large transfers        |
| [`15_subagents.ts`](src/15_subagents.ts)         | Delegating to another agent: a savings coach            |

### Appendix

| Lesson                                     | You learn                                          |
| ------------------------------------------ | -------------------------------------------------- |
| [`16_pi_durable.ts`](src/16_pi_durable.ts) | What `pi.prompt` does, written out with pi-durable |

## Next

[`@restatedev/sessions`](https://github.com/restatedev/sdk-sessions/tree/main/packages/sessions)
and [`@restatedev/agents`](https://github.com/restatedev/sdk-sessions/tree/main/packages/agents)
cover everything the lessons use, in full.
