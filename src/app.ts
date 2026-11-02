/**
 * A database per key
 *
 * Each key of a session object has its own SQLite database, `ctx.db`. It is
 * stored in Restate together with the object's state, so there is no
 * database server to run. `schema` lists the statements that create the
 * tables; they run once per key, the first time that key is used.
 *
 * The wallet records each deposit as a row, and the balance is their sum.
 * Bob's wallet is another key, so it has a database of its own.
 */
import * as restate from '@restatedev/sessions';

const wallet = restate.sessionObject({
  name: 'wallet',
  schema: ['CREATE TABLE entries (amount INTEGER NOT NULL)'],
  handlers: {
    deposit: async (ctx, amount: number) => {
      await ctx.db.execute('INSERT INTO entries (amount) VALUES (?)', [amount]);
      // `get` returns the first row as an object, with a property per column.
      const row = await ctx.db.get<{ balance: number }>('SELECT sum(amount) AS balance FROM entries');
      return row?.balance;
    },
  },
});

const services = [wallet];

restate.connect({ services, name: 'wallet-v1' });
// To run locally, with a Restate server on this machine, use this instead:
// await restate.serve({ services, port: 9080 });

// The tutorial (src/tutorial) is off by default: sixteen lessons, from a SQL
// database per key to agents. To try it, serve its lessons next to the wallet
// (lessons 09 to 16 also need OPENAI_API_KEY):
//
//   import { tutorial } from './tutorial/index.ts';   // at the top
//   const services = [wallet, ...tutorial];
