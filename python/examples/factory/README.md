# A software factory

A new issue in Linear starts it, through a webhook. Agents on two frameworks
take it from there:

1. A triage agent (OpenAI Agents SDK) decides whether the issue is ready to
   build, and leads the work.
2. It asks the planner (OpenAI Agents SDK) for a plan. The plan comes back
   structured: a summary, and parts that can be built at once.
3. Triage makes a Linear sub-issue for each part, and hands every part to a
   coder (Pydantic AI, on Claude) of its own, all at once. Each coder works on
   a git branch of its own, and opens a pull request of it on GitHub.
4. As each coder answers with its pull request, triage has a reviewer (OpenAI
   Agents SDK) review it, which posts its review on the pull request. Triage
   hands the changes it asks for back to the coder, and has it reviewed again,
   until it approves.
5. With every pull request approved, triage marks the issue Done, and leaves
   the merging to people.

People can also talk to a coder on its pull request: GitHub's webhook takes
their comments and reviews, and failed CI runs, to the coder of that pull
request, which answers there and pushes. Triage and the coders move their issues
along the team's workflow, and comment on them, through Linear's MCP server.

```
  Linear ── webhook: a new issue ──▶ linear/webhook ── send ──▶ triage/ENG-1
     ▲                                                     │  (OpenAI Agents SDK)
     │ issues, sub-issues, comments (Linear's MCP server)  │
     └─────────────────────────────────────────────────────┤
                                                           ├── call ─────▶ planner/ENG-1 plan: a Plan
                                                           ├── subagent ─▶ coder/ENG-1.parser   (Pydantic AI)
                                                           ├── subagent ─▶ coder/ENG-1.history
                                                           └── subagent ─▶ reviewer/ENG-1.parser, …
  GitHub ── webhook: comments, reviews, failed CI ──▶ github/webhook ── send ──▶ coder/ENG-1.parser
     ▲
     └── branches eng-1-parser, eng-1-history: pushed by the coders, PRs into main, reviews as comments
```

Each agent is a session object with its conversation in its own SQL database,
keyed by its task (`coder/ENG-1.parser`). A crash resumes it where it was, and
the parent waits for its answers without holding a process. Tasks of different
names run at once, so the coders work side by side. Each part has one task of
each kind, `coder/ENG-1.parser` and `reviewer/ENG-1.parser`, which triage hands
each round to: the coder remembers its work, and the reviewer its last review,
so it reads only what changed since. The factory stops with the pull requests
approved and open, for people to merge.

A pull request that the reviewer has not approved after three reviews leaves its
sub-issue, and the issue, **In Review**. Not every issue goes the whole way:
triage leaves an unclear issue in **Backlog**, with a comment asking what it needs
to know, and moves one that is nothing to build to **Canceled**.

## The files

| File                                 | What                                                                                                   |
| ------------------------------------ | ------------------------------------------------------------------------------------------------------ |
| [`factory.py`](factory.py)           | The agents, each with its tools and handlers: triage, the planner, a coder, a reviewer; the webhooks   |
| [`tools.py`](tools.py)               | The agents' tools: Linear's (signed), GitHub's pull requests, a coder's clone, a reviewer's diff        |
| [`env.py`](env.py)                   | The environment: the keys, Linear's and GitHub's MCP servers, the project's repository                 |
| [`answers.py`](answers.py)           | The planner's structured answer, the `Plan`                                                            |
| [`prompts.py`](prompts.py)           | The agents' system prompts: triage's, the planner's, a coder's, the reviewer's                         |
| [`linear.py`](linear.py)             | Linear's webhook: the issue an event is for                                                            |
| [`github.py`](github.py)             | GitHub's webhook: the coder an event on a pull request is for, and what of the event it reads          |
| [`mcp_client.py`](mcp_client.py)     | A client of an MCP server, which hands its tools to any agent, asked for when first needed             |
| [`signatures.py`](signatures.py)     | The agents' signatures on what they write, and how the factory tells their comments from people's      |
| [`workspace.py`](workspace.py)       | The coders' clones of the project, each on its own branch; a first commit for an empty project         |

## What it shows

- **A webhook into agents.** `webhook()` of `restate.agents` makes the `linear` service.
  Linear posts to it at Restate's ingress, and it delivers each new issue, and each comment
  on one, to the triage agent keyed by the issue, as a message that says where it comes
  from (`<webhook name="linear" delivery="…">`). A delivery Linear sends again has the same
  `linear-delivery` header, the message's idempotency key, so it reaches the same message
  rather than a second one. With a secret, a webhook that Linear did not sign is refused
  (401). The `github` webhook works the same way for the coders, each event going to the
  coder of its pull request, with only what it needs of the event (`message`).
- **A structured answer from an agent.** The planner is an agent with a handler of its own,
  `plan`, that takes an `Issue` and returns a `Plan`. It asks the model once, with
  `openai.prompt(ctx, …, output=Plan)`, in the planner's conversation for the issue
  (`planner/ENG-1`), and gets a `Plan` back, checked. A retry gets the same plan without
  asking the model again. Triage calls it as a tool (`call(plan, key=…)`), and gets the plan
  as JSON.
- **Agents on two frameworks, in one conversation.** Triage and the reviewer run on the
  OpenAI Agents SDK, the coders on Pydantic AI. Triage takes a coder's pull request to the
  reviewer, and the review back to the coder, round by round, each in the same task every
  time. On GitHub, the pull request shows the conversation: each review, and the coder's
  answer to it, point by point.
- **Work divided, at once.** The parent's subagent calls in one step run at the same time,
  each a coder with a conversation of its own, and the parent waits for them all, holding no
  process.
- **Tools of your own for a coding agent.** The coders work in a clone of the project with
  three tools (`bash`, `read_file`, `write_file`), confined to the clone. Their commands
  don't see the factory's other keys.
- **MCP tools in any agent.** `McpClient(url).tools()` turns an MCP server's tools into
  `restate.agents` tools, which both frameworks take. A tool call is stored once it is done,
  so a crash makes again only one that had not finished (moving an issue twice is harmless;
  a comment may show twice).
- **Status in Linear.** Triage and each coder move their own issue, and say what they are
  about to do as they start it. They all write as one Linear user, so each comment, each
  sub-issue's description, each commit (its author) and each comment on a pull request opens
  with who wrote it ("🧭 Triage", "🛠️ Coder · parser"). That signature is also how the
  factory drops its own comments when they come back as webhooks.

## Run it, on Linear and GitHub

The agents move and comment on real issues, make real sub-issues, and open real pull
requests: use a team and a repository of their own, for the factory. The coders run real
commands on this machine, in `WORKSPACE` (`/tmp/restate-factory` by default): run it in a
sandbox, such as a container or a VM.

1. **A key the factory acts with**, `LINEAR_API_KEY`: a personal API key (Settings,
   Security & access), or the token of an OAuth app installed with `actor=app`, so that the
   factory acts in Linear as itself ([Linear's docs](https://linear.app/developers/oauth-actor-authorization)).
   It needs to write issues and comments. The factory sends it to Linear's MCP server
   (`https://mcp.linear.app/mcp`) as a bearer token.
2. **Restate, reachable by Linear and GitHub**: their webhooks post to Restate's ingress,
   with no Restate API key. With a Restate server on your machine, a tunnel to its ingress,
   such as `cloudflared tunnel --url http://localhost:8080`. Its URL is public and opens all
   of the ingress, the agents too: for more than a demo, use a tunnel that opens only
   `/linear/webhook` and `/github/webhook`.
3. **Linear's webhook**: in Linear's settings, under API, a webhook to
   `https://<the tunnel>/linear/webhook`, for Issues and Comments, on the factory's team only.
   Its signing secret is `LINEAR_WEBHOOK_SECRET`.
4. **The team's states**: the agents move issues to Todo, In Progress, In Review, Done and
   Canceled. Add any the team doesn't have, under the team's workflow settings.
5. **A repository, and a token for it**: `GITHUB_REPO` (`owner/name`; if it is empty, the
   factory pushes a README to `main` first), and a fine-grained personal access token for it
   alone, with read and write access to its contents and pull requests: `GITHUB_TOKEN`. The
   coders push their branches with it, and open pull requests through GitHub's MCP server
   (`https://api.githubcopilot.com/mcp/`), where the reviewers post their reviews and the
   coders their answers, as comments (an author can't approve their own pull request on
   GitHub, so the factory's approval shows in Linear).
6. **GitHub's webhook**: in the repository's settings, under Webhooks, a webhook to
   `https://<the tunnel>/github/webhook`, with content type `application/json` and a secret
   of yours (`openssl rand -hex 32`): `GITHUB_WEBHOOK_SECRET`. Its events: Issue comments,
   Pull request reviews, Pull request review comments, and Workflow runs (for CI).

Then, from `python/`, each in a terminal of its own:

```sh
LINEAR_API_KEY=lin_api_… LINEAR_WEBHOOK_SECRET=lin_wh_… \
GITHUB_REPO=<owner>/<repo> GITHUB_TOKEN=github_pat_… GITHUB_WEBHOOK_SECRET=… \
OPENAI_API_KEY=… ANTHROPIC_API_KEY=… \
  uv run python -m restate serve examples.factory:app
npx @restatedev/restate-server@1.8.1                                    # Restate, its UI at localhost:9070
npx @restatedev/restate@1.8.1 deployments register http://localhost:9080
```

The coders run on Claude (`anthropic/claude-sonnet-5-5`, with `ANTHROPIC_API_KEY`); set
`CODER_MODEL=openai/gpt-6-sol` to run them on OpenAI's instead. `RESTATE_AGENT_MODEL` sets
the model of triage, the planner and the reviewer.

Create an issue on the team, in Linear: it moves as the agents work, and its sub-issues
appear, each moving on its own. Comment on the issue ("How is it going?"): triage answers
there. Comment on a pull request, or review it, on GitHub: its coder answers there, and
pushes what you asked for. Follow the agents in Restate, by the issue (`ENG-1`) and the
parts triage names:

```sh
curl localhost:8080/triage/ENG-1/status            # what triage is doing now
curl localhost:8080/triage/ENG-1/messages          # triage's conversation, with its tool calls
curl localhost:8080/planner/ENG-1/messages         # the planner's: the issue, and the plan
curl localhost:8080/coder/ENG-1.parser/messages    # a coder's, of a part triage named "parser"
curl localhost:8080/reviewer/ENG-1.parser/messages # its reviewer's: the reviews, round by round
uv run python -m restate.agents chat triage/ENG-1  # or follow triage, and talk to it, from a terminal
```

Restate's UI, at http://localhost:9070, shows the same work as calls: triage's, and the
planner's, coders' and reviewer's under it.

`LINEAR_MCP_URL`, `GITHUB_MCP_URL` and `GITHUB_REMOTE` point the factory at other servers
and another remote, such as GitHub Enterprise's.

## Run it, on Modal

The Modal image has only `app/` and its dependencies. To deploy the factory, add it to
`app/__main__.py`'s `restate.app([...])` (its services are `examples.factory.factory`'s),
copy `examples/factory/` into the image, move its dependencies (the `examples` group's
`pydantic-ai`, `mcp`) into `[project] dependencies`, and add `git` to the image
(`.apt_install("git")` in `modal/on_modal.py`). Its keys go in the Modal secret, beside
`RESTATE_CONNECT_KEY`. Linear's and GitHub's webhooks then go to your Restate Cloud
environment's ingress. The coders' clones are on the container's disk, not in Restate: a new
container clones the project again, and a coder's branch from what it pushed.
