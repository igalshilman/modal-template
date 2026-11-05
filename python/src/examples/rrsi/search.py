"""The search: ``rrsi``, a session object with one key per run, and its rounds.

Each round is one ``step``. It reads the run from the database, works out the round (the calls
to models are each answered once), then commits everything the round found and sends the next
``step`` in one transaction. A crash at any point retries the step from its first line: it finds
the same answers, and commits once.
"""

import asyncio
from dataclasses import dataclass
from typing import Any

import restate
from pydantic import ValidationError
from restate import sessions

from .harness import BASE, COMPONENTS, Component, Edit, Harness, Proposal, apply_edits, diff
from .roles import analyst, analyst_prompt, ask, critic, critic_prompt, json_in, proposer, proposer_prompt, run_trial
from .rules import Settings, edit_budget, is_stalled, noise_band, novelty, rejection
from .tasks import EVOLVE, HELD_OUT, Task, leak, reward

rrsi = sessions.SessionObject(
    "rrsi",
    description="A search for a better harness, one key per run",
    migrations=[
        """CREATE TABLE run (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            settings TEXT NOT NULL,
            round INTEGER NOT NULL,
            best REAL NOT NULL,
            delta REAL NOT NULL,
            incumbent INTEGER NOT NULL,
            done INTEGER NOT NULL DEFAULT 0
        )""",
        """CREATE TABLE harnesses (
            id INTEGER PRIMARY KEY,
            body TEXT NOT NULL,
            round INTEGER NOT NULL,
            score REAL NOT NULL,
            cost REAL NOT NULL
        )""",
        """CREATE TABLE trials (
            harness INTEGER NOT NULL,
            task TEXT NOT NULL,
            trial INTEGER NOT NULL,
            reply TEXT NOT NULL,
            reward REAL NOT NULL,
            cost REAL NOT NULL
        )""",
        """CREATE TABLE rounds (
            t INTEGER PRIMARY KEY,
            score REAL NOT NULL,
            budget INTEGER NOT NULL,
            stalled INTEGER NOT NULL,
            feedback TEXT NOT NULL,
            winner INTEGER
        )""",
        """CREATE TABLE edits (
            round INTEGER NOT NULL,
            candidate INTEGER NOT NULL,
            component TEXT NOT NULL,
            op TEXT NOT NULL,
            name TEXT,
            hypothesis TEXT NOT NULL,
            verdict TEXT NOT NULL,
            ds REAL,
            dc REAL,
            accepted INTEGER NOT NULL DEFAULT 0
        )""",
    ],
)

BASE_ID = 1  # the base harness's id in the harnesses table


# --- The run's state, as the database holds it ----------------------------------------------------------


@dataclass(frozen=True)
class Run:
    settings: Settings
    round: int
    best: float  # S*, the best score so far
    delta: float  # the noise band
    incumbent: int  # the incumbent harness's id
    done: bool


async def load_run(db: sessions.DatabaseReader) -> Run | None:
    row = await db.get("SELECT settings, round, best, delta, incumbent, done FROM run")
    if row is None:
        return None
    return Run(
        settings=Settings.model_validate_json(str(row["settings"])),
        round=int(row["round"] or 0),
        best=float(row["best"] or 0),
        delta=float(row["delta"] or 0),
        incumbent=int(row["incumbent"] or BASE_ID),
        done=bool(row["done"]),
    )


@dataclass(frozen=True)
class Stored:
    """A harness as stored, with its score and cost on the evolve set."""

    id: int
    harness: Harness
    score: float
    cost: float


async def load_harness(db: sessions.DatabaseReader, id: int) -> Stored:
    row = await db.get("SELECT body, score, cost FROM harnesses WHERE id = ?", [id])
    if row is None:
        raise restate.TerminalError(f"No harness {id}")
    harness = Harness.model_validate_json(str(row["body"]))
    return Stored(id, harness, score=float(row["score"] or 0), cost=float(row["cost"] or 0))


# --- Evaluating a harness -------------------------------------------------------------------------------


@dataclass(frozen=True)
class Trial:
    task: str
    index: int
    reply: str
    reward: float
    cost: float


@dataclass(frozen=True)
class Evaluation:
    trials: list[Trial]

    @property
    def score(self) -> float:
        return sum(t.reward for t in self.trials) / len(self.trials)

    @property
    def cost(self) -> float:
        return sum(t.cost for t in self.trials) / len(self.trials)


async def evaluate(ctx: sessions.SessionContext, tag: str, harness: Harness, tasks: list[Task], k: int) -> Evaluation:
    """Run ``harness`` on each task ``k`` times, all at once; ``tag`` names its trials (``<run>.<tag>.<task>.<i>``)."""
    runs = [(task, i) for task in tasks for i in range(k)]
    results = await asyncio.gather(
        *(run_trial(ctx, f"{ctx.key}.{tag}.{task.id}.{i}", harness, task) for task, i in runs)
    )
    trials = [
        Trial(task.id, i, result.reply, reward(task, result.reply), result.cost)
        for (task, i), result in zip(runs, results, strict=True)
    ]
    return Evaluation(trials)


async def insert_trials(tx: sessions.Transaction, harness: int, trials: list[Trial], offset: int = 0) -> None:
    for t in trials:
        await tx.execute(
            "INSERT INTO trials (harness, task, trial, reply, reward, cost) VALUES (?, ?, ?, ?, ?, ?)",
            [harness, t.task, offset + t.index, t.reply, t.reward, t.cost],
        )


# --- Starting a run ------------------------------------------------------------------------------------------


@rrsi.handler
async def start(ctx: sessions.SessionContext, settings: Settings) -> dict[str, Any]:
    """Measure the noise band on the base harness, then start the rounds. Starting again does nothing."""
    if await load_run(ctx.db) is None:
        repeats = await asyncio.gather(
            *(evaluate(ctx, f"base{r}", BASE, EVOLVE, settings.trials) for r in range(settings.noise_repeats))
        )
        scores = [e.score for e in repeats]
        score, cost = sum(scores) / len(scores), sum(e.cost for e in repeats) / len(repeats)
        async with ctx.db.transaction() as tx:
            await tx.execute(
                "INSERT INTO harnesses (id, body, round, score, cost) VALUES (?, ?, -1, ?, ?)",
                [BASE_ID, BASE.model_dump_json(), score, cost],
            )
            for r, e in enumerate(repeats):
                await insert_trials(tx, BASE_ID, e.trials, offset=r * settings.trials)
            await tx.execute(
                "INSERT INTO run (id, settings, round, best, delta, incumbent) VALUES (1, ?, 0, ?, ?, ?)",
                [settings.model_dump_json(), score, noise_band(scores, settings), BASE_ID],
            )
            tx.send(step, 0, key=ctx.key)  # the first round, once this commits
    return await status_of(ctx.db)


# --- A round ----------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Plan:
    """What steers this round's proposals: the regularizers of the proposal side."""

    budget: int
    stalled: bool
    untried: list[Component]  # components never edited: required when stalled
    prune: list[str]  # components whose recent edits didn't help: to remove
    history: list[sessions.Row]  # the latest edits, for the proposer

    def rules(self, s: Settings) -> list[str]:
        rules = [f"Each candidate has at most {self.budget} edits."]
        if self.stalled and self.untried:
            untried = ", ".join(self.untried)
            rules.append(f"The score has stalled: at least {s.m_draft} candidate(s) must edit only {untried}.")
        if self.prune:
            pruned = ", ".join(self.prune)
            rules.append(f"Recent edits to {pruned} did not help: one candidate should remove that machinery.")
        return rules


async def plan(db: sessions.DatabaseReader, t: int, run: Run, incumbent: Stored) -> Plan:
    s = run.settings
    earlier = await db.get("SELECT score FROM rounds WHERE t = ?", [t - s.stall_window])
    tried = {str(r["component"]) for r in await db.query("SELECT DISTINCT component FROM edits")}
    gains = await db.query(
        "SELECT component, max(ds) AS gain FROM edits WHERE ds IS NOT NULL AND round >= ? GROUP BY component",
        [t - s.prune_window],
    )
    history = await db.query(
        """SELECT round, component, op, name, hypothesis, verdict, round(ds, 3) AS ds, accepted
        FROM edits ORDER BY round DESC, candidate LIMIT 30"""
    )
    return Plan(
        budget=edit_budget(t, s),
        stalled=is_stalled(incumbent.score, None if earlier is None else float(earlier["score"] or 0), run.delta),
        untried=[c for c in COMPONENTS if c not in tried],
        prune=[str(r["component"]) for r in gains if float(r["gain"] or 0) <= 0],
        history=history,
    )


@dataclass
class Draft:
    """A candidate, as it goes through the round: drafted, screened, evaluated, and accepted or rejected."""

    edits: list[Edit]
    harness: Harness | None = None
    rejected: str | None = None  # why, if it was
    evaluation: Evaluation | None = None
    accepted: bool = False

    @property
    def alive(self) -> bool:
        return self.harness is not None and self.rejected is None

    @property
    def verdict(self) -> str:
        return self.rejected or ("accepted" if self.accepted else "evaluated")


def draft(incumbent: Harness, edits: list[Edit], budget: int) -> Draft:
    """Apply a candidate's edits within the budget, and run the deterministic leakage guard."""
    d = Draft(edits)
    if not 0 < len(edits) <= budget:
        d.rejected = f"invalid: {len(edits)} edits, the budget is {budget}"
        return d
    try:
        d.harness = apply_edits(incumbent, edits)
    except ValueError as error:
        d.rejected = f"invalid: {error}"
        return d
    if (reason := leak(incumbent, d.harness, EVOLVE)) is not None:
        d.rejected = f"guard: {reason}"
    return d


async def screen(ctx: sessions.SessionContext, key: str, incumbent: Harness, d: Draft) -> None:
    """The critic's leakage screen, before any evaluation."""
    if not d.alive or d.harness is None:
        return
    answer = await ask(ctx, critic, key, critic_prompt(EVOLVE, diff(incumbent, d.harness)))
    try:
        verdict = json_in(answer)
    except ValueError:
        d.rejected = "critic: no verdict"
        return
    if verdict.get("verdict") != "pass":
        d.rejected = f"critic: {verdict.get('reason', 'rejected')}"


async def accepted_components(db: sessions.DatabaseReader) -> set[Component]:
    rows = await db.query("SELECT DISTINCT component FROM edits WHERE accepted = 1")
    return {c for c in COMPONENTS if c in {str(r["component"]) for r in rows}}


def select(drafts: list[Draft], incumbent: Stored, run: Run, accepted: set[Component]) -> int | None:
    """Reject the evaluated drafts that aren't admissible, and return the best of the others, if any."""
    winner: int | None = None
    best_seen: tuple[float, float] | None = None  # (score, -cost): higher is better
    for i, d in enumerate(drafts):
        if d.evaluation is None:
            continue
        e = d.evaluation
        reason = rejection(
            score=e.score,
            gain=e.score - incumbent.score,
            cost_change=(e.cost - incumbent.cost) / incumbent.cost,
            novel=novelty(d.edits, accepted),
            best=run.best,
            delta=run.delta,
            s=run.settings,
        )
        if reason is not None:
            d.rejected = f"not admissible: {reason}"
        elif best_seen is None or (e.score, -e.cost) > best_seen:
            winner, best_seen = i, (e.score, -e.cost)
    if winner is not None:
        drafts[winner].accepted = True
    return winner


@rrsi.handler
async def step(ctx: sessions.SessionContext, t: int) -> None:
    """Round ``t``: analyze, propose, screen, evaluate, select; then commit it, and send round ``t + 1``."""
    run = await load_run(ctx.db)
    if run is None or run.done or run.round != t:
        return  # a round sent twice: it ran already
    s = run.settings
    incumbent = await load_harness(ctx.db, run.incumbent)
    guidance = await plan(ctx.db, t, run, incumbent)

    # The analyst explains the incumbent's failures; the proposer drafts candidates.
    trials = await ctx.db.query("SELECT task, reply, reward FROM trials WHERE harness = ? LIMIT 20", [incumbent.id])
    feedback = await ask(ctx, analyst, f"{ctx.key}.r{t}", analyst_prompt(incumbent.harness, trials))
    prompt = proposer_prompt(incumbent.harness, feedback, guidance.history, s.candidates, guidance.rules(s))
    try:
        proposal = Proposal.model_validate(json_in(await ask(ctx, proposer, f"{ctx.key}.r{t}", prompt)))
    except (ValueError, ValidationError):
        proposal = Proposal(candidates=[])

    # Draft and screen each candidate, evaluate those that pass, and select.
    drafts = [draft(incumbent.harness, c.edits, guidance.budget) for c in proposal.candidates[: s.candidates]]
    await asyncio.gather(*(screen(ctx, f"{ctx.key}.r{t}.c{i}", incumbent.harness, d) for i, d in enumerate(drafts)))

    async def evaluate_draft(i: int, d: Draft) -> None:
        if d.alive and d.harness is not None:
            d.evaluation = await evaluate(ctx, f"r{t}c{i}", d.harness, EVOLVE, s.trials)

    await asyncio.gather(*(evaluate_draft(i, d) for i, d in enumerate(drafts)))
    winner = select(drafts, incumbent, run, await accepted_components(ctx.db))

    # Commit the round, and send the next one, together.
    async with ctx.db.transaction() as tx:
        new_incumbent, new_score = incumbent.id, incumbent.score
        for i, d in enumerate(drafts):
            harness_id = await record_draft(tx, t, i, d, incumbent)
            if d.accepted and harness_id is not None and d.evaluation is not None:
                new_incumbent, new_score = harness_id, d.evaluation.score
        await tx.execute(
            "INSERT INTO rounds (t, score, budget, stalled, feedback, winner) VALUES (?, ?, ?, ?, ?, ?)",
            [t, incumbent.score, guidance.budget, int(guidance.stalled), feedback, winner],
        )
        done = t + 1 >= s.rounds
        await tx.execute(
            "UPDATE run SET round = ?, best = ?, incumbent = ?, done = ?",
            [t + 1, max(run.best, new_score), new_incumbent, int(done)],
        )
        if not done:
            tx.send(step, t + 1, key=ctx.key)


async def record_draft(tx: sessions.Transaction, t: int, i: int, d: Draft, incumbent: Stored) -> int | None:
    """Record a draft's edits (with their verdict and effect) and, if it was evaluated, its harness and trials."""
    harness_id: int | None = None
    gain = cost_change = None
    if d.evaluation is not None and d.harness is not None:
        e = d.evaluation
        gain, cost_change = round(e.score - incumbent.score, 4), round((e.cost - incumbent.cost) / incumbent.cost, 4)
        await tx.execute(
            "INSERT INTO harnesses (body, round, score, cost) VALUES (?, ?, ?, ?)",
            [d.harness.model_dump_json(), t, e.score, e.cost],
        )
        row = await tx.get("SELECT max(id) AS id FROM harnesses")
        harness_id = int(row["id"] or 0) if row else None
        await insert_trials(tx, harness_id or 0, e.trials)
    for edit in d.edits:
        await tx.execute(
            """INSERT INTO edits (round, candidate, component, op, name, hypothesis, verdict, ds, dc, accepted)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [t, i, edit.component, edit.op, edit.name, edit.hypothesis, d.verdict, gain, cost_change, int(d.accepted)],
        )
    return harness_id


# --- Reading a run, and checking transfer ----------------------------------------------------------------


async def status_of(db: sessions.DatabaseReader) -> dict[str, Any]:
    run = await load_run(db)
    if run is None:
        return {"started": False}
    incumbent, base = await load_harness(db, run.incumbent), await load_harness(db, BASE_ID)
    rounds = await db.query("SELECT t, round(score, 3) AS score, budget, stalled, winner FROM rounds ORDER BY t")
    return {
        "started": True,
        "round": run.round,
        "done": run.done,
        "delta": run.delta,
        "base": {"score": base.score, "cost": round(base.cost)},
        "incumbent": {
            "score": incumbent.score,
            "cost": round(incumbent.cost),
            "harness": incumbent.harness.model_dump(),
        },
        "rounds": rounds,
    }


@rrsi.view
async def status(ctx: sessions.ViewContext) -> dict[str, Any]:
    """The round, the noise band, the base and the incumbent harness with their scores, and each round."""
    return await status_of(ctx.db)


@rrsi.view
async def history(ctx: sessions.ViewContext) -> list[sessions.Row]:
    """Every edit proposed: its hypothesis, its verdict, its effect on score and cost, and whether it won."""
    return await ctx.db.query(
        """SELECT round, candidate, component, op, name, hypothesis, verdict, ds, dc, accepted
        FROM edits ORDER BY round, candidate"""
    )


@rrsi.handler
async def held_out(ctx: sessions.SessionContext) -> dict[str, float]:
    """Run the base harness and the incumbent on the held-out tasks, which selection never saw."""
    run = await load_run(ctx.db)
    if run is None:
        raise restate.TerminalError("Not started")
    final = await load_harness(ctx.db, run.incumbent)
    k = run.settings.trials
    base, last = await asyncio.gather(
        evaluate(ctx, "heldout.base", BASE, HELD_OUT, k),
        evaluate(ctx, f"heldout.h{final.id}", final.harness, HELD_OUT, k),
    )
    return {"base": base.score, "incumbent": last.score}
