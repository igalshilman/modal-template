"""
The software factory: four agents, and the two webhooks that start them.

    Linear ──webhook──▶ triage ──call──────▶ planner
                               ──subagent──▶ coder ◀──webhook── GitHub
                               ──subagent──▶ reviewer

Each agent is keyed by its task: triage and the planner by the issue
(``triage/ENG-1``), a coder and its reviewer by the issue's part
(``coder/ENG-1.parser``). How it all works: README.md.
"""

from datetime import timedelta

import restate
from restate import sessions
from restate.agents import AgentContext, Tool, call, openai, pydantic_ai, subagent, webhook

from examples.factory import env, github, linear, prompts
from examples.factory.answers import Issue, Plan
from examples.factory.signatures import CODER, REVIEWER, TRIAGE
from examples.factory.tools import (
    bash,
    comment_on_pull_request,
    linear_tools,
    open_pull_request,
    pull_request_diff,
    read_own_file,
    read_pushed_file,
    write_file,
)

# --- Triage: leads the work on an issue -----------------------------------------------------------------


async def triage_tools(ctx: sessions.SessionContext) -> list[Tool]:
    return [
        *await linear_tools(TRIAGE),
        call(plan, description="Plan the work on an issue: a summary, and its parts", key=lambda ctx: ctx.key),
        subagent(coder),
        subagent(reviewer),
    ]


triage = openai.agent("triage", system=prompts.TRIAGE, tools=triage_tools)


# --- The planner: plans an issue, as a Plan ---------------------------------------------------------------

planner = openai.agent(
    "planner",
    description="Plans the work on an issue, from its title and description: a summary, and parts to build at once",
    system=prompts.PLANNER,
)


@planner.handler
async def plan(ctx: AgentContext, issue: Issue) -> Plan:
    """Plan the work on an issue, as a ``Plan``: asked once, in the planner's conversation for the issue.

    A retry of the handler gets the same plan, without asking the model again.
    """
    return await openai.prompt(ctx, f"# {issue.title}\n\n{issue.description}", system=prompts.PLANNER, output=Plan)


# --- A coder: builds a part, in its own clone, and opens its pull request -----------------------------------


async def coder_tools(ctx: sessions.SessionContext) -> list[Tool]:
    return [
        bash,
        read_own_file,
        write_file,
        open_pull_request(CODER),
        comment_on_pull_request(CODER),
        *await linear_tools(CODER),
    ]


coder = pydantic_ai.agent(
    "coder",
    description="Builds a part of the plan, on a branch of its own, and opens its pull request; answers its reviews",
    model=env.CODER_MODEL,
    system=prompts.CODER,
    tools=coder_tools,
    inactivity_timeout=timedelta(minutes=10),  # a coder's commands (tests, builds) can take minutes
)


# --- A reviewer: reviews a coder's pull request, as pushed ----------------------------------------------

reviewer = openai.agent(
    "reviewer",
    description="Reviews a pull request, as pushed, and posts its review on it: approved, or the changes to make",
    system=prompts.REVIEWER,
    tools=[pull_request_diff, read_pushed_file, comment_on_pull_request(REVIEWER)],
)


# --- The webhooks: Linear's into triage, GitHub's into the coders --------------------------------------------

linear_webhook = webhook(
    "linear",
    description="Linear's new issues, and comments on them, to triage",
    route=[triage],
    key=linear.issue_of,
    secret=env.LINEAR_WEBHOOK_SECRET,
    signature_header="linear-signature" if env.LINEAR_WEBHOOK_SECRET else None,  # unsigned deliveries are taken
    idempotency_header="linear-delivery",
)

github_webhook = webhook(
    "github",
    description="GitHub's comments, reviews and failed CI runs on the coders' pull requests, to their coders",
    route=[coder],
    key=github.coder_of,
    message=github.what_happened,
    secret=env.GITHUB_WEBHOOK_SECRET,
    signature_header="x-hub-signature-256" if env.GITHUB_WEBHOOK_SECRET else None,
    idempotency_header="x-github-delivery",
)

app = restate.app([linear_webhook, github_webhook, triage, planner, coder, reviewer])
