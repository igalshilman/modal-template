# Working on the Python project

A starter kit: a Restate application in Python (`app/__main__.py`: notes, and an assistant
that keeps them) that connects to Restate Cloud and is deployed on Modal (`modal/on_modal.py`,
or `modal/on_modal_push.py`, where Restate Cloud calls it instead).
Beside it, for this machine only: a tutorial to read and copy from (`tutorial/`), and
complete examples, each ending with an ASGI app (`examples/`).

## Skills

Load the skill for the task before starting (they are in `.agents/skills/`, and in
`.claude/skills/` for Claude Code):

- **building-restate-services**: writing or changing services, session objects, agents,
  virtual objects or workflows.
- **deploying-on-modal**: running the app locally, connecting it to Restate Cloud,
  deploying it on Modal (connected, or called by Restate Cloud), its secret and its image.

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
uv run app                                          # the app, on port 9080
uv run python -m restate serve examples.chat:app    # an example, on port 9080
uv run python -m restate.agents chat assistant/alice   # chat with an agent from the terminal
uv run ruff check && uv run ruff format --check && uv run pyright   # lint
uv run ruff format                                  # format
```

## Conventions

- Services go in `app = restate.app([...])` in `app/__main__.py`, the ASGI app. An agent
  brings along what it needs (the `signals` object), served once. The file ends with `restate.serve(app)`; Restate Cloud and Modal connect the same
  `app` with `python -m restate connect app.__main__:app --name notes-python-v1`, and
  `modal/on_modal_push.py` serves it on Modal with `python -m restate serve app.__main__:app`,
  for Restate Cloud to call.
- An example is a module of `examples/` that ends with `app = restate.app([...])`. Serve it with
  `python -m restate serve` (above), or connect it to Restate Cloud with
  `python -m restate connect examples.<name>:app --name <name>-python-v1`. A lesson of `tutorial/` is only read and copied:
  nothing imports it.
- Dependencies, in `pyproject.toml`: what `app/` imports in `[project] dependencies`, what
  only the examples need in the `examples` group, tools in the `dev` group. The Modal image
  installs `[project] dependencies` only (at `uv.lock`'s versions), and copies only `app/`.
  After changing dependencies, run `uv lock` and commit `uv.lock`.
- Agents: the OpenAI Agents SDK is installed (`restate-sdk[serve,openai]`), and the app's
  assistant and the tutorial's agents (lessons 09–16) use it; LangGraph, LangChain (for
  `create_agent`) and `langchain-openai` are in the `examples` group. Another framework in `app/` needs its extra
  of `restate-sdk` (`[langgraph]`, `[pydantic-ai]`, `[adk]`) and its model provider's package
  in `[project] dependencies`.
- Keys (`RESTATE_CONNECT_KEY`, model API keys) come from the environment, and on Modal from
  its secret. Never commit them.
