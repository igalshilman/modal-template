"""The models of the search: the policy that runs a harness, and the analyst, proposer and critic.

Each is an agent object, and each conversation is a key of its own: a trial per key, and a
conversation of a role per round (and per candidate, for the critic). Every call to one has an
idempotency key made of that key, so a retried round gets the answers it got the first time.
"""

import json
from typing import Any

from pydantic import BaseModel
from restate import sessions
from restate.agents import AgentObject, openai

from .harness import TOOLS, Harness
from .tasks import QUESTIONS, Task

# --- The policy --------------------------------------------------------------------------------------


class TrialRequest(BaseModel):
    instructions: str
    tools: list[str]
    question: str


class TrialResult(BaseModel):
    reply: str
    cost: float


trial = AgentObject("rrsi_trial", description="One trial of a harness on a task", background=True)


@trial.handler
async def attempt(ctx: sessions.SessionContext, request: TrialRequest) -> TrialResult:
    tools = [TOOLS[name] for name in request.tools if name in TOOLS]
    reply = await openai.prompt(ctx, request.question, system=request.instructions, tools=tools)
    # An estimate of the tokens: the text in and out, and each tool's schema.
    cost = (len(request.instructions) + len(request.question) + len(reply)) / 4 + 60 * len(request.tools)
    return TrialResult(reply=reply, cost=cost)


async def run_trial(ctx: sessions.SessionContext, key: str, harness: Harness, task: Task) -> TrialResult:
    """Run ``harness`` on ``task``, as the trial ``key``: once, however often the caller is retried."""
    request = TrialRequest(instructions=harness.instructions(), tools=harness.tools, question=task.question)
    return await ctx.call(attempt, request, key=key, idempotency_key=key)


# --- The roles of the search ---------------------------------------------------------------------------

analyst = openai.agent(
    "rrsi_analyst",
    background=True,
    system=(
        "You analyze an agent's failures. Given its harness and its trials, say in a few short bullet points "
        "what kinds of mistakes it makes and what generic change to its harness might fix them. "
        "Never repeat answers."
    ),
)

proposer = openai.agent(
    "rrsi_proposer",
    background=True,
    system=(
        "You improve an agent's harness: its system prompt, its skills (named instructions) and its tools. "
        "You propose candidate edits as JSON, and nothing else. "
        "Edits must be generic improvements: never a task's answer, its numbers or its text."
    ),
)

critic = openai.agent(
    "rrsi_critic",
    background=True,
    system=(
        "You screen edits to an agent's harness for leakage before they are evaluated. "
        "Reject an edit that carries a task's name, answer or task-specific values, "
        "or that adds machinery that does nothing. Pass generic improvements. "
        'Answer with JSON only: {"verdict": "pass" or "reject", "reason": "..."}.'
    ),
)


async def ask(ctx: sessions.SessionContext, role: AgentObject, key: str, text: str) -> str:
    """Ask ``role``, in its conversation ``key``: once, however often the caller is retried."""
    answer = await ctx.generic_call(role.name, "chat", text, key=key, idempotency_key=f"{role.name}/{key}")
    return str(answer)


def json_in(text: str) -> Any:
    """The JSON object in a model's reply, which may wrap it in prose or a code fence."""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("no JSON object")
    return json.loads(text[start : end + 1])


# --- Their prompts -----------------------------------------------------------------------------------

PROPOSAL_FORMAT = (
    '{"candidates": [{"edits": [{"component": "prompt" | "skill" | "client_tool", '
    '"op": "set" | "add" | "remove", "name": "<skill or tool name>", "value": "<prompt or skill text>", '
    '"hypothesis": "<why it helps>"}]}]}'
)


def analyst_prompt(harness: Harness, trials: list[sessions.Row]) -> str:
    """The incumbent and its trials: the questions and replies, never the answers."""
    outcomes = [f"- {QUESTIONS[str(r['task'])]} -> {r['reply']!r} (reward {r['reward']})" for r in trials]
    return "\n".join(
        [
            "The harness:",
            harness.model_dump_json(indent=2),
            "",
            "Its trials (reward 1 is right, 0 wrong):",
            *outcomes,
        ]
    )


def proposer_prompt(harness: Harness, feedback: str, history: list[sessions.Row], count: int, rules: list[str]) -> str:
    tools = [f"- {t.name}: {t.description}" for t in TOOLS.values()]
    return "\n".join(
        [
            "The current harness:",
            harness.model_dump_json(indent=2),
            "",
            "What goes wrong:",
            feedback,
            "",
            "Tools a harness can add (client_tool, by name):",
            *tools,
            "",
            "Earlier edits, newest first (verdict, ds = score change, accepted):",
            json.dumps(history),
            "",
            f"Propose {count} candidates. {' '.join(rules)}",
            f"Answer with JSON: {PROPOSAL_FORMAT}",
        ]
    )


def critic_prompt(tasks: list[Task], diff: str) -> str:
    return "\n".join(["The tasks:", *(f"- {task.question}" for task in tasks), "", "The diff:", diff])
