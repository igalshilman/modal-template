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
curl localhost:8080/assistant/alice/steer -H 'idempotency-key: s-1' -d 'Skip Friday'   # join the turn being answered
```

- One key answers **one message at a time**, in the order they came; a message sent to
  `chat` while another is answered waits. One sent to `steer` joins the turn being answered
  ("Steering", below).
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
const { answering, waiting, steering } = await alice.status();
const { turn } = await alice.steer('Skip Friday', clients.rpc.opts({ idempotencyKey: 's-1' }));
```

`agent<H>(name)` types a session object of your own, with its handlers `H`.

## The conversation, and following it

- `messages` is the conversation a page at a time (the latest 50 by default), with the tool
  calls and their outputs: `{ messages, more, cursor }`. `{ limit, before }` pages back;
  `{ cursor }` gives what is new or changed since a cursor. A message's `id` is its position,
  and never changes; a message that grew (a tool call that got its output) comes again with
  its `id`. `{ view: "summary" }` gives each turn's message(s) and answer alone, under the
  same ids. A summarized or compacted conversation still shows every turn as it was said.
- `status` is what it's doing: `{ answering: { invocationId, since } | null, waiting: [...],
  steering: [...] }` (`steering`: the steered messages the turn holds and hasn't taken yet).
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

## Turns, stop, clear

| View    | What it does                                                                                                                                                                                                                                        | Answers                                |
| ------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------- |
| `stop`  | Cancels the message being answered (Restate's cancellation): the turn ends, cut-off tool calls are recorded as cancelled, and the calls its tools made (a wait, a subagent's task, a workflow) are cancelled with it. The next waiting message runs | `{ stopped: <invocation id> \| null }` |
| `clear` | Stops the turn, then forgets the conversation: the key's database, and its companion's waits and kept signals                                                                                                                                       | `{ stopped: … }`                       |

To change course outright, `stop` the turn, then send the message that replaces it: it is
answered once the stopped turn ended, after any messages already waiting. A message sent
before `clear` is answered, then forgotten too.

### Steering

A message sent to `chat` while the agent works waits in Restate's queue for the key: its
own turn starts once the turn before it ended. A message sent to the **`steer`** view adds
to the turn being answered instead ("use Celsius", "skip Friday"):

- **The turn takes it at its next step**: once the model's reply has a result for each of
  its tool calls, before the model's next request, which has it after those results. The
  turn's answer covers it, and `messages` shows it inside that turn.
- **Otherwise it is answered as a turn of its own**, right after the turn, before the
  messages sent after it: when it comes too late for a step (the model is writing its final
  answer), with no turn being answered (it then starts one, as `chat/send` would), past the
  16 a turn takes, or to a turn that takes none (a `background` agent, a LangGraph graph of
  your own).
- **Either way it is answered once.** Send it with an idempotency key, so that a request
  sent again is the same message. `steer` answers `{ id, turn }`: the message's id, and the
  turn that holds it, or `turn: null`. A `turn` is no promise: if that turn writes its answer
  before another step, the message is answered right after it. A message the turn took shares its fate: stopped,
  failed or refused with it, it is not answered again; one it hadn't taken yet is answered
  after it.
- **A step comes only once all tool calls returned**: a tool that waits a day for an
  approval holds the message until then (`stop` to change course sooner).
- Where each framework takes it: agents-frameworks.md. An agent whose `chat` is a handler
  of your own (not `<framework>.chat()` or `chatHandler`) refuses `steer` (400).

### Turns, precisely

- **A turn is the agent answering one message: its `chat` invocation, from its start to its
  end**, with however many model calls and tool calls it takes. A turn is the invocation, not
  one run of it. Turns of one key run one at a time, in the order their messages came. A
  message sent with an idempotency key is one invocation, so one turn, however often it is
  sent.
- **The companion** (`<agent>.prebuilt.restate`, keyed as the agent) records each turn's
  start and its close: `status.answering` is the turn from one to the other, or `null`.
- **Its life:** the turn starts (`status` says it answers), then each tool call publishes as
  it starts and as it ends, then the turn writes its last change, **closes, and only then
  returns the answer**. So `status` is idle by the time the caller has the answer.
- **An attempt is not a turn.** A crash, a lost connection or a suspension ends an attempt;
  the next attempt runs the handler from its first line and continues the same turn from the
  database:
  - the prompt by its id (the invocation's id; later prompts of the same invocation
    `<id>:2`, `<id>:3`), found stored, answered or not, rather than asked again;
  - tool calls by their idempotency keys, `<invocation>:<call id>`. Restate's own tools
    (`call`, `send`, `signal`, `subagent`, `workflow`) make their call once however often
    the tool call runs: on a framework that gives a cut-off call a new id (the DeepSeek
    Harness), they get the earlier call's id back. Tools of your own need the `retryOf`
    pattern there (restate-agents.md);
  - a tool's wait rejoins the same wait in the companion, by that key.

  `status` keeps answering the turn meanwhile. An attempt that ends while its process lives
  on stops its work, a model request included: that is not a cancellation, the turn goes on.

- **Deliveries** (`webhook()`, `deliver()`) are messages of their own, keyed by the delivery:
  answered after the message being worked on, even a stopped one. A delivery is never dropped.
- **A `background` agent** (a subagent, say) publishes only each turn's end: followers see a
  turn once it ended. It takes no steered messages.
- **A turn in the conversation** is its message, the steered messages it took, the model's
  replies and tool calls with their results, and its answer, stored as it goes. A turn that
  closes otherwise than with an answer gets a closing note as its answer (`Unanswered: …`,
  `Error: …`, `Cancelled: …`, `Ended: …`), and each of its tool calls a result, so the next
  turn's model never sees a call without a result, and knows how it ended.

How a turn can end:

| How                                                  | The caller gets                    | Then                                                                               |
| ---------------------------------------------------- | ---------------------------------- | ---------------------------------------------------------------------------------- |
| **Answered**                                         | The answer                         | Idle; the next message starts                                                      |
| **Refused** (a wrong API key, an unknown model)      | HTTP 424, for good                 | Idle; the next message is answered on its own                                      |
| **Failed for good** (a terminal error)               | That error                         | Idle                                                                               |
| **Stopped** (`stop`, `clear`, or Restate's cancel)   | `CancelledError` (409)             | Idle; its tools' calls are cancelled, their waits forgotten                        |
| **Crashed** (a process died, a retryable error)      | Nothing yet: Restate runs it again | Still answering: the next attempt goes on with it                                  |
| **Killed** (Restate's admin API)                     | Nothing: no code runs              | The companion's watch closes it (`Ended`): idle, its waits dropped; never finished |
| **Out of retries** (100,000 attempts, about 11 days) | The failure                        | Closed by the watch if Restate fails it; a turn Restate pauses stays open          |

- **Stopping is safe to repeat.** `stop` reads the turn to cancel with an idempotency key
  of its own request, so a `stop` that Restate runs again cancels the same turn again (which
  does nothing), never the message that started after it. A cancellation that comes once the
  turn answered changes nothing: the answer stands.
- **The watch.** A turn closes itself only if its code runs to the end. For the turns that
  don't (killed, out of retries), the companion watches each turn it starts, holding no
  process, and closes it at once if it failed: in the companion, and in the conversation
  (the agent's private `settle`), so the next turn's model is told how it ended. A watch lasts
  an hour at most, then a new one takes over while the turn is still answered. The next
  turn's start also closes a turn before it that never closed. A killed turn is never
  finished under another invocation.
- **Not covered: waits started outside `chat`.** A handler of your own that calls a
  framework's `prompt` with a `signal` tool is not a turn: if it is killed, its waits stay in
  `pending` until a `signal` resolves them or `clear` forgets them.

**What a follower sees.** The revision (`notifications`, `watch`, `sync`) increases at a
turn's start, at each tool call's start and end (not for a `background` agent), at a turn's
close (its own, its watch's, or the next turn's start), when a wait starts, is resolved or is
forgotten, and at `clear`. So a follower that reads each new revision sees every turn begin,
its tool calls, its end, and a killed turn go idle.

Source: the library's
[docs/turns.md](https://github.com/restatedev/sdk-sessions/blob/main/packages/agents/docs/turns.md)
(not shipped in the npm package), with the storage in
[docs/conversation.md](https://github.com/restatedev/sdk-sessions/blob/main/packages/agents/docs/conversation.md).

So, for a UI:

| The user types while the agent works…          | Use                 | What happens                                                                        |
| ---------------------------------------------- | ------------------- | ----------------------------------------------------------------------------------- |
| An addition to what it's doing ("skip Friday") | `steer`             | Taken at the turn's next step, and covered by its answer; else answered right after |
| "Forget that, do something else"               | `stop`, then `chat` | The turn ends now; the new message is answered after any already waiting            |
| Another question, for later                    | `chat` (`/send`)    | Queued: answered after the current turn, and any messages already waiting           |

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

1. **Tool logic** without a model: put what a tool's `run` does in a function that takes
   `ctx.db`, call it from a handler of the object too, and test that handler against a
   Restate server on this machine ([session-sql.md](session-sql.md), "Testing SQL").
2. **The agent end to end**, against a Restate server on this machine with a real model key:
   send messages with curl or the client, and read `messages` and `status`.
3. **Through a crash:** kill the app's process while a tool runs (a tool that waits a few
   seconds with a plain `setTimeout` makes it easy; there is no `ctx.sleep`), start it again, and check that the effect happened once and the answer came.

## Deploying

- Each agent's companion must be served with it: `src/app.ts` connects
  `restate.served(services)`, which adds them.
- The model's API key, and any key a tool uses, go in the environment: on Modal, in the
  Modal secret (deploying-on-modal skill).
- A long turn is fine: the app connects out to Restate Cloud, and a turn that waits (a
  `signal`, a subagent) holds no process. A request/response platform (Lambda) is not: a
  suspension restarts the handler.
- Coding agents (`workspace`) run real commands in the container: the container is their
  sandbox, and their files live on its disk, not in Restate.
- With `serve(...)` of `@restatedev/agents` (not used by this repository),
  `RESTATE_SERVE_ONLY=triage,planner` serves only the services it names, each agent with its
  companion, to deploy one program in parts.
