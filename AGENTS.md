# Working on this repository

A starter kit for Restate on Modal, in two languages. Each is a complete project of its own,
with its own instructions, skills, dependencies and Modal app:

- [`typescript/`](typescript): read [`typescript/AGENTS.md`](typescript/AGENTS.md).
- [`python/`](python): read [`python/AGENTS.md`](python/AGENTS.md).

Find out which project the task is about before starting (ask if it isn't clear), then follow
only that project's `AGENTS.md`, and load its skills (`<project>/.agents/skills/`, and
`<project>/.claude/skills/` for Claude Code). Run its commands from its directory.

A change to one project doesn't need to be made in the other, unless asked. When the
projects' shared story changes (the outline in `README.md`, how the app runs, the
tutorial's lessons), say whether the other project should follow.

Never commit keys (`RESTATE_CONNECT_KEY`, model API keys): they come from the environment,
and on Modal from its secret.
