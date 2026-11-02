# The frameworks of `@restatedev/agents`

Every framework's agent has the same shape: `agent({ name, model, system, tools, output, ... })`,
with the handler `chat` and the views `messages`, `status`, `stop`, `steer`, `clear`, `sync`,
`notifications`, `watch`, `pending`, `signal`. For a session object of your own, each has `<framework>.chat(options)`
(the handler), `<framework>.messages()` (the view) and `<framework>.prompt(ctx, text,
options)`. `options` may be a function of the context. The general rules are in
[restate-agents.md](restate-agents.md); this page is what differs. The full READMEs:
`node_modules/@restatedev/agents/src/<framework>/README.md`.

## At a glance

|                                        | pi                                                                                 | OpenCode                                                    | LangGraph                                                                                  | Claude                                  | DeepSeek Harness                                                                |
| -------------------------------------- | ---------------------------------------------------------------------------------- | ----------------------------------------------------------- | ------------------------------------------------------------------------------------------ | --------------------------------------- | ------------------------------------------------------------------------------- |
| Models                                 | Any pi-ai provider                                                                 | Any provider OpenCode serves                                | OpenAI's, Anthropic's, or a LangChain chat model                                           | Anthropic's only                        | DeepSeek's, or any pi-ai provider                                               |
| Default model                          | `openai/gpt-6-sol`                                                                 | `openai/gpt-6-sol`                                          | `openai/gpt-6-sol`                                                                         | `anthropic/claude-sonnet-5-5`           | `deepseek/deepseek-flash`                                                       |
| Coding tools                           | `workspace` (read, write, edit, bash)                                              | `workspace` (read, edit, bash, glob, grep, …)               | Your tools                                                                                 | Your tools (or the SDK's agent toolset) | Your tools                                                                      |
| Tool call cut off by a crash           | Runs again, same `callId` (its own coding tools: not run again, the model is told) | New call, new `callId` (use `retryOf`)                      | Runs again, same `callId`                                                                  | Runs again, same `callId`               | New call, new `callId` (use `retryOf`)                                          |
| Steering (`steer`) mid-turn            | Yes                                                                                | Yes                                                         | No: answered next                                                                          | No: answered next                       | Yes                                                                             |
| Beyond a prompt                        | `withPi(ctx, options, work)`                                                       | `withOpenCode(ctx, options, work)`                          | `new SqlCheckpointSaver(db)` for a graph of your own                                       |                                         |                                                                                 |
| Packages (exact versions where pinned) | `@earendil-works/pi-durable`, `pi-ai`, `chord`                                     | `@opencode/{core,plugin,sdk,server}@2.0.32`, `effect@4.0.1` | `@langchain/core`, `langgraph`, `langgraph-checkpoint`, `@langchain/openai` or `anthropic` | `@anthropic-ai/sdk`                     | `@deepseek-ai/cordis`, `@deepseek-ai/dsh-*@0.2.1-rc.2`, `@earendil-works/pi-ai` |

For each, a tool's error other than a `TerminalError` fails the attempt and Restate
retries it (the framework itself would hand it to the model); a `TerminalError` from a `@restatedev/agents` tool is the
tool's answer. A message is answered once per invocation: a retried attempt returns the
stored answer, and a message a crash interrupted is finished before the next one starts.

## pi (`@restatedev/agents/pi`): the default

```ts
import * as pi from '@restatedev/agents/pi';
const assistant = pi.agent({ name: 'assistant', system: 'Answer briefly.', tools: [weather] });
```

| Option                      | What                                                                                                        |
| --------------------------- | ----------------------------------------------------------------------------------------------------------- |
| `model`                     | `provider/model-id`, of any provider pi-ai knows                                                            |
| `models`                    | A pi-ai model registry, for a provider of your own                                                          |
| `system`, `tools`, `output` | As every framework; `tools` also takes pi-durable's `defineTool`s                                           |
| `workspace`                 | A directory for pi-durable's coding tools (`read`, `write`, `edit`, `bash`), made if missing. Use a sandbox |
| `serviceTier`               | OpenAI's service tier: `fast` (its fast mode, priced higher), `flex`, `priority`, …                         |

- Its storage is pi-durable's, as SQL transactions in the key's database; a prompt is
  submitted once, by the invocation id.
- `withPi(ctx, options, work)` runs `work({ prompt, conversation, context })` with pi-durable's
  Harness: `prompt(text)` answers once; `(await conversation())` is the conversation, with
  pi-durable's own API (`compact`, `reset`, `entries`, …):

```ts
handlers: {
  chat: pi.chat(options),
  compact: async (ctx, instructions?: string) =>
    pi.withPi(ctx, await options(ctx), async ({ conversation, context }) => {
      const root = await conversation();
      await root.compact(instructions || undefined, context);
      await root.waitForIdle(context);
    }),
  reset: async (ctx, handoff?: string) =>
    pi.withPi(ctx, await options(ctx), async ({ conversation, context }) =>
      (await conversation()).reset(handoff || undefined, context),
    ),
},
```

- **The `workspace`'s files are on the disk, not in the database.** They last as long as the
  disk does (on Modal, until the container is replaced), and a coding tool a crash cut off is
  not run again: the model is told it was interrupted.

## OpenCode (`@restatedev/agents/opencode`): a coding agent

```ts
import * as opencode from '@restatedev/agents/opencode';
const coder = opencode.agent({ name: 'coder', workspace: (ctx) => `/work/${ctx.key}` });
```

| Option                      | What                                                                                                                                          |
| --------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| `model`                     | `provider/model-id`, of any provider OpenCode serves                                                                                          |
| `system`, `tools`, `output` | As every framework; `tools` also takes OpenCode tools of your own                                                                             |
| `workspace`                 | A directory, or a function of the context giving one, where OpenCode's own tools work. Without one, the agent has only `tools`. Use a sandbox |
| `plugins`                   | OpenCode plugins (`@opencode/plugin`): permissions, hooks, such as one that denies edits outside `src/`                                       |

- OpenCode runs embedded, in the handler's process, on a database of its own in the same
  key (beside `ctx.db`). With `opencode.messages()` in your object, `clear` empties it too.
- `withOpenCode(ctx, options, work)` runs `work({ prompt, host })`: `prompt(text)` answers once
  (several prompts make one session), `host` is OpenCode's client.
- **Pinned:** exactly OpenCode 2.0.32 and Effect 4.0.1, since its tables are stored as that
  version lays them out. Node 24.
- **Native build:** it brings `tree-sitter-powershell`, which compiles from source on Linux:
  the image needs `make` and `g++` (see the deploying-on-modal skill).
- **Cost:** some hundreds of SQL statements per prompt; booting takes about 100 ms per
  attempt, after a one-time import of about 2 s per process.
- **A prompt sent while a turn runs waits for it** (it is answered in that turn's run).

## LangGraph (`@restatedev/agents/langgraph`)

```ts
import * as langgraph from '@restatedev/agents/langgraph';
import { ChatOpenAI } from '@langchain/openai';

const assistant = langgraph.agent({ name: 'assistant', tools: [weather] });
const precise = langgraph.agent({
  name: 'precise',
  model: new ChatOpenAI({ model: 'gpt-6-sol', maxRetries: 0, maxTokens: 512 }), // a chat model of your own
});
```

| Option                      | What                                                                      |
| --------------------------- | ------------------------------------------------------------------------- |
| `model`                     | `openai/…` or `anthropic/…`, or any LangChain chat model that calls tools |
| `system`, `tools`, `output` | As every framework; `tools` also takes LangChain's tools                  |

- The graph is the usual loop (model node, tools node). Each step is stored before the next
  (`durability: 'sync'`), so a crash during tools resumes them with the same call ids,
  without asking the model again.
- The agent keeps its thread's latest checkpoint only. For a graph of your own,
  `new SqlCheckpointSaver(db)` keeps them all, for LangGraph's history.
- A chat model of your own: consider `maxRetries: 0`, so that a failed request fails the
  attempt, and Restate retries it, resuming from the database (the example in the package
  does this).

## Claude (`@restatedev/agents/claude`)

```ts
import * as claude from '@restatedev/agents/claude';
const assistant = claude.agent({ name: 'assistant', system: 'Answer briefly.', tools: [weather], effort: 'high' });
```

| Option                      | What                                                                                          |
| --------------------------- | --------------------------------------------------------------------------------------------- |
| `model`                     | `anthropic/model-id` only (`ANTHROPIC_API_KEY`)                                               |
| `system`, `tools`, `output` | As every framework; `tools` also takes the SDK's runnable tools (`betaZodTool`)               |
| `client`                    | An Anthropic client of your own (a base URL, a proxy)                                         |
| `maxTokens`                 | The most tokens per reply (default 16000): a reply cut off there fails the message (terminal) |
| `effort`                    | `low`, `medium`, `high`, `xhigh` or `max` (default: the model's)                              |

- The lightest: the Anthropic SDK's tool runner, with the conversation stored as the API's
  own messages in the key's database. Each reply is stored before its tools run.
- Claude Code's own tools, if you want them, come as the SDK's agent toolset
  (`@anthropic-ai/sdk/tools/agent-toolset/node`).

## DeepSeek Harness (`@restatedev/agents/deepseek`)

```ts
import * as deepseek from '@restatedev/agents/deepseek';
const assistant = deepseek.agent({ name: 'assistant', tools: [weather] }); // deepseek/deepseek-flash, DEEPSEEK_API_KEY
const onGpt = deepseek.agent({ name: 'on-gpt', model: 'openai/gpt-6-sol' }); // through pi-ai, OPENAI_API_KEY
```

| Option                      | What                                                                                      |
| --------------------------- | ----------------------------------------------------------------------------------------- |
| `model`                     | `deepseek/…` (to DeepSeek), or any model pi-ai knows, through the harness's pi-ai adapter |
| `system`, `tools`, `output` | As every framework; `tools` also takes the harness's `defineTool`s                        |

- The session is event-sourced, one row per event; the harness flushes before each model
  request, tool body and step.
- **Pinned:** its packages are release candidates (0.2.1-rc.2) that require each other's
  exact versions.
- A tool call stored without a result gets an error result saying its outcome is unknown,
  and the model is told to retry only idempotent operations: see `retryOf` in
  [restate-agents.md](restate-agents.md).
