# Agents on session objects (`@restatedev/agents`)

`@restatedev/agents` runs an agent of one of four frameworks (pi, LangGraph, Claude, the
DeepSeek Harness) inside a Restate session object. The conversation lives in the object's
SQL database, as a conversation of turns: each turn is a message, the model's replies and
tool calls that answered it, and its answer. A crash, a restart, or a person who takes a day
to approve changes nothing: each message is answered once per invocation (a message resent
without an idempotency key is a new one), and Restate's own tools make each call once. Tools
of your own need care: see "Tools that must not run twice".

An agent **is a session object**, so [session-objects.md](session-objects.md) applies to it
and to every handler you add to it: no journal replay, no `ctx.run`, `Promise.all` is fine,
and handlers must be safe to run twice. **Do not apply `ai-agents.md` or
`ts/api-and-pitfalls.md` to these agents.** Those are for agents written by hand in
journaled handlers, which wrap every model call in `ctx.run`. Here, the framework's state
is stored in the database step by step, and a retried attempt resumes from it.

More in this skill: [agents-frameworks.md](agents-frameworks.md) (each framework's options,
crash behaviour and API) and [agents-operations.md](agents-operations.md) (calling and
following an agent, turns, steering and stopping, failures, testing, deploying). The
package's own documentation: `node_modules/@restatedev/agents/README.md`, and per framework
`node_modules/@restatedev/agents/src/{pi,langgraph,claude,deepseek}/README.md`. Its source is
in `node_modules/@restatedev/agents/src/`, readable TypeScript. How turns are answered,
stored, steered and closed, in depth (not in the npm package):
[docs/](https://github.com/restatedev/sdk-sessions/tree/main/packages/agents/docs), its
`turns.md` and `conversation.md`.

## Start

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

export const assistant = pi.agent({ name: 'assistant', system: 'Answer briefly.', tools: [weather] });
```

Each key (`assistant/alice`) is a conversation with its own database, answering one message
at a time, in the order they came.

**Serving it.** In this repository, add it to `services` in `src/app.ts`:

```ts
const services = [notes, assistant];
```

Each agent brings its **companion**, a virtual object of its own named
`<agent>.prebuilt.restate` (`assistant.prebuilt.restate`), keyed as the agent, which keeps its
waits and status. Never list it. **`restate.connect`**, what this repository commits, serves
exactly the services it is given, so `src/app.ts` passes them through
`restate.served(services)`, which adds each agent's companion, once: keep that call.
`restate.serve(...services)` of `@restatedev/sessions` (and `serve` of `@restatedev/agents`,
the same function) does it by itself.

## Choose a framework

| Import                         | Framework                 | Choose it when                                                                                             |
| ------------------------------ | ------------------------- | ---------------------------------------------------------------------------------------------------------- |
| `@restatedev/agents/pi`        | pi-durable                | The default: any provider pi-ai knows, coding tools on request (`workspace`), the Harness (compact, reset) |
| `@restatedev/agents/langgraph` | LangGraph                 | You use LangChain: its tools, a chat model of your own, or a graph of your own                             |
| `@restatedev/agents/claude`    | Anthropic SDK tool runner | Claude with nothing in between: the lightest, the API's own messages; Anthropic models only                |
| `@restatedev/agents/deepseek`  | DeepSeek Harness          | DeepSeek's harness and models, or any model pi-ai knows; tool calls that wait for an approval              |

There is no OpenCode agent any more (it was one up to 0.3.0): for a coding agent, use pi with a
`workspace`.

Each framework's packages are optional peer dependencies: install only those you import
(the list per framework is in [agents-frameworks.md](agents-frameworks.md)). A subpath whose
packages are missing fails as it is imported, naming the first it lacks.

Every framework's `agent()` takes `name`, `model`, `system`, `tools` and `output`; pi takes
a `workspace` too. Every agent also takes:

| Option        | What                                                                                                         |
| ------------- | ------------------------------------------------------------------------------------------------------------ |
| `description` | What it is, for the UI, and for a parent's model when it is a `subagent`                                     |
| `background`  | It works unwatched (a subagent): followers see each turn once it ended, and it takes no steered messages     |
| `schema`      | Tables of your own in its database (never named `restate_…`)                                                 |
| `window`      | How many of the latest answered turns the model sees whole, with their tool calls (default 1), or `'all'`    |
| `budget`      | How many tokens of the turns before the window the model sees, as their messages and answers (default 32000) |
| `summarize`   | `(ctx, request) => summary`: summarizes the turns past `budget`, after an answer                             |

`system` is the whole system prompt for Claude and LangGraph, and is added to the
framework's own (which describes its tools) for pi and DeepSeek.

**What the model sees.** For Claude and LangGraph's built-in agent, the conversation of
turns: the summary of the earliest turns (if any), the turns before the window as their
message and answer, within `budget`, and the latest `window` turns whole. Their `agent()`
summarizes the turns past the budget with its own model, in an invocation of its own after
the answer (in a `sessionObject` of your own: `summarize: claude.summarizer(options)`, or
`langgraph.summarizer(model)`; without one, the earliest turns are only left out). pi and
the DeepSeek Harness keep their own history and compact it themselves; a LangGraph graph of
your own sees its own state. Whatever the model sees, `messages` shows every turn as it was
said: summaries and compactions change only what the model gets. One object holds one
framework's conversation.

## Models

`model` is `provider/model-id`, or else the `MODEL` environment variable, or else
`openai/gpt-6-sol` with `OPENAI_API_KEY`. Claude defaults to `anthropic/claude-sonnet-5-5`
(`ANTHROPIC_API_KEY`), the DeepSeek Harness to `deepseek/deepseek-flash`
(`DEEPSEEK_API_KEY`).

- pi and the DeepSeek Harness take any provider they know (DeepSeek, pi-ai's); LangGraph
  OpenAI's and Anthropic's (or any LangChain chat model object as `model`); Claude
  Anthropic's only.
- A model that isn't `provider/model-id`, or of a provider the framework doesn't take
  (Claude: Anthropic only; LangGraph: OpenAI and Anthropic; DeepSeek: those pi-ai knows),
  fails when the agent is defined. A missing or wrong key, or a model the provider doesn't know, fails the
  message at once with a terminal error (HTTP 424) that says what to check, rather than
  retrying.
- The key goes in the environment: on Modal, in the Modal secret.
- A model changed while a conversation goes on is the model of its next turn.

## Tools

```ts
import { call, send, signal, subagent, tool, workflow } from '@restatedev/agents';
```

| Tool                                                                  | What the model gets                                                                                                                        | Default tool name    |
| --------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ | -------------------- |
| `tool({ name, description, input, run })`                             | Your function. `input` is a zod object; `run(input, { ctx, callId, idempotencyKey })` returns text, or anything JSON (nothing is "done")   | `name`               |
| `call(target, handler, { description, input?, key?, name? })`         | Calls a handler of a service, object or workflow, and answers with its result. Of an object, the model picks the key unless `key` gives it | `<target>_<handler>` |
| `send(target, handler, { description, input?, key?, delay?, name? })` | A one-way call, after `delay` if given                                                                                                     | `<target>_<handler>` |
| `workflow(target, { description, input?, key?, name? })`              | Runs a workflow's `run` to the end; one workflow per tool call (id `<agent key>-<call id>`) unless `key` gives it                          | `<target>`           |
| `signal(name, { description, input?, name? })`                        | Waits for a value from outside (a person's approval) without holding a process                                                             | `wait_for_<name>`    |
| `subagent(agent, { description?, name?, handler? })`                  | Hands a named task to another agent (any framework), keyed `<this key>.<task>`; the same task name continues it                            | the agent's name     |

- `ctx` in `run` is the session's context: `ctx.db`, `ctx.rpc`, `ctx.send`, `ctx.key`. It has
  **no `ctx.run`**. To call an outside API safely, see
  [session-objects.md](session-objects.md), "Side effects outside Restate".
- Handler names are checked against the target's handlers at compile time. `key` is a string
  or a function of the context giving one.
- **Errors:** a `restate.TerminalError` thrown by `run` (or by a handler it calls) becomes the
  tool's answer to the model, `Error: <message>`, and the agent goes on. So do arguments that
  don't fit `input` (`run` never sees them), and a call of a tool the agent doesn't have. Any
  other error fails the attempt, and Restate retries it: the tool call runs again.
- **Per invocation** (each user's tools): `pi.chat(async (ctx) => ({ tools: await toolsOf(ctx) }))`.

### Tools that must not run twice

An agent, like any session object, is delivered at least once, so its tools can run more
than once: see "Delivery semantics" in [session-objects.md](session-objects.md) for the
layers (an attempt, a caller resending a message, the same operation later). A crash can
cut a tool call off. What happens next depends on the framework:

| Framework             | After a crash cut a tool call off                                                              | So a tool that changes something outside                                                                  |
| --------------------- | ---------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| pi, LangGraph, Claude | The same tool call runs again, **with the same `callId`**                                      | Passes `idempotencyKey` (`<invocation id>:<call id>`) on: to the API, or as the id it records in `ctx.db` |
| DeepSeek Harness      | The model is told the call was interrupted, and makes **a new tool call, with a new `callId`** | Also takes the id of the call it retries as input (`retryOf`), and tells the model so in its description  |

Restate's own tools (`call`, `send`, `workflow`, `subagent`, `signal`) need nothing: made
again with the same input, the call is the one the cut-off call made. For a tool of your own
that works on every framework, the `retryOf` pattern:

```ts
const transfer = tool({
  name: 'transfer',
  description:
    'Move money between accounts. If an earlier transfer was interrupted, or its outcome is unknown, ' +
    'retry it with `retryOf` set to its tool call id: the money then moves once.',
  input: z.object({
    from: z.string(),
    to: z.string(),
    amount: z.number().int().positive(),
    retryOf: z.string().optional().describe('The tool call id of the transfer this one retries'),
  }),
  run: async ({ from, to, amount, retryOf }, { ctx, callId }) => {
    const id = retryOf ?? callId; // a retry of an earlier call is that call's transfer
    // The agent's schema has the table; an outside API would get `id` as its idempotency key.
    await ctx.db.execute('INSERT OR IGNORE INTO transfers (id, src, dst, amount) VALUES (?, ?, ?, ?)', [
      id,
      from,
      to,
      amount,
    ]);
    return `Moved ${amount} from ${from} to ${to}`;
  },
});
```

## Signals: a person in the loop

```ts
const approval = signal('approval', {
  description: 'Wait for a manager to approve a refund. Answers with the decision.',
  input: z.object({ order: z.string(), amount: z.number() }),
});
```

Every agent has the views `pending` (its waits) and `signal` (resolve one). Use `/send` for
the message, since its answer waits for the approval:

```sh
curl localhost:8080/support/alice/chat/send -d 'Refund my $30 for order 103'
curl localhost:8080/support/alice/pending
curl localhost:8080/support/alice/signal --json '{"id": "<the wait id>", "value": "approved"}'
curl localhost:8080/support/alice/signal --json '{"name": "approval", "value": "approved"}'   # the oldest wait of that name
```

`signal` answers `{"resolved": <id>}`, or `{"resolved": null}` if nothing waited: then the
value is dropped, unless it has `"keep": true`, which keeps it for the next wait of its name.
A wait ends with its invocation: a stopped turn leaves `pending`. Two frameworks wait the
same way without a `signal()` tool: a DeepSeek agent's tool calls named by its `approval`
option wait for the signal `approval` before they run, and `interrupt()` in a LangGraph graph
of your own waits for the signal `interrupt` (agents-frameworks.md).

`signal()` is a tool, so calling it is the model's choice, guided by the descriptions: use it
as it is for approvals the model should ask for. If an approval is a hard rule (a refund over
$50 must never happen without one), enforce it in code: put the action in a journaled
workflow that waits for the approval itself (a durable promise), and give the agent a
`workflow()` tool for it.

## Structured answers

With `output`, a zod object, the agent's answer is a checked value, not text:

```ts
const Plan = z.object({ summary: z.string(), parts: z.array(z.string()) });
const planner = pi.agent({ name: 'planner', output: Plan });
// in a handler: const plan = await ctx.rpc(planner, 'ENG-1').chat('Plan the work on ENG-1'); // a Plan
```

A reply that isn't such JSON is answered once with what's wrong, for the model to reply
again; then the invocation fails with a terminal error, and the conversation shows the turn
failed. Claude asks for it natively where the model has structured outputs (the API's
`output_config.format`; `nativeOutput: false` turns that off); the other frameworks ask in the
system prompt. `prompt(ctx, text, { output })` answers with one too, and a parent's model
gets a subagent's as JSON.

## Your own session object, with an agent in it

`agent()` is a session object with `chat` and `messages`. For handlers and tables of your
own, use `sessionObject` of `@restatedev/agents` (not of `@restatedev/sessions`): it adds what
agents need (the built-in views, retries for weeks, its companion):

```ts
import { sessionObject } from '@restatedev/agents';
import * as pi from '@restatedev/agents/pi';

const memory = sessionObject({
  name: 'memory',
  schema: ['CREATE TABLE facts (fact TEXT PRIMARY KEY)'], // yours, beside the agent's restate_… tables
  handlers: {
    chat: pi.chat({ system: 'Remember what you learn about the user.', tools: [remember, recall] }),
    forget: async (ctx, fact: string) => {
      await ctx.db.execute('DELETE FROM facts WHERE fact = ?', [fact]);
    },
  },
  views: {
    messages: pi.messages(), // a view, never a handler: with it, the object is an agent
    facts: (ctx) => ctx.db.query<{ fact: string }>('SELECT fact FROM facts'),
  },
});
```

- **Reserved names:** your handlers and views can't be named `signal`, `pending`, `status`,
  `stop`, `notifications` or `watch` (every object's), nor `sync`, `clear`, `steer`,
  `erase`, `settle`, `compact` or `steered` (an agent's: one with a `messages` view).
  Defining one throws, and doesn't type-check. A handler that compacts pi's conversation
  needs another name (`shorten`, say: tutorial lesson 16).
- `chat` takes options, or a function of the context giving them (each user's model and
  persona from `ctx.db`): `pi.chat(async (ctx) => ({ model: await modelOf(ctx) }))`.
- `prompt(ctx, text, options)` asks a model from any handler, once however often the handler
  runs; each prompt of an invocation is its own: `pi.prompt(ctx, 'Describe these entries…')`.
- `chatHandler(answer)` makes a handler that takes its message as `chat` does (text, or a
  JSON string): `recap: chatHandler(async (ctx, topic) => pi.prompt(ctx, …))`. A `chat` made
  so answers each steered message as a turn of its own; only a framework's own `chat()` takes
  them mid-turn, and a `chat` that is neither refuses `steer`.
- Its own options (`retryPolicy`, …) go in `options`, and add to the defaults: retries start
  50 ms after a failure, doubling up to 10 s apart, for up to 100,000 attempts.
- Your tables share the database with the agent's, whose names all start with `restate_`
  (`restate_agent_turns`, `restate_agent_items`, `restate_agent_steers`, `restate_pi_tasks`, …).
  Read the conversation through `messages`, not those tables.

## Webhooks

`webhook({ name, auth, idempotencyHeader, route, key, message?, description? })` is a service
at `/<name>/webhook` that checks each delivery's HMAC-SHA256 signature (`auth: { header,
secret }`; 401 otherwise) and delivers it to the agents of `route`, keyed by `key(body)`
(`undefined` drops it). A delivery sent again (same idempotency header) reaches the same
message. A delivery is a message of its own to the agent's `chat`, which reads it as
`<webhook name="…" delivery="…">{json}</webhook>`, and answers it after the message it works
on, if any, even a stopped one: a delivery is never dropped. From any handler, for events of
other kinds (a queue, a schedule): `deliver(ctx, agent, key, text, { idempotencyKey })`, a
message of the same kind.

## Before finishing (agents)

- [ ] [session-objects.md](session-objects.md)'s checklist holds for every handler you added
- [ ] The agents are in `services`, and `src/app.ts` still connects `restate.served(services)`
- [ ] The framework's packages are installed, and the model's API key is in the environment
      (and in the Modal secret, for a deployment)
- [ ] Tools that change something outside are safe to repeat for their framework: the
      `idempotencyKey` passed on (pi, LangGraph, Claude), or `retryOf` as well (the DeepSeek
      Harness)
- [ ] Permanent tool failures throw `TerminalError`, so the model gets the message
- [ ] No handler or view of yours has a reserved name, and `messages` is a view
- [ ] The agent answered a message through Restate (curl or the playground)
