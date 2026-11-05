/**
 * 04 · Changing the schema
 *
 * Once alice's database exists, editing its CREATE TABLE statement would
 * change nothing for her. That's why `schema` is a list of steps: to change
 * the tables, add a step at the end. Each key's database runs the steps it
 * hasn't run yet, the next time it is used. Never edit or remove a step that
 * may have run somewhere; add a new one instead.
 *
 * Here, deposits get a note. (`wallet04` is new, so its databases run both
 * steps on first use; a wallet released before the note would run only the
 * second.)
 *
 *   curl localhost:8080/wallet04/alice/deposit --json '{"amount": 20}'
 *   curl localhost:8080/wallet04/alice/deposit --json '{"amount": 50, "note": "birthday"}'
 *   curl localhost:8080/wallet04/alice/history                                          # the first deposit has no note
 */
import * as restate from '@restatedev/sessions';

const balanceOf = async (db: restate.DatabaseReader) =>
  (await db.get<{ balance: number }>('SELECT coalesce(sum(amount), 0) AS balance FROM entries'))?.balance ?? 0;

const wallet = restate.sessionObject({
  name: 'wallet04',
  schema: [
    'CREATE TABLE entries (amount INTEGER NOT NULL)', // as in lesson 02
    'ALTER TABLE entries ADD COLUMN note TEXT', // new: runs once on each wallet's database
  ],
  handlers: {
    deposit: async (ctx, { amount, note }: { amount: number; note?: string }) => {
      await ctx.db.execute('INSERT INTO entries (amount, note) VALUES (?, ?)', [amount, note ?? null]);
      return balanceOf(ctx.db);
    },
  },
  views: {
    balance: async (ctx) => balanceOf(ctx.db),

    history: async (ctx) =>
      ctx.db.query<{ amount: number; note: string | null }>('SELECT amount, note FROM entries ORDER BY rowid'),
  },
});

export const services = [wallet];
