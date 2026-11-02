/**
 * A demo app: notes per user.
 *
 * Each key of a session object (`alice`, `bob`, …) has its own SQLite
 * database, `ctx.db`, stored in Restate together with the object's state.
 */
import * as restate from '@restatedev/sessions';

const notes = restate.sessionObject({
  name: 'notes',
  // Creates each key's database. Each statement runs once per key; append new ones later as needed.
  schema: ['CREATE TABLE notes (text TEXT NOT NULL)'],
  handlers: {
    add: async (ctx, note: string) => {
      await ctx.db.execute('INSERT INTO notes (text) VALUES (?)', [note]);
    },
  },
  views: {
    /** A view only reads, so it can run while `add` is writing. */
    list: async (ctx) => {
      const rows = await ctx.db.query<{ text: string }>('SELECT text FROM notes ORDER BY rowid');
      return rows.map(({ text }) => text);
    },
  },
});

const services = [notes];

restate.connect({ services, name: 'notes-v1' });
// To run locally, with a Restate server on this machine, use this instead:
// await restate.serve({ services, port: 9080 });

// The tutorial (src/tutorial) is off by default: sixteen lessons, from a SQL
// database per key to agents. To try it, serve its lessons next to the notes
// (lessons 09 to 16 also need OPENAI_API_KEY):
//
//   import { tutorial } from './tutorial/index.ts';   // at the top
//   const services = [notes, ...tutorial];
