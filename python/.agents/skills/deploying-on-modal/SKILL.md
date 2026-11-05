---
name: deploying-on-modal
description: >
  Run the Python project's Restate app (python/) locally, connect it to Restate Cloud, and
  deploy it on Modal: the connect key, registering the deployment
  (connect://notes-python-v1), the Modal secret, modal deploy, logs, and changing
  modal/on_modal.py. Use when the user wants to run, test locally, deploy, redeploy, debug a
  deployment, add an API key, a dependency or a system package to the image, or asks about
  Modal, Restate Cloud, RESTATE_CONNECT_KEY or on_modal.py.
---

# Run and deploy on Modal

The app is `app/__main__.py`: it defines the services, the ASGI app `app` (`restate.app([...])`),
and ends with `restate.serve(app)`. Run every command from `python/`, the project's directory.
The same `app` runs in one of three ways, and nothing in the file changes between them:

| Where                                          | Command                                                                | Who calls whom                             |
| ---------------------------------------------- | ---------------------------------------------------------------------- | ------------------------------------------ |
| A Restate server on this machine (development) | `uv run app`: `restate.serve`, on `PORT` (9080 by default)             | Restate calls the app on port 9080         |
| This machine, against Restate Cloud            | `uv run python -m restate connect app.__main__:app --name notes-python-v1` | The app connects out to Restate Cloud  |
| Modal, against Restate Cloud                   | `modal/on_modal.py` runs that same `python -m restate connect …`       | One always-on Modal container connects out |

Importing `app.__main__` doesn't serve it (the `serve` is under `if __name__ == "__main__"`), so
`python -m restate connect` takes the `app` and connects it instead: the app connects out to
Restate Cloud, rather than Restate Cloud calling Modal.

Only `app/` is deployed. `tutorial/` is for reading and copying into `app/__main__.py`, and
each module of `examples/` ends with an `app` of its own, served one at a time on this
machine: `uv run python -m restate serve examples.<name>:app`
(`chat`, `langgraph_agent`, `models`, `memory`, `support`), or connected to Restate Cloud
with `python -m restate connect examples.<name>:app --name <name>-python-v1`.

## Locally, with a Restate server (no account needed)

```sh
uv sync
uv run app                                                          # the services, on port 9080
npx @restatedev/restate-server@1.8.1                                # Restate, in another terminal; UI on localhost:9070
npx @restatedev/restate@1.8.1 deployments register http://localhost:9080
curl localhost:8080/notes/alice/add --json '"Buy milk"'
curl localhost:8080/notes/alice/list
```

After changing the services, or switching to an example
(`python -m restate serve examples.<name>:app`), restart and register again with `--force`
(`npx @restatedev/restate@1.8.1 deployments register --force --yes http://localhost:9080`).
If ports 8080 or 9070 are taken (another Restate server, in Docker say), stop it first.

## Against Restate Cloud

1. A connect key: Cloud UI, **Configure SDK -> Create connect key**
   (https://cloud.restate.dev/to/developers/integration#configure-sdk). `python -m restate
   connect` reads it from `RESTATE_CONNECT_KEY`. Never commit it: keep it in `restate.env` or `.env`,
   which `.gitignore` excludes.
2. Run the app: `uv run --env-file restate.env python -m restate connect app.__main__:app --name notes-python-v1`
   (or with `RESTATE_CONNECT_KEY=…` in front instead of `--env-file`).
3. Once per deployment name, register it: in the Cloud UI
   (https://cloud.restate.dev/to/overview?register-deployment=connect://notes-python-v1), or
   with the CLI, signed in to Restate Cloud first (`restate cloud login`, which also selects
   the environment; without it, the CLI talks to `localhost:9070`):
   `npx @restatedev/restate@1.8.1-hotfix.2 deployments register connect://notes-python-v1`.
4. Send requests from the playground
   (https://cloud.restate.dev/to/overview?servicePlayground=notes), or with the SDK's client
   and an ingress key (`RESTATE_INGRESS_KEY`, from **Configure SDK -> Create ingress key**):
   `restate.create_client()` reads it.

## Calling handlers: a local server or Restate Cloud

Every example in these skills calls `http://localhost:8080`, a local server's ingress. On
Restate Cloud the paths, bodies and headers are the same, at your environment's ingress
URL, with an ingress key's API key as a bearer token:

|                | Local server                                       | Restate Cloud                                                                                            |
| -------------- | -------------------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| Ingress        | `http://localhost:8080`                            | `https://<environment id>.env.<region>:8080`, such as `https://201kab12cd34ef.env.eu.restate.cloud:8080` |
| Authentication | None                                               | `Authorization: Bearer <API key>`, of an ingress key (**Configure SDK -> Create ingress key**)           |
| UI and admin   | `http://localhost:9070`                            | The Cloud UI (https://cloud.restate.dev)                                                                 |
| The client     | `restate.create_client("http://localhost:8080")`   | `restate.create_client()`, which reads the URL and the API key from `RESTATE_INGRESS_KEY`                |

The Cloud UI shows the environment's ingress URL and the ingress key's API key. The URL
above is a placeholder: use yours.

```sh
# A local server
curl localhost:8080/notes/alice/add --json '"Buy milk"'
curl localhost:8080/notes/alice/list

# Restate Cloud: the same requests, at your ingress, with your ingress API key
RESTATE_INGRESS_URL=https://201kab12cd34ef.env.eu.restate.cloud:8080   # placeholder: yours from the Cloud UI
curl "$RESTATE_INGRESS_URL/notes/alice/add" -H "Authorization: Bearer $RESTATE_INGRESS_API_KEY" --json '"Buy milk"'
curl "$RESTATE_INGRESS_URL/notes/alice/list" -H "Authorization: Bearer $RESTATE_INGRESS_API_KEY"
```

Everything else in the examples carries over as it is: `/send`, `/restate/invocation/…/attach`,
and the `idempotency-key` header.

From code, with the SDK's client: the `client` extra of `restate-sdk`, in the `dev` group,
since the app doesn't need it and the Modal image installs the runtime dependencies only.
`object_call` is typed by the handler function itself:

```python
# scripts/try.py: `PYTHONPATH=. uv run --env-file .env scripts/try.py`, with RESTATE_INGRESS_KEY in .env
import asyncio
import os

import restate
from app.__main__ import add, list_notes  # importing it doesn't serve it: that is under `if __name__`


async def main() -> None:
    # Restate Cloud: URL and API key from RESTATE_INGRESS_KEY; else a local server.
    ingress = None if os.environ.get("RESTATE_INGRESS_KEY") else "http://localhost:8080"
    async with restate.create_client(ingress) as client:
        await client.object_call(add, key="alice", arg="Buy milk")
        print(await client.object_call(list_notes, key="alice", arg=None))


asyncio.run(main())
```

`client.generic_call(service, handler, arg_bytes, key=...)` calls by name, with raw JSON
bytes in and out.

`RESTATE_INGRESS_KEY` (for calling) and `RESTATE_CONNECT_KEY` (for the app to connect) are
different keys, both from **Configure SDK**. Keep them in `.env`, which `.gitignore`
excludes; `uv run --env-file .env` loads it.

The deployment's name, `--name` (`notes-python-v1`, `NAME` in `modal/on_modal.py`), identifies this
version of the code; replicas of one version share it. For a new version (services or
handlers added, changed or removed), use a new name (`notes-python-v2`) and register it.
Restate sends new invocations to the newest version, while invocations already running stay
on theirs, and need that version still connected to finish. With one Modal container running
only the new code, they can't: tell the user before switching. Versioning is in Restate's
docs (https://docs.restate.dev).

## On Modal

`modal/on_modal.py` builds the image on Modal and runs
`python -m restate connect app.__main__:app --name notes-python-v1` in one container
(`min_containers=1`), with its keys from the Modal secret
`restate-template`. The Modal app is `restate-template-python`. `modal` is a dev dependency
of the project, so `uv run modal …` runs it:

```sh
uv sync && uv run modal setup                                                          # once
uv run modal secret create restate-template RESTATE_CONNECT_KEY=… OPENAI_API_KEY=…    # once
uv run modal deploy modal/on_modal.py                                                  # build and run; again after each change
uv run modal app logs restate-template-python                                          # follow it
uv run modal app stop restate-template-python                                          # stop it
```

Then register `connect://notes-python-v1` as above, once. To check the Modal package itself,
don't run `python -c "import modal"` from `python/`: Python finds the project's `modal/`
folder first.

### What goes into the image

- `pyproject.toml` and `uv.lock`, then `uv sync --no-default-groups` (`Image.uv_sync`):
  **the `[project] dependencies` only**, at the versions of `uv.lock`. So anything `app/`
  imports at runtime must be there, not in the `dev` or `examples` group, and the lockfile must be up to date
  (`uv lock` locally, and commit `uv.lock`). A framework's agents need its extra of
  `restate-sdk` (`restate-sdk[serve,openai]`) and its model provider's package.
- `app/`, as is, at `/srv/app`. **Nothing else of the project**, not `tutorial/` nor
  `examples/`: code the app imports must be under `app/`, or added to the image with another `add_local_dir` / `add_local_file`.
- Base image `debian_slim` with Python 3.13. It has no compiler and no git. A dependency that
  builds from source needs `.apt_install("build-essential")` before `uv_sync`; an agent that
  runs git needs `.apt_install("git", "ca-certificates")`.

### Keys and configuration

Every environment variable the app reads comes from the secret: model API keys
(`OPENAI_API_KEY` for the assistant, `ANTHROPIC_API_KEY`, …) included. To add one, create the secret again
with all of its keys, and redeploy:

```sh
uv run modal secret create restate-template --force RESTATE_CONNECT_KEY=… OPENAI_API_KEY=…
uv run modal deploy modal/on_modal.py
```

Or from a file: `uv run modal secret create restate-template --from-dotenv restate.env --force`.

### When it doesn't start

`on_modal.py` fails the container if the app exits within 10 seconds of starting, so a bad
connect key or a crash at import shows at once: read `uv run modal app logs restate-template-python`.

- `RESTATE_CONNECT_KEY` missing or wrong: recreate the secret.
- A module not found: it is in the `dev` or `examples` group, outside `app/`, or `uv.lock` is
  out of date.
- `uv sync` failing in the image build: the lockfile is out of date, or a dependency needs
  build tools (see above).
- Requests not reaching the app: the deployment isn't registered, or it is registered under
  another name than `NAME` in `modal/on_modal.py`.

On shutdown, the container sends the app SIGTERM: the SDK finishes the requests in flight,
and Restate retries the rest on the next container.

## Before finishing

- [ ] `app/__main__.py` still ends with `restate.serve(app)` under `if __name__ == "__main__"`
- [ ] New runtime dependencies are in `[project] dependencies`, and `uv.lock` is updated
- [ ] New environment variables are documented and added to the Modal secret
- [ ] No key or secret was written into a committed file
- [ ] After a deploy, `uv run modal app logs restate-template-python` shows the app
      connected, and a request through Restate Cloud answered
