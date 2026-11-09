"""
The same agent on LangGraph

A durable chat agent on LangGraph: a tool-calling graph whose checkpoints
live in the object's SQL database.

Each key is a thread of its own. If the process dies mid-reply, Restate
retries the call and the graph carries on from its last step::

    uv run python -m restate serve examples.langgraph_agent:app
    curl localhost:8080/langgraph/alice/chat -d 'Hi, I am Alice. Is it warm in Lisbon?'
    curl localhost:8080/langgraph/alice/messages

Or bring a graph of your own, such as LangChain's ``create_agent`` makes,
with the same tool (``langgraph.tools`` makes LangChain tools of this
package's tools)::

    curl localhost:8080/langchain/alice/chat -d 'Is it warm in Lisbon?'

A graph of your own is durable a step at a time: a crash runs the step it
cut off again, and its tools' Restate calls are made once. It takes no
steered messages: one sent to ``steer`` is answered as a turn of its own,
after the one being answered.
"""

import restate
from langchain.agents import create_agent  # pyright: ignore[reportUnknownVariableType] (its types are partly unknown)
from restate.agents import langgraph, tool


# A tool, for any framework's agent (the framework's own tools work too).
@tool
async def get_weather(city: str) -> str:
    """The current weather in a city."""
    return f"Sunny and 21°C in {city}"  # a stand-in for a real weather API


# The model defaults to "openai/gpt-6-sol" (or $RESTATE_AGENT_MODEL), through langchain-openai.
assistant = langgraph.agent("langgraph", system="Keep your answers short.", tools=[get_weather])

# Any graph built on LangGraph's MessagesState: its checkpoints live in the key's database too.
graph: langgraph.AnyGraph = create_agent(
    "openai:gpt-6-sol", tools=langgraph.tools([get_weather]), system_prompt="Keep your answers short."
)
langchain_agent = langgraph.agent("langchain", graph=graph)

app = restate.app([assistant, langchain_agent])
