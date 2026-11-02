# A Restate application on Modal

The [`@restatedev/sessions` tutorial](https://github.com/restatedev/sdk-sessions/tree/main/packages/template),
a wallet for every user, from a SQL database per key to agents, deployed on
[Modal](https://modal.com) and connected to [Restate Cloud](https://cloud.restate.dev).
Each lesson in `src/` is one file that runs on its own; the comment at the top
explains it and lists the requests to try.

The lesson connects *out* to Restate Cloud with `restate.connect`, the last
line of each lesson, so Modal exposes no port and no URL: one container runs
the lesson, always up, and Restate Cloud reaches it over that connection.

## Before you start

You need the keys of a [Restate Cloud](https://cloud.restate.dev) environment:
[Configure SDK](https://cloud.restate.dev/to/developers/integration#configure-sdk)
downloads them as a file. Save it here as `restate.env` (it is in
`.gitignore`). Lessons 09 to 16 ask OpenAI's models, with your API key in
`OPENAI_API_KEY`.

## Run it locally

With Node 24 or later and pnpm:

```sh
pnpm install
node --env-file=restate.env src/01_object.ts   # connects to Restate Cloud
```

Then, once, tell Restate Cloud about the deployment, named `template` in
`on_modal.py` (the lesson prints this too):

```sh
npx @restatedev/restate deployments register connect://template
```

Now call the wallet through your environment's ingress: from the Cloud UI's
playground, or from code with the ingress key in `RESTATE_INGRESS_KEY`:

```ts
import * as clients from '@restatedev/restate-sdk-clients';

const rs = clients.connect({}); // the environment and the key from RESTATE_INGRESS_KEY
const alice = rs.objectClient({ name: 'wallet' }, 'alice');
console.log(await alice.hello()); // "Hello, alice!"
```

The requests to try are at the top of each lesson, as `curl` against a local
Restate: on Cloud, send the same paths and bodies through the ingress. The
Cloud UI shows every request and what it did.

To move on, stop the lesson, start the next one, and register again: the
wallets you filled in one lesson are still there in the next, just as a real
application keeps its data across releases.

Without Restate Cloud, every lesson ends with the `restate.serve` line to use
instead of `restate.connect`, commented out. With it, Restate runs on this
machine:

```sh
node src/01_object.ts                                                           # the lesson, on port 9080
npx @restatedev/restate-server                                                  # Restate, in another terminal
npx @restatedev/restate -y deployments register --force http://localhost:9080   # tell Restate where it is
curl localhost:8080/wallet/alice/hello
```

## Run it on Modal

[`on_modal.py`](on_modal.py) builds the image on Modal (`pnpm install`) and
runs `node src/<lesson>.ts` in one container, with your keys from a Modal
secret, created once from `restate.env`:

```sh
pip install modal python-dotenv && modal setup                                        # once
modal secret create restate-template --from-dotenv restate.env OPENAI_API_KEY=sk-…    # once
modal deploy on_modal.py                                                              # builds the image, runs lesson 01
LESSON=15_subagents modal deploy on_modal.py                                          # another lesson takes its place
```

Register the deployment as above, `connect://template`, and call it the same
way. `modal app logs restate-template` follows the lesson, and
`modal app stop restate-template` stops it.
