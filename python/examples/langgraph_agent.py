"""
The same agent on LangGraph

A durable chat agent on LangGraph: a tool-calling graph whose checkpoints
live in the object's SQL database.

Each key is a thread of its own. If the process dies mid-reply, Restate
retries the call and the graph carries on from its last step::

    uv run python -m restate serve examples.langgraph_agent:app
    curl localhost:8080/langgraph/alice/chat -d 'Hi, I am Alice. Is it warm in Lisbon?'
    curl localhost:8080/langgraph/alice/messages
"""

import restate
from restate.agents import langgraph, tool


# A tool, for any framework's agent (the framework's own tools work too).
@tool
async def get_weather(city: str) -> str:
    """The current weather in a city."""
    return f"Sunny and 21°C in {city}"  # a stand-in for a real weather API


# The model defaults to "openai/gpt-6-sol" (or $RESTATE_AGENT_MODEL), through langchain-openai.
assistant = langgraph.agent("langgraph", system="Keep your answers short.", tools=[get_weather])

app = restate.app([assistant])
