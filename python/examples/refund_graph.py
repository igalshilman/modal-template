"""
A graph of your own

A refund desk you chat with, as a LangGraph graph of your own whose steps are
Restate's: a clerk agent reads the request into a ``Refund``, a manager
approves it (a signal), and a workflow pays it out. Each step happens once,
even if the process crashes in the middle, and the wait for approval holds no
process, for as long as it takes::

    uv run python -m restate serve examples.refund_graph:app
    curl localhost:8080/refund_desk/alice/chat/send -d 'Order 103 arrived broken, I want my $30 back.'
    curl localhost:8080/refund_desk/alice/pending   # the refund it waits to approve
    curl localhost:8080/refund_desk/alice/signal --json '{"name": "approval", "value": "approved"}'
    curl localhost:8080/refund_desk/alice/messages  # the answer: the payout's receipt

Any other value rejects the refund. The clerk is an agent of its own, on the
OpenAI Agents SDK, that answers with data: ``output=Refund`` makes its ``chat``
answer with a ``Refund``'s JSON, rather than text::

    curl localhost:8080/clerk/bob/chat -d 'I paid $12 for order 7, and want it back.'   # {"order":"7","amount":12.0}
"""

# LangGraph's StateGraph has types that pyright's strict mode doesn't see whole.
# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false

from typing import Any, NotRequired

import restate
from langchain_core.messages import AIMessage
from langgraph.graph import END, START, MessagesState, StateGraph
from pydantic import BaseModel
from restate.agents import langgraph, openai
from restate.agents.langgraph import nodes


class Refund(BaseModel):
    order: str
    amount: float


# The payout, a workflow: it runs once per order.
payouts = restate.Workflow("payouts")


@payouts.main()
async def pay(ctx: restate.WorkflowContext, refund: Refund) -> str:
    return f"Refunded ${refund.amount:.2f} for order {refund.order}."


clerk = openai.agent("clerk", system="Read the refund request: which order, and how much.", output=Refund)


class Desk(MessagesState):
    """The graph's state: the conversation (LangGraph's messages), and what each step wrote."""

    refund: NotRequired[dict[str, Any]]
    approval: NotRequired[str]
    receipt: NotRequired[str]


def request(state: Desk) -> str:
    """The user's message, for the clerk."""
    return str(state["messages"][-1].text)


def refund_of(state: Desk) -> dict[str, Any]:
    return state.get("refund", {})


def order_of(state: Desk) -> str:
    """The payout's workflow id: one payout per order, however often it is asked for."""
    return str(refund_of(state)["order"])


def approved(state: Desk) -> str:
    return "pay" if state.get("approval") == "approved" else "answer"


def answer(state: Desk) -> dict[str, list[AIMessage]]:
    if state.get("approval") != "approved":
        return {"messages": [AIMessage("The refund was not approved.")]}
    return {"messages": [AIMessage(state.get("receipt", ""))]}


graph = StateGraph(Desk)
# Prebuilt nodes that are Restate steps: each reads its input from the state, and writes its result to `output`.
graph.add_node("read", nodes.subagent(clerk, message=request, output="refund"))
graph.add_node("approve", nodes.wait_for_signal("approval", input=refund_of, output="approval"))
graph.add_node("pay", nodes.workflow(pay, input=refund_of, key=order_of, output="receipt"))
graph.add_node("answer", answer)
graph.add_edge(START, "read")
graph.add_edge("read", "approve")
graph.add_conditional_edges("approve", approved, ["pay", "answer"])
graph.add_edge("pay", "answer")
graph.add_edge("answer", END)

# An agent whose `chat` runs the graph: each key's database keeps its checkpoints and its conversation.
refund_desk = langgraph.agent("refund_desk", graph=graph)

app = restate.app([payouts, clerk, refund_desk])
