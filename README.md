# A Restate application on Modal

A Restate application running on [Modal](https://modal.com), connected to
[Restate Cloud](https://cloud.restate.dev). The application connects *out*
with `restate.connect`, so Modal exposes no port and no URL: one container,
always up, that Restate Cloud reaches over that connection.

The application is a wallet for every user, with a SQL database per wallet
and an agent in it, built step by step: each file in `src/` runs on its own,
and its top comment lists the requests to try. `01_object.ts` is the
simplest; from `09_prompt.ts` on it asks OpenAI's models.

## Before you start

Get the keys of your Restate Cloud environment from
[Configure SDK](https://cloud.restate.dev/to/developers/integration#configure-sdk)
and save the file here as `restate.env` (it is in `.gitignore`). For the
agent, add your OpenAI API key to it as `OPENAI_API_KEY`.

## Run it locally

With Node 24 or later and pnpm:

```sh
pnpm install
node --env-file=restate.env src/01_object.ts
```

Then, once, [register `connect://template`](https://cloud.restate.dev/to/overview?register-deployment=connect://template)
in the Cloud UI (the application prints this link too), or with the CLI:

```sh
npx @restatedev/restate deployments register connect://template
```

Send a request from the
[playground](https://cloud.restate.dev/to/overview?servicePlayground=wallet#/operations/hello):
the wallet's `hello` handler, with `alice` as the key, answers
"Hello, alice!". Or from code, with the ingress key in `RESTATE_INGRESS_KEY`:

```ts
import * as clients from '@restatedev/restate-sdk-clients';

const rs = clients.connect({});
const alice = rs.objectClient({ name: 'wallet' }, 'alice');
console.log(await alice.hello()); // "Hello, alice!"
```

To run another file, stop this one, start that, and register again.

Without Restate Cloud, every file ends with the `restate.serve` line to use
instead of `restate.connect`, commented out, for a Restate on this machine:

```sh
node src/01_object.ts                                                           # on port 9080
npx @restatedev/restate-server                                                  # Restate, in another terminal
npx @restatedev/restate -y deployments register --force http://localhost:9080
curl localhost:8080/wallet/alice/hello
```

## Run it on Modal

[`on_modal.py`](on_modal.py) builds the image on Modal and runs one file in
one container, with your keys from a Modal secret, created once from
`restate.env`:

```sh
pip install modal python-dotenv && modal setup                                        # once
modal secret create restate-template --from-dotenv restate.env OPENAI_API_KEY=sk-…    # once
modal deploy on_modal.py                                                              # runs src/01_object.ts
LESSON=15_subagents modal deploy on_modal.py                                          # another file takes its place
```

Register `connect://template` as above, and send requests the same way.
`modal app logs restate-template` follows it; `modal app stop restate-template`
stops it.
