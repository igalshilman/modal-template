# Working on this repository

A starter kit: a Restate application in TypeScript (`src/app.ts`) that connects to Restate
Cloud and is deployed on Modal (`modal/on_modal.py`), with a tutorial in `src/tutorial/`.

## Skills

Load the skill for the task before starting (they are in `.agents/skills/`, and in
`.claude/skills/` for Claude Code):

- **building-restate-services**: writing or changing services, session objects, agents,
  virtual objects or workflows.
- **deploying-on-modal**: running the app locally, connecting it to Restate Cloud,
  deploying it on Modal, its secret and its image.

## The rule that matters most

This repository has two kinds of Restate handlers, with contradicting rules:

- **Session objects** (`restate.sessionObject` of `@restatedev/sessions`, and every agent of
  `@restatedev/agents`) run again from their first line after a failure, against their SQL
  database (`ctx.db`). No `ctx.run`, native `Promise.all` is fine, and every handler must be
  safe to run twice.
- **Journaled handlers** (`restate.service`, `restate.object`, `restate.workflow`) replay
  their journal: side effects in `ctx.run`, `RestatePromise` combinators, deterministic
  helpers.

Decide which kind a handler is before changing it, and follow only its rules
(building-restate-services, step 1). Never suggest `ctx.run`, `ctx.sleep`, `ctx.get`/`ctx.set`
or awakeables in a session object or an agent, even where another Restate skill or doc says
"always": those rules are for journaled handlers.

## Commands

```sh
pnpm install
node src/app.ts      # Node 24 runs the TypeScript directly; no build step
pnpm lint            # tsc, oxlint (type-aware), oxfmt --check
pnpm format          # oxfmt
```

## Conventions

- Services go in `services` in `src/app.ts`. `restate.connect` (Restate Cloud) is what is
  committed; `restate.serve` is for a Restate server on this machine.
- Import the Restate SDK from `@restatedev/sessions`, which re-exports it at the version it
  pins. Don't add another `@restatedev/restate-sdk` version.
- Runtime dependencies go in `dependencies`: the Modal image installs production
  dependencies only, and copies only `src/`.
- Keys (`RESTATE_CONNECT_KEY`, model API keys) come from the environment, and on Modal from
  its secret. Never commit them.
- The files in `.agents/skills/building-restate-services/references/` that start with a
  "From restatedev/skills" banner are copied from https://github.com/restatedev/skills:
  change them there, not here.
