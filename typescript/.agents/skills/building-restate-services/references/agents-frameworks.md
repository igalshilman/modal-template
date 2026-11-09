# The frameworks of `@restatedev/agents`

Every framework's agent has the same shape: `agent({ name, model, system, tools, output, ... })`,
with the handler `chat` and the views `messages`, `status`, `steer`, `stop`, `clear`, `sync`,
`notifications`, `watch`, `pending`, `signal`. For a session object of your own, each has
`<framework>.chat(options)` (the handler), `<framework>.messages()` (the view) and
`<framework>.prompt(ctx, text, options)`. `options` may be a function of the context. The
general rules are in [restate-agents.md](restate-agents.md); this page is what differs. The
full READMEs: `node_modules/@restatedev/agents/src/<framework>/README.md`.

## At a glance

|                                        | pi                                                                                 | LangGraph                                                                                  | Claude                                       | DeepSeek Harness                                                                |
| -------------------------------------- | ---------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------ | -------------------------------------------- | ------------------------------------------------------------------------------- |
| Models                                 | Any pi-ai provider                                                                 | OpenAI's, Anthropic's, or a LangChain chat model                                           | Anthropic's only                             | DeepSeek's, or any pi-ai provider                                               |
| Default model                          | `openai/gpt-6-sol`                                                                 | `openai/gpt-6-sol`                                                                         | `anthropic/claude-sonnet-5-5`                | `deepseek/deepseek-flash`                                                       |
| What the model sees of earlier turns   | pi's own history, which pi compacts                                                | The conversation of turns (`window`, `budget`, summaries); a graph of your own, its state  | The conversation of turns                    | The harness's own session, which it compacts (`compaction`)                     |
| A steered message is taken             | As a round of tool calls ends, after their results                                 | Before each model request that follows tool results; a graph of your own takes none        | Before each model request after tool results | At the step after the next model request                                        |
| Coding tools                           | `workspace` (read, write, edit, bash)                                              | Your tools                                                                                 | Your tools (or the SDK's agent toolset)      | Your tools                                                                      |
| Tool call cut off by a crash           | Runs again, same `callId` (its own coding tools: not run again, the model is told) | Runs again, same `callId`                                                                  | Runs again, same `callId`                    | New call, new `callId` (use `retryOf`)                                          |
| Beyond a prompt                        | `withPi(ctx, options, work)`                                                       | `graph`: a graph of your own; `nodes.*` and `langgraph.tools()` for Restate's steps in it  | `nativeOutput`, `effort`                     | `approval`: tool calls that wait for a person                                   |
| Packages (exact versions where pinned) | `@earendil-works/pi-durable`, `pi-ai`, `chord`                                     | `@langchain/core`, `langgraph`, `langgraph-checkpoint`, `@langchain/openai` or `anthropic` | `@anthropic-ai/sdk`                          | `@deepseek-ai/cordis`, `@deepseek-ai/dsh-*@0.2.1-rc.2`, `@earendil-works/pi-ai` |

For each, a tool's error other than a `TerminalError` fails the attempt and Restate
retries it (the framework itself would hand it to the model); a `TerminalError` from a
`@restatedev/agents` tool is the tool's answer. A message is answered once per invocation: a
retried attempt returns the stored answer, and a turn a killed invocation left is closed
(`ended`), never finished: the next turn's model is told how it ended.

There is no OpenCode agent any more (it was one up to 0.3.0): pi with a `workspace` is the
coding agent.

## pi (`@restatedev/agents/pi`): the default

```ts
import * as pi from '@restatedev/agents/pi';
const assistant = pi.agent({ name: 'assistant', system: 'Answer briefly.', tools: [weather] });
```

| Option                      | What                                                                                                              |
| --------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| `model`                     | `provider/model-id`, of any provider pi-ai knows                                                                  |
| `models`                    | A pi-ai model registry, for a provider of your own                                                                |
| `system`, `tools`, `output` | As every framework; `tools` also takes pi-durable's `defineTool`s                                                 |
| `workspace`                 | A directory for pi-durable's coding tools (`read`, `write`, `edit`, `bash`), made if missing. Use a sandbox       |
| `serviceTier`               | OpenAI's service tier: `fast` (its fast mode, priced higher), `flex`, `priority`, …                               |
| `retry`                     | How pi asks the model again after a request failed for a reason that passes (an outage): by default without limit |

- Its storage is pi-durable's, as SQL transactions in the key's database; a prompt is
  submitted once, by the invocation id. pi keeps its own history (and compacts it); each pi
  commit of a prompt's run copies its new entries into the conversation of turns, in the
  same transaction: what `messages` shows.
- **A provider's outage never ends the turn**: pi asks the model again until it answers
  (`retry` sets how often). A request refused for good (a wrong API key) ends it, with a
  terminal error (424) that says what to check.
- A run that a killed invocation left is aborted, never finished.
- `withPi(ctx, options, work)` runs `work({ prompt, conversation, context, harness })` with
  pi-durable's Harness: `prompt(text)` answers once; `(await conversation())` is the
  conversation, with pi-durable's own API (`compact`, `reset`, `entries`, …). It changes what
  the model sees, not `messages`. pi's `compact` summarizes what is older than the latest
  ~20,000 tokens, which it keeps as they are: a shorter conversation stays as it is. Name such handlers otherwise than `compact`, which every
  agent has (tutorial lesson 16):

```ts
handlers: {
  chat: pi.chat(options),
  shorten: async (ctx, instructions?: string) =>
    pi.withPi(ctx, await options(ctx), async ({ conversation, context }) => {
      const root = await conversation();
      await root.compact(instructions || undefined, context);
      await root.waitForIdle(context);
    }),
  startOver: async (ctx, handoff?: string) =>
    pi.withPi(ctx, await options(ctx), async ({ conversation, context }) =>
      (await conversation()).reset(handoff || undefined, context),
    ),
},
```

- **The `workspace`'s files are on the disk, not in the database.** They last as long as the
  disk does (on Modal, until the container is replaced), and a coding tool a crash cut off is
  not run again: the model is told it was interrupted.
- Steering: a steered message is placed after the results of the round of tool calls it
  joins (pi-durable's inbox), not in a round that ends the run.

## LangGraph (`@restatedev/agents/langgraph`)

```ts
import * as langgraph from '@restatedev/agents/langgraph';
import { ChatOpenAI } from '@langchain/openai';

const assistant = langgraph.agent({ name: 'assistant', tools: [weather] });
const precise = langgraph.agent({
  name: 'precise',
  model: new ChatOpenAI({ model: 'gpt-6-sol', maxRetries: 0, maxTokens: 512 }), // a chat model of your own
});
const desk = langgraph.agent({ name: 'desk', graph }); // a graph of your own
```

| Option                      | What                                                                                |
| --------------------------- | ----------------------------------------------------------------------------------- |
| `model`                     | `openai/…` or `anthropic/…`, or any LangChain chat model that calls tools           |
| `system`, `tools`, `output` | As every framework; `tools` also takes LangChain's tools                            |
| `recursionLimit`            | The most steps of a turn (default 10 000): past it, the turn fails for good         |
| `graph`                     | A graph of your own (on `MessagesAnnotation`, or compiled, such as `createAgent`'s) |
| `context`                   | LangGraph's run context for that graph (by default the handler's context)           |

- **The built-in agent** is the usual loop (model node, tools node), on the conversation of
  turns: no checkpoints. The model node stores its reply before it returns, the tools node
  each result as it lands, so a crash during tools resumes them with the same call ids,
  without asking the model again. It takes steered messages before each model request that
  follows tool results.
- **A graph of your own** (`graph`) has its own model and tools (no `model`, `system`,
  `tools`): `chat` runs it with each message as a new `HumanMessage`, and answers with its
  last AI message. Its checkpoints are in the key's database (`SqlCheckpointSaver`, one thread
  per key, each stored before its step runs), and its new messages are copied into the
  conversation after each step. `interrupt()` waits for the signal `interrupt` (in
  `pending`; `signal` resolves it, and the run resumes with its value). Its state is its own,
  so `window`, `budget` and summaries don't reach it, and it takes no steered messages.
- **A graph is durable a step at a time:** a crash runs the step it cut off again. For side
  effects that must happen once, use Restate's: `nodes.waitForSignal`, `nodes.workflow`,
  `nodes.call`, `nodes.send`, `nodes.subagent` as nodes, or `langgraph.tools([...])` for
  `tool()`s and Restate's tools in a `ToolNode` or `createAgent`.
- LangGraph's own errors that a retry would meet again (an invalid state update) end the
  turn, as a `TerminalError` does.
- A chat model of your own: consider `maxRetries: 0`, so that a failed request fails the
  attempt, and Restate retries it, resuming from the database.

## Claude (`@restatedev/agents/claude`)

```ts
import * as claude from '@restatedev/agents/claude';
const assistant = claude.agent({ name: 'assistant', system: 'Answer briefly.', tools: [weather], effort: 'high' });
```

| Option                      | What                                                                                             |
| --------------------------- | ------------------------------------------------------------------------------------------------ |
| `model`                     | `anthropic/model-id` only (`ANTHROPIC_API_KEY`)                                                  |
| `system`, `tools`, `output` | As every framework; `tools` also takes the SDK's runnable tools (`betaZodTool`)                  |
| `nativeOutput`              | Whether `output` is asked for with the API's structured outputs (default: if the model has them) |
| `client`                    | An Anthropic client of your own (a base URL, a proxy)                                            |
| `maxTokens`                 | The most tokens per reply (default 16000): a reply cut off there fails the message (terminal)    |
| `effort`                    | `low`, `medium`, `high`, `xhigh` or `max` (default: the model's)                                 |

- The lightest: the Anthropic SDK's tool runner, on the conversation of turns, stored as the
  API's own messages in the key's database. Each reply is stored before its tools run, and
  their results before the next request; steered messages join that request.
- Claude Code's own tools, if you want them, come as the SDK's agent toolset
  (`@anthropic-ai/sdk/tools/agent-toolset/node`).

## DeepSeek Harness (`@restatedev/agents/deepseek`)

```ts
import * as deepseek from '@restatedev/agents/deepseek';
const assistant = deepseek.agent({ name: 'assistant', tools: [weather] }); // deepseek/deepseek-flash, DEEPSEEK_API_KEY
const onGpt = deepseek.agent({ name: 'on-gpt', model: 'openai/gpt-6-sol' }); // through pi-ai, OPENAI_API_KEY
const bank = deepseek.agent({ name: 'bank', tools: [transfer, audit], approval: ['transfer'] });
```

| Option                      | What                                                                                                   |
| --------------------------- | ------------------------------------------------------------------------------------------------------ |
| `model`                     | `deepseek/…` (to DeepSeek), or any model pi-ai knows, through the harness's pi-ai adapter              |
| `system`, `tools`, `output` | As every framework; `tools` also takes the harness's `defineTool`s                                     |
| `approval`                  | The tool calls that wait for a person's approval before they run: tool names, or `({ name, args }) =>` |
| `compaction`                | When the model's input is condensed (by default at 0.8 of the model's context window)                  |

- The session is event-sourced, one row per event; the harness flushes before each model
  request, tool body and step.
- **Approvals:** such a call waits for the signal `approval` (`deepseek.APPROVAL`), as a
  `signal()` tool waits: `pending` lists it with the tool and its arguments, and `signal`
  answers it (`approved`, `yes`, `true`… approve; anything else denies, and the tool never
  runs). The person is asked once, even if a crash makes the model call it again.
- **Pinned:** its packages are release candidates (0.2.1-rc.2) that require each other's
  exact versions.
- A tool call stored without a result gets an error result saying its outcome is unknown,
  and the model is told to retry only idempotent operations: see `retryOf` in
  [restate-agents.md](restate-agents.md).
- Steering: it hears of a message sent while a tool runs once that tool's result is stored,
  and places it at the step after the next model request, in the same turn.
