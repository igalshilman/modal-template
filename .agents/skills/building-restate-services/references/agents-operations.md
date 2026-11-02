# Operating agents: calling, following, failing, testing, deploying

Companion to [restate-agents.md](restate-agents.md). The examples use a local Restate
server's ingress (`localhost:8080`). On Restate Cloud, the same requests go to your
environment's ingress (`https://<environment id>.env.<region>:8080`) with
`-H "Authorization: Bearer <ingress API key>"`, or through the client with
`RESTATE_INGRESS_KEY` (the deploying-on-modal skill, "Calling handlers").

## Calling an agent

The request's body is the message (text, or a JSON string); the answer is a JSON string (or
the `output` value).

```sh
curl localhost:8080/assistant/alice/chat -d 'Hi, I am Alice'                     # wait for the answer
curl localhost:8080/assistant/alice/chat/send -d 'Plan my week'                  # don't wait: {"invocationId": "inv_…"}
curl localhost:8080/restate/invocation/inv_…/attach                              # its answer, once there is one
curl localhost:8080/assistant/alice/chat/send -H 'idempotency-key: msg-1' -d 'Plan my week'   # sent again: the same invocation
curl localhost:8080/restate/invocation/assistant/alice/chat/msg-1/attach         # its answer, by the key
```

- One key answers **one message at a time**, in the order they came; a message sent while
  another is answered waits.
- Use `/send` when a turn may take longer than an HTTP request should wait (a tool that
  waits for a person, a coding task).
- A caller that may send a message again (after a timeout) gives it an idempotency key:
  without one, the repeat is a new invocation, and the agent answers it again, tools
  included (delivery is at least once: "Delivery semantics" in
  [session-objects.md](session-objects.md)).

From a Restate handler, through the agent's definition: `await ctx.rpc(assistant,
'alice').chat('Hi')` from a session object, `ctx.objectClient(assistant, 'alice').chat('Hi')`
from a journaled handler.

From other code (a web app, a script), with `@restatedev/restate-sdk-clients` and
`agent(name)` of `@restatedev/agents/client`, which imports nothing of the agent's code, so a
browser bundles it:

```ts
import * as clients from '@restatedev/restate-sdk-clients';
import { agent } from '@restatedev/agents/client';

const restate = clients.connect({ url: 'http://localhost:8080' }); // or clients.connect() with RESTATE_INGRESS_KEY
const alice = restate.objectClient(agent('assistant'), 'alice');

const answer = await alice.chat('Hi, I am Alice');
const { messages } = await alice.messages({ limit: 20 });
const { answering, waiting } = await alice.status();
```

`agent<H>(name)` types a session object of your own, with its handlers `H`.

## The conversation, and following it

- `messages` is the conversation a page at a time (the latest 50 by default), with the tool
  calls and their outputs: `{ messages, more, cursor }`. `{ limit, before }` pages back;
  `{ cursor }` gives what is new or changed since a cursor. A message's `id` never changes;
  a message that grew (a tool call that got its output) comes again with its `id`.
- `status` is what it's doing: `{ answering: { invocationId, since } | null, waiting: [...] }`.
- `sync` waits for the next change (a message or tool call stored, a wait, a turn's start or
  end), up to 50 s by default: `{ revision, cursor, status, messages, more }`. It waits in
  Restate, holding no process. `notifications` and `watch({ revision })` are the revision
  alone and the wait alone.
- **There is no token streaming:** a reply comes whole, as a message.

For a UI, `follow()` is a loop of syncs that survives network failures:

```ts
import { agent, follow, type ChatMessage } from '@restatedev/agents/client';

const stop = new AbortController();
const shown = new Map<number, ChatMessage>();
for await (const change of follow(restate, agent('assistant'), 'alice', { signal: stop.signal })) {
  for (const m of change.messages) shown.set(m.id, m); // keep by id: a message may come again, changed
  render(change.status, [...shown.values()]); // drop ids below change.first: `clear` forgot them
}
```

`asText(message)` is a message as a terminal shows it. A follower can carry on later from
`change.cursor` (`follow(..., { cursor })`).

## Turns, stop, steer, clear

| View    | What it does                                                                                                                                                                                                                                        | Answers                                |
| ------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------- |
| `stop`  | Cancels the message being answered (Restate's cancellation): the turn ends, cut-off tool calls are recorded as cancelled, and the calls its tools made (a wait, a subagent's task, a workflow) are cancelled with it. The next waiting message runs | `{ stopped: <invocation id> \| null }` |
| `steer` | Adds a message to the turn being answered, which takes it after its next tool call (pi, OpenCode, DeepSeek). Not taken by then, or with no turn running, it becomes a message of its own (see below)                                                | `{ invocationId, steered }`            |
| `clear` | Stops the turn, then forgets the conversation: the key's database and what `signals` holds for it, steered messages included                                                                                                                        | `{ stopped: … }`                       |

To interrupt with a new message: `stop`, then send it. Messages already waiting are answered
first. A message sent before `clear` is answered, then forgotten too.

### Turns and steering, precisely

- **A turn is the agent answering one message: one invocation of `chat`**, with however many
  model calls and tool calls it takes. Turns of one key run one at a time, in the order their
  messages came; `status.answering` is the turn in progress. The agent's `signals` object
  records each turn's start and its close.
- **A steer during a turn** is queued for that turn (its id `<turn>:steer:<n>`), and
  `steer` answers `{ invocationId: <the turn's>, steered: true }`. The turn takes the queued
  steers **after each tool call ends**, on the frameworks that steer: pi, OpenCode and the
  DeepSeek Harness. They are taken by id, so a retried attempt neither loses nor repeats one.
- **A steer with no turn running**, or to a turn that has already closed, is sent to `chat`
  as a message of its own: `{ invocationId: <the new one>, steered: false }`.
- **When a turn closes, each steer it didn't take is sent as a message of its own**, queued
  behind messages already waiting (not ahead of them). That covers a turn that ended without
  another tool call, and every steer on Claude and LangGraph, which never take steers.
- **A stopped turn drops the steers it didn't take.** Deliveries (`webhook()`, `deliver()`)
  are never dropped: they are answered after the turn, even a stopped one.
- **A `background` agent** (a subagent, say) reports to its `signals` only when a turn ends,
  so a steer waits for the end, and is then answered as a message of its own.
- **An attempt is not a turn.** A crash or a suspension ends an attempt; the next attempt
  continues the same turn, with the same steers. Only a stop, an answer or a terminal
  failure ends a turn.

So, for a UI:

| The user types while the agent works…               | Use                 | What happens                                                                                   |
| --------------------------------------------------- | ------------------- | ---------------------------------------------------------------------------------------------- |
| "Only Monday, please" (a correction for this turn)  | `steer`             | Taken after the next tool call; if none comes, answered right after the turn                   |
| "Forget that, do something else" (replace the turn) | `stop`, then `chat` | The turn ends now; its untaken steers are dropped; the new message follows any already waiting |
| Another question (for later)                        | `chat` (`/send`)    | Queued: answered after the current turn, and any messages already waiting                      |

## Failures and retries

- **A model provider's refusal** (missing or wrong API key, unknown model) fails the message
  at once with a terminal error, HTTP 424, saying what to check. The next message is answered
  on its own.
- **Any other failure** (a crash, a network error, a tool's non-terminal error) fails the
  attempt, and Restate retries it: 50 ms later, doubling up to 10 s apart, for up to 100,000
  attempts (weeks). Each attempt resumes from the database: answered prompts aren't asked
  again, completed tool calls aren't repeated (a cut-off one is: see "Tools that must not
  run twice" in restate-agents.md). Change the policy with `options: { retryPolicy }`
  on your `sessionObject`.
- An attempt that ends while its process lives on (suspended, abandoned) stops its work, a
  model request included; the next attempt continues the turn.
- **A structured answer** (`output`) that doesn't parse is sent back once; then the message
  fails, terminally.
- A failure that keeps retrying shows in Restate's UI (localhost:9070, or the Cloud UI) and
  through the CLI (`restate search list invocations`, then `--json`): fix the cause (the key,
  the tool), or cancel the invocation.

## Testing agents

The library's scripted test models are not published, so test in layers:

1. **Tool logic** as plain functions: put what a tool's `run` does in a function that takes
   `ctx.db` (or a database from `@restatedev/sessions/internal`, see
   [session-sql.md](session-sql.md)) and test it without a model.
2. **The agent end to end**, against a Restate server on this machine with a real model key:
   send messages with curl or the client, and read `messages` and `status`.
3. **Through a crash:** kill the app's process while a tool runs (a tool that waits a few
   seconds with a plain `setTimeout` makes it easy; there is no `ctx.sleep`), start it again, and check that the effect happened once and the answer came.

## Deploying

- `signals` must be served next to the agents, once (`services` in `src/app.ts`).
- The model's API key, and any key a tool uses, go in the environment: on Modal, in the
  Modal secret (deploying-on-modal skill).
- A long turn is fine: the app connects out to Restate Cloud, and a turn that waits (a
  `signal`, a subagent) holds no process. A request/response platform (Lambda) is not: a
  suspension restarts the handler.
- Coding agents (`workspace`) run real commands in the container: the container is their
  sandbox, and their files live on its disk, not in Restate.
- With `serve(...)` of `@restatedev/agents` (not used by this repository),
  `RESTATE_SERVE_ONLY=triage,planner,signals` serves only the services it names, to deploy
  one program in parts.
