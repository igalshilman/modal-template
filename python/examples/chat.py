"""
A chat agent

A durable chat agent on the OpenAI Agents SDK.

Each key is a conversation of its own (``chatbot/alice``, ``chatbot/bob``),
kept in the object's SQL database. If the process dies mid-reply, Restate
retries the call and the agent picks up where it left off::

    uv run python -m restate serve examples.chat:app
    curl localhost:8080/chatbot/alice/chat -d 'Hi, I am Alice. Is it warm in Lisbon?'
    curl localhost:8080/chatbot/alice/chat -d 'What is my name?'
    curl localhost:8080/chatbot/alice/messages   # the conversation so far
    curl localhost:8080/chatbot/alice/clear      # forget it: the next message starts anew

Or chat from a terminal: ``uv run python -m restate.agents chat chatbot/alice``.
"""

import restate
from restate.agents import openai, tool


# A tool, for any framework's agent (the framework's own tools work too).
@tool
async def get_weather(city: str) -> str:
    """The current weather in a city."""
    return f"Sunny and 21°C in {city}"  # a stand-in for a real weather API


chatbot = openai.agent("chatbot", system="You are a helpful assistant. Keep your answers short.", tools=[get_weather])

app = restate.app([chatbot])
