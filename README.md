# A Restate application on Modal

A Restate application running on [Modal](https://modal.com), connected to
[Restate Cloud](https://cloud.restate.dev). The application connects *out*
with `restate.connect`, so Modal exposes no port and no URL: one container,
always up, that Restate Cloud reaches over that connection.

## Before you start

Get the keys of your Restate Cloud environment from
[**Configure SDK**](https://cloud.restate.dev/to/developers/integration#configure-sdk)
and save the file here as `restate.env`.

## Run it locally

With Node 24 or later and pnpm:

```sh
pnpm install
node --env-file=restate.env src/01_object.ts
```

Then, once, [register `connect://template`](https://cloud.restate.dev/to/overview?register-deployment=connect://template)
in the Cloud UI (the application prints this link too), or with the CLI:

```sh
npx @restatedev/restate@1.8.1-hotfix.2 deployments register connect://template
```

Send a request from the [playground](https://cloud.restate.dev/to/overview?servicePlayground=wallet#/operations/hello).

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

## Using client to send requests

To send requests using the ingress client:

```ts
import * as clients from '@restatedev/restate-sdk-clients';

const rs = clients.connect();
const alice = rs.objectClient({ name: 'wallet' }, 'alice');
console.log(await alice.hello()); // "Hello, alice!"
```

This will use the configured key `RESTATE_INGRESS_KEY` from `restate.env`

To run another file, stop this one, start that, and register again.

Without Restate Cloud, every file ends with the `restate.serve` line to use
instead of `restate.connect`, commented out, for a Restate on this machine:

```sh
node src/01_object.ts                                                           # on port 9080
npx @restatedev/restate-server                                                  # Restate, in another terminal
npx @restatedev/restate -y deployments register --force http://localhost:9080
curl localhost:8080/wallet/alice/hello
```