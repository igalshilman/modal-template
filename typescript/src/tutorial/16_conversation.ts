/**
 * 16 · Appendix: more than a chat
 *
 * `pi.chat()` answers messages. For anything else you want to do with the
 * conversation, `pi.withPi(ctx, options, work)` hands `work` the same
 * conversation `chat` uses: here, a handler that compacts it, and one that
 * starts it over, keeping only a note you give it. Compacting has the model
 * summarize all but the latest part of the conversation (about its last
 * 20,000 tokens, which pi keeps as they are), so that later turns send fewer
 * tokens: a conversation shorter than that, like the one below, stays as it
 * is. (The handler is `shorten`: `compact` is a name every agent keeps for
 * itself, as it does `steer`, `stop` and `clear`.)
 *
 * Both are handlers of the wallet, so they wait for the message being
 * answered, and run one at a time with the messages. A crash runs them
 * again, which is harmless: compacting again only shortens the conversation
 * further, and starting over again with the same note ends the same.
 *
 * They change what the model sees, not what was said: `messages` still
 * shows every message and answer, as it was.
 *
 *   curl localhost:8080/wallet16/alice/chat -d 'I am saving up for a bike, 600, by June.'
 *   curl localhost:8080/wallet16/alice/shorten                                # too short to shorten yet
 *   curl localhost:8080/wallet16/alice/chat -d 'What am I saving for?'        # the bike
 *   curl localhost:8080/wallet16/alice/startOver --json '"Alice now saves for a laptop."'
 *   curl localhost:8080/wallet16/alice/chat -d 'What am I saving for?'        # the laptop
 *   curl localhost:8080/wallet16/alice/messages                               # all of it, the bike too
 */
import { sessionObject } from '@restatedev/agents';
import * as pi from '@restatedev/agents/pi';

// The same options for every handler that talks to the model.
const options: pi.Options = { system: "You are the assistant of the user's wallet. Keep your answers short." };

const wallet = sessionObject({
  name: 'wallet16',
  handlers: {
    chat: pi.chat(options),

    shorten: async (ctx) =>
      pi.withPi(ctx, options, async ({ conversation, context }) => {
        const root = await conversation();
        await root.compact(undefined, context);
        await root.waitForIdle(context);
      }),

    startOver: async (ctx, note?: string) =>
      pi.withPi(ctx, options, async ({ conversation, context }) => {
        await (await conversation()).reset(note || undefined, context);
      }),
  },
  views: {
    messages: pi.messages(),
  },
});

export const services = [wallet];
