---
name: deploying-on-modal
description: >
  Run the TypeScript project's Restate app (typescript/) locally, connect it to Restate Cloud, and deploy it on
  Modal: the connect key, registering the deployment (connect://notes-v1), the Modal secret,
  modal deploy, logs, and changing modal/on_modal.py. Use when the user wants to run, test
  locally, deploy, redeploy, debug a deployment, add an API key or a system package to the
  image, or asks about Modal, Restate Cloud, RESTATE_CONNECT_KEY or on_modal.py.
---

# Run and deploy on Modal

The app is `src/app.ts`. Run every command from `typescript/`, the project's directory. The
app runs in one of three ways, chosen by its last lines:

| Where                                          | `src/app.ts` uses                                               | Who calls whom                             |
| ---------------------------------------------- | --------------------------------------------------------------- | ------------------------------------------ |
| A Restate server on this machine (development) | `await restate.serve(...services)`, on `PORT` (9080 by default) | Restate calls the app on port 9080         |
| This machine, against Restate Cloud            | `restate.connect({ services, name: 'notes-v1' })`               | The app connects out to Restate Cloud      |
| Modal, against Restate Cloud                   | `restate.connect(...)`, as committed                            | One always-on Modal container connects out |

`restate.connect` is what is committed: switch to `restate.serve` only for a local server,
and switch back before deploying. The app connects to Restate Cloud, rather than Restate
Cloud calling Modal, on purpose: long-lived HTTP/2 connections from Restate Cloud to Modal
sometimes get stuck (see the footnote in `README.md`). Don't change it to a pushed
deployment.

## Locally, with a Restate server (no account needed)

Swap `restate.connect(...)` for the commented `restate.serve(...)` line in `src/app.ts`, then:

```sh
pnpm install
node src/app.ts                                                     # the services, on port 9080
npx @restatedev/restate-server@1.8.1                                # Restate, in another terminal; UI on localhost:9070
npx @restatedev/restate@1.8.1 deployments register http://localhost:9080
curl localhost:8080/notes/alice/add --json '"Buy milk"'
curl localhost:8080/notes/alice/list
```

After changing the services, restart the app and register again with `--force`
(`npx @restatedev/restate@1.8.1 -y deployments register --force http://localhost:9080`).

## Against Restate Cloud

1. A connect key: Cloud UI, **Configure SDK -> Create connect key**
   (https://cloud.restate.dev/to/developers/integration#configure-sdk). `restate.connect`
   reads it from `RESTATE_CONNECT_KEY`. Never commit it: keep it in `restate.env` or `.env`,
   which `.gitignore` excludes.
2. Run the app: `RESTATE_CONNECT_KEY=… node src/app.ts`. It prints how to register.
3. Once per deployment name, register it: in the Cloud UI
   (https://cloud.restate.dev/to/overview?register-deployment=connect://notes-v1), or
   `npx @restatedev/restate@1.8.1-hotfix.2 deployments register connect://notes-v1`.
4. Send requests from the playground
   (https://cloud.restate.dev/to/overview?servicePlayground=notes), or with
   `@restatedev/restate-sdk-clients` and an ingress key (`RESTATE_INGRESS_KEY`, from
   **Configure SDK -> Create ingress key**): `clients.connect()` reads it.

## Calling handlers: a local server or Restate Cloud

Every example in these skills calls `http://localhost:8080`, a local server's ingress. On
Restate Cloud the paths, bodies and headers are the same, at your environment's ingress
URL, with an ingress key's API key as a bearer token:

|                | Local server                                        | Restate Cloud                                                                                            |
| -------------- | --------------------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| Ingress        | `http://localhost:8080`                             | `https://<environment id>.env.<region>:8080`, such as `https://201kab12cd34ef.env.eu.restate.cloud:8080` |
| Authentication | None                                                | `Authorization: Bearer <API key>`, of an ingress key (**Configure SDK -> Create ingress key**)           |
| UI and admin   | `http://localhost:9070`                             | The Cloud UI (https://cloud.restate.dev)                                                                 |
| The client     | `clients.connect({ url: 'http://localhost:8080' })` | `clients.connect()`, which reads the URL and the API key from `RESTATE_INGRESS_KEY`                      |

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

From code, with `@restatedev/restate-sdk-clients`, a dev dependency of this repository: the
app doesn't need it, and the Modal image installs production dependencies only.

```ts
// scripts/try.ts: `node --env-file=.env scripts/try.ts`, with RESTATE_INGRESS_KEY in .env
import * as clients from '@restatedev/restate-sdk-clients';

const restate = process.env.RESTATE_INGRESS_KEY
  ? clients.connect() // Restate Cloud: URL and API key from RESTATE_INGRESS_KEY
  : clients.connect({ url: 'http://localhost:8080' }); // a local server
// The handlers' types, each with its context first, as the object defines them.
type Notes = { add(ctx: unknown, note: string): Promise<void>; list(ctx: unknown): Promise<string[]> };
const alice = restate.objectClient<Notes>({ name: 'notes' }, 'alice');

await alice.add('Buy milk');
console.log(await alice.list());
```

`RESTATE_INGRESS_KEY` (for calling) and `RESTATE_CONNECT_KEY` (for the app to connect) are
different keys, both from **Configure SDK**. Keep them in `.env`, which `.gitignore`
excludes; `node --env-file=.env` loads it.

The deployment's name, `name` in `restate.connect` (`notes-v1`), identifies this version of
the code; replicas of one version share it. For a new version (services or handlers added,
changed or removed), use a new name (`notes-v2`) and register it. Restate sends new
invocations to the newest version, while invocations already running stay on theirs, and
need that version still connected to finish. With one Modal container running only the new
code, they can't: tell the user before switching. Versioning is in Restate's docs
(https://docs.restate.dev).

## On Modal

`modal/on_modal.py` builds the image on Modal and runs `node src/app.ts` in one container
(`min_containers=1`, `max_containers=1`), with its keys from the Modal secret
`restate-template`:

```sh
pip install modal python-dotenv && modal setup                                  # once
modal secret create restate-template RESTATE_CONNECT_KEY=${RESTATE_CONNECT_KEY} # once
modal deploy modal/on_modal.py                                                  # build and run; again after each change
modal app logs restate-template                                                 # follow it
modal app stop restate-template                                                 # stop it
```

Then register `connect://notes-v1` as above, once. Run the `modal` commands from
`typescript/`, the project's directory, as above. To check the Modal package itself, don't run
`python -c "import modal"` from there: Python finds the project's `modal/` folder first.

### What goes into the image

- `package.json`, `pnpm-workspace.yaml` and `pnpm-lock.yaml`, then
  `pnpm install --prod --frozen-lockfile`: **production dependencies only**, so anything
  `src/` imports at runtime must be in `dependencies`, and the lockfile must be up to date
  (`pnpm install` locally, and commit `pnpm-lock.yaml`).
- `src/`, as is. **Nothing else of the repository**: code the app imports must be under
  `src/`, or added to the image with another `add_local_dir` / `add_local_file`.
- Base image `node:24-bookworm-slim`, with Python beside it for Modal's runtime. It has no
  compiler and no git. A dependency that builds native code from source (OpenCode's
  `tree-sitter-powershell`, say) needs `.apt_install("python3", "make", "g++")` before the
  install; an agent that runs git needs `.apt_install("git", "ca-certificates")`.

### Keys and configuration

Every environment variable the app reads comes from the secret: model API keys
(`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, …) included. To add one, create the secret again
with all of its keys, and redeploy:

```sh
modal secret create restate-template --force RESTATE_CONNECT_KEY=… OPENAI_API_KEY=…
modal deploy modal/on_modal.py
```

Or from a file: `modal secret create restate-template --from-dotenv restate.env --force`.

### When it doesn't start

`on_modal.py` fails the container if the app exits within 10 seconds of starting, so a bad
connect key or a crash at import shows at once: read `modal app logs restate-template`.

- `RESTATE_CONNECT_KEY` missing or wrong: recreate the secret.
- A module not found: it is a dev dependency, or outside `src/`.
- `pnpm install` failing in the image build: the lockfile is out of date, or a native
  module needs build tools (see above).
- Requests not reaching the app: the deployment isn't registered, or it is registered under
  another name than `restate.connect`'s.

On shutdown, the container sends the app SIGTERM: the SDK finishes the requests in flight,
and Restate retries the rest on the next container.

## Before finishing

- [ ] `src/app.ts` ends with `restate.connect(...)` again if it was switched to `serve`
- [ ] New runtime dependencies are in `dependencies`, and `pnpm-lock.yaml` is updated
- [ ] New environment variables are documented and added to the Modal secret
- [ ] No key or secret was written into a committed file
- [ ] After a deploy, `modal app logs restate-template` shows the app connected, and a
      request through Restate Cloud answered
