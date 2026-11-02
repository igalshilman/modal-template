/**
 * The tutorial: a wallet per user, from a SQL database per key to agents,
 * one idea per lesson. The comment at the top of each lesson explains its
 * idea, and lists the requests to try it.
 *
 * Every lesson's objects carry its number (`wallet01` … `wallet16`,
 * `handle07`, `coach15`, …), so they can all be served by one deployment:
 * `tutorial` is all of them, in order. It is off by default: the comment in
 * src/app.ts shows how to include it.
 *
 * Lessons 09 to 16 ask OpenAI's models, with your key in `OPENAI_API_KEY`.
 */
import { signals } from '@restatedev/agents';
import * as l01 from './01_object.ts';
import * as l02 from './02_database.ts';
import * as l03 from './03_views.ts';
import * as l04 from './04_schema.ts';
import * as l05 from './05_transaction.ts';
import * as l06 from './06_retries.ts';
import * as l07 from './07_calls.ts';
import * as l08 from './08_sends.ts';
import * as l09 from './09_prompt.ts';
import * as l10 from './10_agent.ts';
import * as l11 from './11_tools.ts';
import * as l12 from './12_tool_writes.ts';
import * as l13 from './13_restate_tools.ts';
import * as l14 from './14_approval.ts';
import * as l15 from './15_subagents.ts';
import * as l16 from './16_pi_durable.ts';

export const tutorial = [
  // Part 1 · A database per key
  ...l01.services,
  ...l02.services,
  ...l03.services,
  ...l04.services,
  // Part 2 · Changes that happen once
  ...l05.services,
  ...l06.services,
  ...l07.services,
  ...l08.services,
  // Part 3 · Agents
  ...l09.services,
  ...l10.services,
  ...l11.services,
  ...l12.services,
  ...l13.services,
  ...l14.services,
  ...l15.services,
  // Appendix
  ...l16.services,
  // What the agents need beside them: `signal` tools (14) are answered through it.
  signals,
];
