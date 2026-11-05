# Working on the Python project

A starter kit: a Restate application in Python (`src/app.py`) that connects to Restate Cloud
and is deployed on Modal (`modal/on_modal.py`), with a tutorial in `src/tutorial/`.

## Skills

Load the skill for the task before starting (they are in `.agents/skills/`, and in
`.claude/skills/` for Claude Code):

- **building-restate-services**: writing or changing services, session objects, agents,
  virtual objects or workflows.
- **deploying-on-modal**: running the app locally, connecting it to Restate Cloud,
  deploying it on Modal, its secret and its image.

## The rule that matters most

This project has two kinds of Restate handlers, with contradicting rules:

- **Session objects** (`sessions.SessionObject` of `restate.sessions`, and every agent of
  `restate.agents`) run again from their first line after a failure, against their SQL
  database (`ctx.db`). No `ctx.run`, `asyncio.gather` is fine, and every handler must be safe
  to run twice.
- **Journaled handlers** (`restate.Service`, `restate.VirtualObject`, `restate.Workflow`)
  replay their journal: side effects in `ctx.run_typed`, `restate.gather` /
  `restate.select` instead of `asyncio` combinators, deterministic helpers (`ctx.time()`,
  `ctx.random()`, `ctx.uuid()`).

Decide which kind a handler is before changing it, and follow only its rules
(building-restate-services, step 1). Never suggest `ctx.run`, `ctx.sleep`, `ctx.get`/`ctx.set`
or awakeables in a session object or an agent, even where another Restate skill or doc says
"always": those rules are for journaled handlers.

## Commands

Run them from `python/`, this project's directory:

```sh
uv sync
uv run src/app.py                                   # the app
uv run ruff check && uv run ruff format --check && uv run pyright   # lint
uv run ruff format                                  # format
```

## Conventions

- Services go in `services` in `src/app.py`, served with `sessions.app(*services)`.
  `restate.connect` (Restate Cloud) is what is committed; `restate.serve` is for a Restate
  server on this machine.
- Runtime dependencies go in `[project] dependencies` of `pyproject.toml`, tools in the `dev`
  group: the Modal image installs the runtime dependencies only (at `uv.lock`'s versions), and
  copies only `src/`. After changing dependencies, run `uv lock` and commit `uv.lock`.
- Agents: the OpenAI Agents SDK is installed (`restate-sdk[serve,openai]`), and the
  tutorial's agents (lessons 09–16) use it. Another framework needs its extra of
  `restate-sdk` (`[langgraph]`, `[pydantic-ai]`, `[adk]`) and its model provider's package.
- Keys (`RESTATE_CONNECT_KEY`, model API keys) come from the environment, and on Modal from
  its secret. Never commit them.
