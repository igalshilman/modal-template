"""
RRSI, simplified: regularized recursive self-improvement of an agent's harness.

After "RRSI: Regularized Recursive Self-Improvement of Agent Harnesses"
(https://arxiv.org/abs/2609.24972). An agent is a fixed model plus a harness: its prompt, its
skills and its tools. RRSI improves the harness in rounds, on a small set of tasks (the evolve
set): an analyst explains the failures, a proposer suggests edits, and a candidate replaces the
incumbent only if it passes regularizers that keep the search from overfitting that set:

- An edit budget that anneals from ``b_max`` edits per candidate down to ``b_min`` (cosine).
- A leakage screen before evaluation: a deterministic guard, then a critic model, reject edits
  that carry the tasks' answers or task-specific values.
- A noise band ``delta``, measured by evaluating the unchanged base harness several times: a
  candidate must score at least the best score so far minus ``delta``; above the band, its cost
  may grow only in proportion to its gain (``dC <= beta0 + beta1 * dS``); within the band, it must
  pay for itself (``w_s * dS - w_c * dC + w_n * novelty > 0``), so a simpler harness wins a tie.
- Every edit is recorded with its hypothesis and its effect, rejected ones too. When the score
  stalls, the proposer must try components it hasn't tried; components whose recent edits
  didn't help are offered for removal.

A held-out set, never used for selection, then shows whether the gains transfer.

Simplifications: a harness is a system prompt, named skills and tools from a fixed registry; the
tasks have exact answers, so the reward is deterministic; the cost is an estimate of tokens
from text lengths, not the model's usage.

How it runs on Restate: ``rrsi`` is a session object, one key per run, whose database holds the
harnesses, every trial, the rounds and the edit history. Each round is one ``step``: it computes
everything, then commits the round's records and sends the next ``step`` in one transaction, so
the loop advances once per round, whatever crashes. Every model call is a Restate call with a
stable idempotency key (the trials, and the analyst, proposer and critic, each an agent with a
conversation per round), so a retried round gets the same answers rather than asking again.

To serve it, add ``rrsi.services`` to ``services`` in src/app.py (see src/examples/__init__.py).
It needs OPENAI_API_KEY, and makes many model calls: with the defaults, about 50 per round::

    curl localhost:8080/rrsi/run1/start/send --json '{}'          # measure the noise band, then run the rounds
    curl localhost:8080/rrsi/run1/status                          # the round, the scores, the incumbent harness
    curl localhost:8080/rrsi/run1/history                         # every edit: its hypothesis, verdict and effect
    curl localhost:8080/rrsi/run1/held_out                        # once done: base and final harness on unseen tasks
    curl localhost:8080/rrsi_proposer/run1.r0/messages            # what the proposer was asked, and answered, in round 0

``start`` takes the settings (see ``Settings``), such as ``{"rounds": 2, "trials": 1}``.
"""

import ast
import asyncio
import difflib
import json
import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

import restate
from pydantic import BaseModel, ValidationError
from restate import sessions
from restate.agents import AgentObject, openai, tool

# --- The harness, and the edits to it --------------------------------------------------------------

Component = Literal["prompt", "skill", "client_tool"]
COMPONENTS: tuple[Component, ...] = ("prompt", "skill", "client_tool")
STRUCTURAL: tuple[Component, ...] = ("skill", "client_tool")  # what counts as novelty (the paper's nu)


class Harness(BaseModel):
    """What the policy runs with: its instructions are ``system`` and the skills; its tools come from ``TOOLS``."""

    system: str
    skills: dict[str, str] = {}
    tools: list[str] = []


BASE = Harness(system="Answer the question.")


class Edit(BaseModel):
    """One atomic edit, with the hypothesis behind it."""

    component: Component
    op: Literal["set", "add", "remove"]
    name: str | None = None  # the skill's or the tool's name
    value: str | None = None  # the prompt text, or the skill's text
    hypothesis: str = ""


class Candidate(BaseModel):
    edits: list[Edit]


class Proposal(BaseModel):
    candidates: list[Candidate]


def instructions_of(harness: Harness) -> str:
    return "\n\n".join([harness.system, *(f"Skill ({name}): {text}" for name, text in sorted(harness.skills.items()))])


def applied(harness: Harness, edit: Edit) -> Harness:
    """Return ``harness`` with ``edit`` applied, or raise ``ValueError`` if it doesn't apply."""
    h = harness.model_copy(deep=True)
    match edit.component, edit.op:
        case "prompt", "set" if edit.value:
            h.system = edit.value
        case "prompt", "add" if edit.value:
            h.system = f"{h.system}\n{edit.value}"
        case "prompt", "remove" if edit.value and edit.value in h.system:
            h.system = h.system.replace(edit.value, "").strip()
        case "skill", "add" | "set" if edit.name and edit.value:
            h.skills[edit.name] = edit.value
        case "skill", "remove" if edit.name in h.skills:
            del h.skills[edit.name]
        case "client_tool", "add" if edit.name in TOOLS and edit.name not in h.tools:
            h.tools.append(edit.name)
        case "client_tool", "remove" if edit.name in h.tools:
            h.tools.remove(edit.name)
        case _:
            raise ValueError(f"does not apply: {edit.component} {edit.op} {edit.name or edit.value!r}")
    return h


def _lines(harness: Harness) -> list[str]:
    return json.dumps(harness.model_dump(), indent=2).splitlines()


def diff_of(old: Harness, new: Harness) -> str:
    return "\n".join(difflib.unified_diff(_lines(old), _lines(new), "incumbent", "candidate", lineterm=""))


# --- The tools a harness can give the policy -------------------------------------------------------

_OPERATORS: dict[type[ast.operator], Callable[[float, float], float]] = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
}


def _evaluate(node: ast.expr) -> float:
    if isinstance(node, ast.Constant) and isinstance(node.value, int | float):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPERATORS:
        return _OPERATORS[type(node.op)](_evaluate(node.left), _evaluate(node.right))
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -_evaluate(node.operand)
    raise restate.TerminalError("Only numbers, + - * / and parentheses")


@tool
def calculator(expression: str) -> str:
    """Evaluate an arithmetic expression: numbers, + - * / and parentheses."""
    try:
        result = _evaluate(ast.parse(expression, mode="eval").body)
    except SyntaxError as error:
        raise restate.TerminalError(f"Not an expression: {error.msg}") from error
    return f"{result:g}" if isinstance(result, float) and not result.is_integer() else str(int(result))


@tool
def count_letter(text: str, letter: str) -> int:
    """Count how many times a letter appears in a text (ignoring case)."""
    return text.lower().count(letter.lower())


TOOLS = {t.name: t for t in (calculator, count_letter)}


# --- The tasks: an evolve set to select on, and a held-out set to check transfer ---------------------


@dataclass(frozen=True)
class Task:
    id: str
    question: str
    answer: str
    subject: str  # the task-specific text that must not show up in a harness


def arithmetic(id: str, expression: str) -> Task:
    value = _evaluate(ast.parse(expression, mode="eval").body)
    return Task(id, f"What is {expression}?", str(int(value)), expression)


def letters(id: str, text: str, letter: str) -> Task:
    return Task(id, f"How many times does the letter {letter} appear in '{text}'?", str(text.count(letter)), text)


EVOLVE = [
    arithmetic("mul", "347 * 29"),
    arithmetic("sum", "1234 + 5678 + 91011"),
    arithmetic("mixed", "7 * 8 * 9 - 123"),
    letters("berries", "strawberry raspberry", "r"),
    letters("banana", "banana bandana", "a"),
]
HELD_OUT = [
    arithmetic("mul2", "613 * 47"),
    arithmetic("mixed2", "12 * 13 * 14 - 999"),
    letters("mississippi", "mississippi missouri", "s"),
]


def reward(task: Task, reply: str) -> float:
    """1 if the last number of the reply is the answer, else 0."""
    numbers = re.findall(r"-?\d[\d,]*", reply)
    return 1.0 if numbers and numbers[-1].replace(",", "") == task.answer else 0.0


def leak_of(old: Harness, new: Harness, tasks: list[Task]) -> str | None:
    """The deterministic leakage guard: the reason ``new`` adds a task's answer or subject, if it does."""
    added = "\n".join(line[1:] for line in diff_of(old, new).splitlines() if line.startswith("+"))
    for task in tasks:
        if re.search(rf"(?<![\d.]){re.escape(task.answer)}(?![\d.])", added) or task.subject in added:
            return f"carries task {task.id}'s answer or subject"
    if len(instructions_of(new)) > 4000:
        return "instructions over 4000 characters"
    return None


# --- The policy, and the roles of the search --------------------------------------------------------------


class TrialRequest(BaseModel):
    instructions: str
    tools: list[str]
    question: str


class TrialResult(BaseModel):
    reply: str
    cost: float


# One key per trial: each is a conversation of its own, answered once.
trial = AgentObject("rrsi_trial", description="One trial of a harness on a task", background=True)


@trial.handler
async def attempt(ctx: sessions.SessionContext, request: TrialRequest) -> TrialResult:
    reply = await openai.prompt(
        ctx, request.question, system=request.instructions, tools=[TOOLS[n] for n in request.tools if n in TOOLS]
    )
    # An estimate of the tokens: the text in and out, and each tool's schema.
    cost = (len(request.instructions) + len(request.question) + len(reply)) / 4 + 60 * len(request.tools)
    return TrialResult(reply=reply, cost=cost)


analyst = openai.agent(
    "rrsi_analyst",
    background=True,
    system="You analyze an agent's failures. Given its harness and its trials, say in a few short bullet points "
    "what kinds of mistakes it makes and what generic change to its harness might fix them. Never repeat answers.",
)

proposer = openai.agent(
    "rrsi_proposer",
    background=True,
    system="You improve an agent's harness: its system prompt, its skills (named instructions) and its tools. "
    "You propose candidate edits as JSON, and nothing else. Edits must be generic improvements: never a task's "
    "answer, its numbers or its text.",
)

critic = openai.agent(
    "rrsi_critic",
    background=True,
    system="You screen edits to an agent's harness for leakage before they are evaluated. Reject an edit that "
    "carries a task's name, answer or task-specific values, or that adds machinery that does nothing. Pass "
    'generic improvements. Answer with JSON only: {"verdict": "pass" or "reject", "reason": "..."}.',
)


def json_in(text: str) -> Any:
    """The JSON object in a model's reply, which may wrap it in prose or a code fence."""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("no JSON object")
    return json.loads(text[start : end + 1])


async def ask(ctx: sessions.SessionContext, agent: AgentObject, key: str, text: str) -> str:
    """Ask a role, in its conversation ``key``: once, however often the round is retried."""
    answer = await ctx.generic_call(agent.name, "chat", text, key=key, idempotency_key=f"{agent.name}/{key}")
    return str(answer)


# --- The search -------------------------------------------------------------------------------------------


class Settings(BaseModel):
    """The search's settings: the paper's symbols, with small defaults (the paper's coding setup in brackets)."""

    rounds: int = 4  # T [20]
    trials: int = 2  # k, trials per task [2]
    noise_repeats: int = 3  # evaluations of the base harness that measure delta
    min_delta: float = 0.02  # delta's floor [0.017]
    candidates: int = 3  # candidates per round
    b_min: int = 1  # [1]
    b_max: int = 3  # [4]
    stall_window: int = 2  # w [3]
    m_draft: int = 1  # candidates reserved for untried components when stalled [1]
    prune_window: int = 2  # n_prune [4]
    beta0: float = 0.10  # [0.10]
    beta1: float = 10.0  # [44.5]
    w_s: float = 1.0
    w_c: float = 0.5
    w_n: float = 0.05


def budget(t: int, s: Settings) -> int:
    """The edit budget of round ``t``: from ``b_max`` down to ``b_min``, on a cosine (the paper's Eq. 4)."""
    return math.ceil(s.b_min + (s.b_max - s.b_min) * 0.5 * (1 + math.cos(math.pi * t / s.rounds)))


@dataclass
class Evaluation:
    score: float
    cost: float
    trials: list[tuple[str, int, str, float, float]]  # task, trial, reply, reward, cost


async def evaluate(ctx: sessions.SessionContext, tag: str, harness: Harness, tasks: list[Task], k: int) -> Evaluation:
    """Run ``harness`` on each task ``k`` times, all at once; each trial is a key of ``rrsi_trial``, answered once."""
    instructions = instructions_of(harness)
    runs = [(task, i) for task in tasks for i in range(k)]
    results = await asyncio.gather(
        *(
            ctx.call(
                attempt,
                TrialRequest(instructions=instructions, tools=harness.tools, question=task.question),
                key=f"{ctx.key}.{tag}.{task.id}.{i}",
                idempotency_key=f"{ctx.key}.{tag}.{task.id}.{i}",
            )
            for task, i in runs
        )
    )
    rows = [(task.id, i, r.reply, reward(task, r.reply), r.cost) for (task, i), r in zip(runs, results, strict=True)]
    return Evaluation(
        score=sum(row[3] for row in rows) / len(rows), cost=sum(row[4] for row in rows) / len(rows), trials=rows
    )


rrsi = sessions.SessionObject(
    "rrsi",
    description="A search for a better harness, one key per run",
    migrations=[
        "CREATE TABLE run (id INTEGER PRIMARY KEY CHECK (id = 1), settings TEXT NOT NULL, round INTEGER NOT NULL, "
        "best REAL NOT NULL, delta REAL NOT NULL, incumbent INTEGER NOT NULL, done INTEGER NOT NULL DEFAULT 0)",
        "CREATE TABLE harnesses (id INTEGER PRIMARY KEY, body TEXT NOT NULL, round INTEGER NOT NULL, "
        "score REAL NOT NULL, cost REAL NOT NULL)",
        "CREATE TABLE trials (harness INTEGER NOT NULL, task TEXT NOT NULL, trial INTEGER NOT NULL, "
        "reply TEXT NOT NULL, reward REAL NOT NULL, cost REAL NOT NULL)",
        "CREATE TABLE rounds (t INTEGER PRIMARY KEY, score REAL NOT NULL, budget INTEGER NOT NULL, "
        "stalled INTEGER NOT NULL, feedback TEXT NOT NULL, winner INTEGER)",
        "CREATE TABLE edits (round INTEGER NOT NULL, candidate INTEGER NOT NULL, component TEXT NOT NULL, "
        "op TEXT NOT NULL, name TEXT, hypothesis TEXT NOT NULL, verdict TEXT NOT NULL, ds REAL, dc REAL, "
        "accepted INTEGER NOT NULL DEFAULT 0)",
    ],
)


async def harness_of(db: sessions.DatabaseReader, id: int) -> tuple[Harness, float, float]:
    row = await db.get("SELECT body, score, cost FROM harnesses WHERE id = ?", [id])
    assert row is not None
    return Harness.model_validate_json(str(row["body"])), float(row["score"] or 0), float(row["cost"] or 0)


@rrsi.handler
async def start(ctx: sessions.SessionContext, settings: Settings) -> dict[str, Any]:
    """Measure the noise band on the base harness, then start the rounds. Starting again does nothing."""
    if await ctx.db.get("SELECT 1 FROM run") is None:
        repeats = await asyncio.gather(
            *(evaluate(ctx, f"base{r}", BASE, EVOLVE, settings.trials) for r in range(settings.noise_repeats))
        )
        scores = [e.score for e in repeats]
        delta = max(max(scores) - min(scores), settings.min_delta)
        score, cost = sum(scores) / len(scores), sum(e.cost for e in repeats) / len(repeats)
        async with ctx.db.transaction() as tx:
            await tx.execute(
                "INSERT INTO harnesses (id, body, round, score, cost) VALUES (1, ?, -1, ?, ?)",
                [BASE.model_dump_json(), score, cost],
            )
            for r, e in enumerate(repeats):
                for task, i, reply, gained, spent in e.trials:
                    await tx.execute(
                        "INSERT INTO trials VALUES (1, ?, ?, ?, ?, ?)",
                        [task, r * settings.trials + i, reply, gained, spent],
                    )
            await tx.execute(
                "INSERT INTO run (id, settings, round, best, delta, incumbent) VALUES (1, ?, 0, ?, ?, 1)",
                [settings.model_dump_json(), score, delta],
            )
            tx.send(step, 0, key=ctx.key)  # the first round, once this commits
    return await status_of(ctx.db)


@rrsi.handler
async def step(ctx: sessions.SessionContext, t: int) -> None:
    """Round ``t``: analyze, propose, screen, evaluate, select; then commit, and send round ``t + 1``."""
    run = await ctx.db.get("SELECT settings, round, best, delta, incumbent, done FROM run")
    if run is None or run["done"] or run["round"] != t:
        return  # a round sent twice: it ran already
    s = Settings.model_validate_json(str(run["settings"]))
    best, delta, incumbent = float(run["best"] or 0), float(run["delta"] or 0), int(run["incumbent"] or 1)
    current, score, cost = await harness_of(ctx.db, incumbent)

    # The proposal side: the budget, the stall flag, untried components and prune targets.
    b = budget(t, s)
    back = await ctx.db.get("SELECT score FROM rounds WHERE t = ?", [t - s.stall_window])
    stalled = back is not None and score - float(back["score"] or 0) <= delta
    tried = {str(r["component"]) for r in await ctx.db.query("SELECT DISTINCT component FROM edits")}
    untried = [c for c in COMPONENTS if c not in tried]
    recent = await ctx.db.query(
        "SELECT component, max(ds) AS gain FROM edits WHERE ds IS NOT NULL AND round >= ? GROUP BY component",
        [t - s.prune_window],
    )
    prune = [str(r["component"]) for r in recent if float(r["gain"] or 0) <= 0]
    history = await ctx.db.query(
        "SELECT round, component, op, name, hypothesis, verdict, round(ds, 3) AS ds, accepted FROM edits "
        "ORDER BY round DESC, candidate LIMIT 30"
    )

    # The analyst explains the incumbent's failures; it sees the replies, never the answers.
    trials = await ctx.db.query("SELECT task, reply, reward FROM trials WHERE harness = ? LIMIT 20", [incumbent])
    questions = {task.id: task.question for task in EVOLVE}
    feedback = await ask(
        ctx,
        analyst,
        f"{ctx.key}.r{t}",
        f"The harness:\n{current.model_dump_json(indent=2)}\n\nIts trials (reward 1 is right, 0 wrong):\n"
        + "\n".join(f"- {questions[str(r['task'])]} -> {r['reply']!r} (reward {r['reward']})" for r in trials),
    )

    # The proposer drafts candidates, within the budget.
    tools = "\n".join(f"- {x.name}: {x.description}" for x in TOOLS.values())
    rules = [f"Each candidate has at most {b} edits."]
    if stalled and untried:
        rules.append(f"The score has stalled: at least {s.m_draft} candidate(s) must edit only {', '.join(untried)}.")
    if prune:
        rules.append(f"Recent edits to {', '.join(prune)} did not help: one candidate should remove that machinery.")
    reply = await ask(
        ctx,
        proposer,
        f"{ctx.key}.r{t}",
        f"The current harness:\n{current.model_dump_json(indent=2)}\n\nWhat goes wrong:\n{feedback}\n\n"
        f"Tools a harness can add (client_tool, by name):\n{tools}\n\n"
        f"Earlier edits, newest first (verdict, ds = score change, accepted):\n{json.dumps(history)}\n\n"
        f"Propose {s.candidates} candidates. {' '.join(rules)}\n"
        'Answer with JSON: {"candidates": [{"edits": [{"component": "prompt" | "skill" | "client_tool", '
        '"op": "set" | "add" | "remove", "name": "<skill or tool name>", "value": "<prompt or skill text>", '
        '"hypothesis": "<why it helps>"}]}]}',
    )
    try:
        proposal = Proposal.model_validate(json_in(reply))
    except (ValueError, ValidationError):
        proposal = Proposal(candidates=[])

    # The selection side: apply, screen for leakage, evaluate what passes, and keep what's admissible.
    @dataclass
    class Drafted:
        edits: list[Edit]
        harness: Harness | None = None
        verdict: str = "evaluated"
        evaluation: Evaluation | None = None

    drafted: list[Drafted] = []
    for candidate in proposal.candidates[: s.candidates]:
        d = Drafted(candidate.edits)
        try:
            if not 0 < len(candidate.edits) <= b:
                raise ValueError(f"{len(candidate.edits)} edits, the budget is {b}")
            h = current
            for edit in candidate.edits:
                h = applied(h, edit)
            d.harness = h
            if (leak := leak_of(current, h, EVOLVE)) is not None:
                d.verdict = f"guard: {leak}"
        except ValueError as error:
            d.verdict = f"invalid: {error}"
        drafted.append(d)

    async def screen(c: int, d: Drafted) -> None:
        if d.harness is None or d.verdict != "evaluated":
            return
        task_list = "\n".join(f"- {task.question}" for task in EVOLVE)
        answer = await ask(
            ctx, critic, f"{ctx.key}.r{t}.c{c}", f"The tasks:\n{task_list}\n\nThe diff:\n{diff_of(current, d.harness)}"
        )
        try:
            verdict = json_in(answer)
            if verdict.get("verdict") != "pass":
                d.verdict = f"critic: {verdict.get('reason', 'rejected')}"
        except ValueError:
            d.verdict = "critic: no verdict"

    await asyncio.gather(*(screen(c, d) for c, d in enumerate(drafted)))

    async def run_candidate(c: int, d: Drafted) -> None:
        if d.harness is not None and d.verdict == "evaluated":
            d.evaluation = await evaluate(ctx, f"r{t}c{c}", d.harness, EVOLVE, s.trials)

    await asyncio.gather(*(run_candidate(c, d) for c, d in enumerate(drafted)))

    accepted_kinds = {
        str(r["component"]) for r in await ctx.db.query("SELECT DISTINCT component FROM edits WHERE accepted = 1")
    }
    chosen: tuple[int, Evaluation] | None = None
    for c, d in enumerate(drafted):
        e = d.evaluation
        if e is None:
            continue
        ds, dc = e.score - score, (e.cost - cost) / cost
        novelty = len({x.component for x in d.edits if x.component in STRUCTURAL and x.op == "add"} - accepted_kinds)
        cost_ok = dc <= s.beta0 + s.beta1 * ds if ds > delta else s.w_s * ds - s.w_c * dc + s.w_n * novelty > 0
        if e.score >= best - delta and cost_ok:
            if chosen is None or (e.score, -e.cost) > (chosen[1].score, -chosen[1].cost):
                chosen = (c, e)
        else:
            d.verdict = "not admissible: " + ("below the best" if e.score < best - delta else "cost")
    winner = None if chosen is None else chosen[0]

    # Commit the round, and send the next one, together.
    async with ctx.db.transaction() as tx:
        new_incumbent = incumbent
        for c, d in enumerate(drafted):
            e = d.evaluation
            ds = None if e is None else round(e.score - score, 4)
            dc = None if e is None else round((e.cost - cost) / cost, 4)
            if e is not None and d.harness is not None:
                await tx.execute(
                    "INSERT INTO harnesses (body, round, score, cost) VALUES (?, ?, ?, ?)",
                    [d.harness.model_dump_json(), t, e.score, e.cost],
                )
                row = await tx.get("SELECT max(id) AS id FROM harnesses")
                harness_id = int(row["id"] or 0) if row else 0
                for task, i, reply, gained, spent in e.trials:
                    await tx.execute(
                        "INSERT INTO trials VALUES (?, ?, ?, ?, ?, ?)", [harness_id, task, i, reply, gained, spent]
                    )
                if c == winner:
                    new_incumbent = harness_id
            for edit in d.edits:
                await tx.execute(
                    "INSERT INTO edits (round, candidate, component, op, name, hypothesis, verdict, ds, dc, accepted) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [t, c, edit.component, edit.op, edit.name, edit.hypothesis, d.verdict, ds, dc, int(c == winner)],
                )
        new_score = score if chosen is None else chosen[1].score
        await tx.execute(
            "INSERT INTO rounds (t, score, budget, stalled, feedback, winner) VALUES (?, ?, ?, ?, ?, ?)",
            [t, score, b, int(stalled), feedback, winner],
        )
        done = t + 1 >= s.rounds
        await tx.execute(
            "UPDATE run SET round = ?, best = ?, incumbent = ?, done = ?",
            [t + 1, max(best, new_score), new_incumbent, int(done)],
        )
        if not done:
            tx.send(step, t + 1, key=ctx.key)


async def status_of(db: sessions.DatabaseReader) -> dict[str, Any]:
    run = await db.get("SELECT round, best, delta, incumbent, done FROM run")
    if run is None:
        return {"started": False}
    harness, score, cost = await harness_of(db, int(run["incumbent"] or 1))
    _, base_score, base_cost = await harness_of(db, 1)
    rounds = await db.query("SELECT t, round(score, 3) AS score, budget, stalled, winner FROM rounds ORDER BY t")
    return {
        "started": True,
        "round": run["round"],
        "done": bool(run["done"]),
        "delta": run["delta"],
        "base": {"score": base_score, "cost": round(base_cost)},
        "incumbent": {"score": score, "cost": round(cost), "harness": harness.model_dump()},
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
        "SELECT round, candidate, component, op, name, hypothesis, verdict, ds, dc, accepted FROM edits "
        "ORDER BY round, candidate"
    )


@rrsi.handler
async def held_out(ctx: sessions.SessionContext) -> dict[str, float]:
    """Run the base harness and the incumbent on the held-out tasks, which selection never saw."""
    run = await ctx.db.get("SELECT settings, incumbent FROM run")
    if run is None:
        raise restate.TerminalError("Not started")
    k = Settings.model_validate_json(str(run["settings"])).trials
    incumbent = int(run["incumbent"] or 1)
    final, _, _ = await harness_of(ctx.db, incumbent)
    base, last = await asyncio.gather(
        evaluate(ctx, "heldout.base", BASE, HELD_OUT, k), evaluate(ctx, f"heldout.h{incumbent}", final, HELD_OUT, k)
    )
    return {"base": base.score, "incumbent": last.score}


services = [rrsi, trial, analyst, proposer, critic]
