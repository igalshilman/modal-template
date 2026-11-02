# A Restate application on Modal

A Restate application using SQLite running on [Modal](https://modal.com), connected to
[Restate Cloud](https://cloud.restate.dev).

## Before you start

Get the connect key of your Restate Cloud environment from
[**Configure SDK -> Create connect key**](https://cloud.restate.dev/to/developers/integration#configure-sdk).

## Run it locally

With Node 24 or later and pnpm:

```sh
pnpm install
node src/app.ts
```

Then, once, [register `connect://wallet-v1`](https://cloud.restate.dev/to/overview?register-deployment=connect://wallet-v1)
in the Cloud UI (the application prints this link too), or with the CLI:

```sh
npx @restatedev/restate@1.8.1-hotfix.2 deployments register connect://template
```

Send a request from the [playground](https://cloud.restate.dev/to/overview?servicePlayground=wallet).

## Run it on Modal

[`modal/on_modal.py`](modal/on_modal.py) builds the image on Modal and runs one file in
one container, with your keys from a Modal secret:

```sh
pip install modal python-dotenv && modal setup
modal secret create restate-template RESTATE_CONNECT_KEY=${RESTATE_CONNECT_KEY}
modal deploy modal/on_modal.py
```

Register `connect://wallet-v1` as above, and send requests the same way.
`modal app logs restate-template` follows it.

## Using client to send requests

Get the ingress key of your Restate Cloud environment from
[**Configure SDK -> Create ingress key**](https://cloud.restate.dev/to/developers/integration#configure-sdk).

Then send requests using `@restatedev/restate-sdk-clients`:

```ts
import * as clients from '@restatedev/restate-sdk-clients';

const rs = clients.connect();
const alice = rs.objectClient({ name: 'wallet' }, 'alice');
console.log(await alice.hello()); // "Hello, alice!"
```