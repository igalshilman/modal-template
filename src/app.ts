/**
 * The application: the services it serves, and how it reaches Restate.
 *
 * It serves the tutorial (src/tutorial): sixteen lessons, from a SQL
 * database per key to agents. Add your own services next to it, or replace
 * it with them. Lessons 09 to 16 ask OpenAI's models, so set
 * `OPENAI_API_KEY` too.
 *
 * Restate Cloud (as is, and on Modal): the app connects out to your Cloud
 * environment, so it needs no open port, only RESTATE_CONNECT_KEY (Cloud UI ->
 * Configure SDK -> Create connect key):
 *
 *   RESTATE_CONNECT_KEY=… OPENAI_API_KEY=… node src/app.ts
 *   npx @restatedev/restate deployments register connect://tutorial-v1    # once; the app prints this too
 *
 * A Restate server on this machine: swap the `connect` line below for the
 * `serve` line, and Restate calls the app on port 9080:
 *
 *   OPENAI_API_KEY=… node src/app.ts
 *   npx @restatedev/restate-server                                                  # in another terminal
 *   npx @restatedev/restate -y deployments register --force http://localhost:9080   # once, and after each change
 *   curl localhost:8080/wallet01/alice/hello                                        # "Hello, alice!"
 */
import * as restate from '@restatedev/sessions';
import { tutorial } from './tutorial/index.ts';

const services = [...tutorial];

restate.connect({ services, name: 'tutorial-v1' });
// await restate.serve({ services, port: 9080 });
