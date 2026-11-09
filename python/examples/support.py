"""
Restate as tools

A support agent whose tools are Restate itself: it looks orders up with a
plain service, waits for a manager's approval (a signal), and refunds with a
workflow. Every step is durable: a crash, or a manager who takes a day,
changes nothing::

    uv run python -m restate serve examples.support:app
    curl localhost:8080/support/alice/chat/send -d 'Order 103 arrived broken, can I get my $30 back?'

The agent waits for approval. See what it waits for (the refund, with the
wait's id). Meanwhile, add to what you asked: a message sent to ``steer``
joins the turn being answered at its next step (here, once the approval
came), and the answer covers it too. Then approve the refund::

    curl localhost:8080/support/alice/pending
    curl localhost:8080/support/alice/steer -H 'idempotency-key: m1' -d 'And where is order 104?'
    curl localhost:8080/support/alice/signal --json '{"name": "approval", "value": "approved"}'
    curl localhost:8080/support/alice/messages   # the refund, your second message, and the answer to both

``/send`` sends the message without waiting for the answer, which waits for
the approval. ``{"id": "<the id>", "value": ...}`` answers one wait by its id.
A message sent to ``steer`` when no step is left (or no turn is being
answered) is answered as a turn of its own, in order: either way, once. Its
idempotency key makes a retried request the same message.

Or all of it from a terminal: ``uv run python -m restate.agents chat support/alice``,
then ``/pending``, ``/steer And where is order 104?`` and ``/signal approval approved``
while the agent waits.
"""

from datetime import timedelta

import restate
from pydantic import BaseModel
from restate.agents import call, openai, wait_for_signal, workflow


class Order(BaseModel):
    order: str


class Refund(BaseModel):
    order: str
    amount: float


# A plain Restate service: a journaled handler.
orders = restate.Service("orders")


@orders.handler()
async def status(ctx: restate.Context, req: Order) -> str:
    return f"Order {req.order} was delivered yesterday."


# A workflow: a refund runs to the end, once per id, however long it takes.
refund = restate.Workflow("refund")


@refund.main()
async def run(ctx: restate.WorkflowContext, req: Refund) -> str:
    await ctx.sleep(timedelta(seconds=5))  # a stand-in for the payment provider: a durable timer
    return f"Refunded ${req.amount:.2f} for order {req.order}."


support = openai.agent(
    "support",
    system="You are a support agent. Keep your answers short.",
    tools=[
        call(status, description="The status of an order."),
        wait_for_signal(
            "approval",
            description="Wait for a manager to decide on a refund. Answers with the manager's decision.",
            input=Refund,
        ),
        workflow(run, description="Refund an order. Only once a manager approved it."),
    ],
)

app = restate.app([orders, refund, support])
