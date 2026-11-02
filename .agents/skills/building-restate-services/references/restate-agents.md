# Agents on session objects (`@restatedev/agents`)

`@restatedev/agents` runs an agent of one of five frameworks (pi, OpenCode, LangGraph,
Claude, the DeepSeek Harness) inside a Restate session object. The conversation lives in
the object's SQL database. A crash, a restart, or a person who takes a day to approve
changes nothing: each message is answered once, and each tool call is made once.

An agent **is a session object**, so [session-objects.md](session-objects.md) applies to it
and to every handler you add to it: no journal replay, no `ctx.run`, `Promise.all` is fine,
and handlers must be safe to run twice. **Do not apply `ai-agents.md` or
`ts/api-and-pitfalls.md` to these agents.** Those are for agents written by hand in
journaled handlers, which wrap every model call in `ctx.run`. Here, the integration stores
each step in the database for you.

The full documentation ships with the package: `node_modules/@restatedev/agents/README.md`,
and per framework `node_modules/@restatedev/agents/src/{pi,opencode,langgraph,claude,deepseek}/README.md`.

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

export const assistant = pi.agent({ name: 'assistant', tools: [weather] });
```

Each key (`assistant/alice`) is a conversation with its own database, answering one message
at a time.

**Serving it.** In this repository, add it to `services` in `src/app.ts`, **together with
`signals`**, the object every agent uses for its waits, steering and status:

```ts
import { signals } from '@restatedev/agents';
const services = [notes, assistant, signals];
```

`signals` belongs in the list once, however many agents you serve. (`serve(...)` of
`@restatedev/agents` adds it by itself, but this repository serves with
`restate.connect` / `restate.serve`.)

## Choose a framework

| Import                         | Framework                 | Choose it when                                                        | Packages it needs                                                                            |
| ------------------------------ | ------------------------- | --------------------------------------------------------------------- | -------------------------------------------------------------------------------------------- |
| `@restatedev/agents/pi`        | pi-durable                | The default: any provider, coding tools on request, compact and reset | `@earendil-works/pi-durable`, `pi-ai`, `chord`                                               |
| `@restatedev/agents/opencode`  | OpenCode 2.0, embedded    | A coding agent with OpenCode's tools in a directory                   | `@opencode/{core,plugin,sdk,server}@2.0.32`, `effect@4.0.1` (pinned)                         |
| `@restatedev/agents/langgraph` | LangGraph                 | You use LangChain tools, or a chat model of your own                  | `@langchain/core`, `langgraph`, `langgraph-checkpoint`, `@langchain/openai` (or `anthropic`) |
| `@restatedev/agents/claude`    | Anthropic SDK tool runner | Claude with nothing in between                                        | `@anthropic-ai/sdk`                                                                          |
| `@restatedev/agents/deepseek`  | DeepSeek Harness          | DeepSeek's harness and models                                         | `@deepseek-ai/*@0.2.1-rc.2`, `@earendil-works/pi-ai`                                         |

The frameworks are optional peer dependencies: install only those you import. A subpath
whose packages are missing fails as it is imported, naming the first it lacks. OpenCode
builds a native module (`tree-sitter-powershell`) from source on Linux, which needs `make`
and `g++` in the image.

Every framework takes `model`, `system`, `tools` and `output`; pi and OpenCode take a
`workspace` (a directory for their coding tools). Every agent also takes `description` (for
the UI and a parent's model), `background` and `schema` (tables of your own).

## Models

`model` is `provider/model-id`, or else the `MODEL` environment variable, or else
`openai/gpt-6-sol` with `OPENAI_API_KEY`. Claude defaults to `anthropic/claude-sonnet-5-5`
(`ANTHROPIC_API_KEY`) and the DeepSeek Harness to `deepseek/deepseek-flash`
(`DEEPSEEK_API_KEY`). A missing key or unknown model fails with a terminal error that says
what to check, rather than retrying. The key goes in the environment: on Modal, in the
Modal secret.

## Tools

```ts
import { call, send, signal, subagent, tool, workflow } from '@restatedev/agents';
```

| Tool                                                           | What the model gets                                                                                                                                   |
| -------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| `tool({ name, description, input, run })`                      | Your function. `input` is a zod object; `run(input, { ctx, callId, idempotencyKey })` returns text or JSON. `ctx` is the session's, so `ctx.db` works |
| `call(target, handler, { description, input?, key? })`         | Calls a handler of a service, object or workflow. Of an object, the model picks the key unless `key` gives it                                         |
| `send(target, handler, { description, input?, key?, delay? })` | A one-way call, after `delay` if given                                                                                                                |
| `workflow(target, { description, input?, key? })`              | Runs a workflow to the end; one per tool call unless `key` gives its id                                                                               |
| `signal(name, { description, input? })`                        | Waits for a value from outside (a person's approval) without holding a process                                                                        |
| `subagent(agent, { description?, handler?, name? })`           | Hands a named task to another agent, keyed `<this key>.<task>`; the same name continues the task                                                      |

- **Errors:** a `TerminalError` from a tool (or from a handler it calls) becomes the tool's
  answer to the model, `Error: <message>`, and the agent goes on. So do arguments that don't
  fit `input`. Any other error fails the attempt, and Restate retries it.
- **Once:** a crash runs an unfinished tool call again with the same call id. A tool that
  must not run twice passes its `idempotencyKey` on (to an API, or as a stable id it records
  in `ctx.db`), as Restate's own tools do.
- **Per invocation:** `pi.chat(async (ctx) => ({ tools: await toolsOf(ctx) }))`.

## Signals: a person in the loop

```ts
signal('approval', {
  description: 'Wait for a manager to approve a refund.',
  input: z.object({ order: z.string(), amount: z.number() }),
});
```

Every agent has the views `pending` (its waits) and `signal` (resolve one):

```sh
curl localhost:8080/support/alice/pending
curl localhost:8080/support/alice/signal --json '{"id": "<the wait id>", "value": "approved"}'
curl localhost:8080/support/alice/signal --json '{"name": "approval", "value": "approved"}'   # the oldest wait of that name
```

A signal no one waits for is dropped, unless it has `"keep": true`.

## Structured answers

With `output`, a zod object, the agent's answer is a checked value, not text:

```ts
const Plan = z.object({ summary: z.string(), parts: z.array(z.string()) });
const planner = pi.agent({ name: 'planner', output: Plan });
const plan = await ctx.rpc(planner, 'ENG-1').chat('Plan the work on ENG-1'); // a Plan
```

## Your own session object, with an agent in it

`agent()` is a session object with `chat` and `messages`. For handlers and tables of your
own, use `sessionObject` of `@restatedev/agents`, which sets up what agents need:

```ts
import { sessionObject, tool } from '@restatedev/agents';
import * as pi from '@restatedev/agents/pi';

const memory = sessionObject({
  name: 'memory',
  schema: ['CREATE TABLE facts (fact TEXT PRIMARY KEY)'], // yours; never name a table restate_…
  handlers: {
    chat: pi.chat({ system: 'Remember what you learn about the user.', tools: [remember, recall] }),
    forget: async (ctx, fact: string) => {
      await ctx.db.execute('DELETE FROM facts WHERE fact = ?', [fact]);
    },
  },
  views: {
    messages: pi.messages(),
    facts: (ctx) => ctx.db.query('SELECT fact FROM facts'),
  },
});
```

- Your handlers and views can't be named `signal`, `pending`, `status`, `stop`, `steer`,
  `notifications`, `watch`, `sync`, `clear` or `erase`: every agent has those.
- `chat` takes options or a function of the context giving them (each user's model and
  persona from `ctx.db`, say).
- `prompt(ctx, text, options)` asks a model once from any handler, however often the handler
  runs: `summary: async (ctx) => pi.prompt(ctx, 'Describe these entries…')`.
  `chatHandler(answer)` makes a handler that takes its message as `chat` does.

## Webhooks

`webhook({ name, auth, idempotencyHeader, route, key, message? })` is a service at
`/<name>/webhook` that checks each delivery's HMAC signature and delivers it to the agents
of `route`, keyed by `key(body)`. A delivery sent again (same idempotency header) reaches
the same message.

## Calling an agent

Through Restate's ingress (the body is the message; the answer is a JSON string):

```sh
curl localhost:8080/assistant/alice/chat -d 'Hi, I am Alice'
curl localhost:8080/assistant/alice/chat/send -d 'Plan my week'      # don't wait: answers with the invocation id
curl localhost:8080/restate/invocation/<id>/attach                  # its answer, once there is one
curl localhost:8080/assistant/alice/chat/send -H 'idempotency-key: msg-1' -d 'Plan my week'   # send again safely
curl localhost:8080/assistant/alice/messages                         # the conversation, with tool calls
curl localhost:8080/assistant/alice/status                           # what it answers, and waits for
curl localhost:8080/assistant/alice/steer -d 'Only Monday, please'   # add to the message being answered
curl localhost:8080/assistant/alice/stop                             # stop the turn
curl localhost:8080/assistant/alice/clear                            # forget the conversation
```

From a Restate handler: `await ctx.rpc(assistant, 'alice').chat('Hi')`. From other code (a
web app): `@restatedev/restate-sdk-clients` with `agent(name)` and `follow(...)` of
`@restatedev/agents/client`, which imports nothing of the agent's code.

## Before finishing (agents)

- [ ] [session-objects.md](session-objects.md)'s checklist holds for every handler you added
- [ ] `signals` is in `services` once, next to the agents
- [ ] The framework's packages are installed, and the model's API key is in the environment
      (and in the Modal secret, for a deployment)
- [ ] Tools that change something outside pass their `idempotencyKey` on
- [ ] Permanent tool failures throw `TerminalError`, so the model gets the message
- [ ] The agent answered a message through Restate (curl or the playground)
