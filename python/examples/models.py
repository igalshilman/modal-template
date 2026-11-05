"""
Models you set up yourself

Agents on models you set up yourself: LangChain chat models of your own, for
LangGraph agents. Any LangChain chat model that calls tools works the same.

- ``precise``: the client takes a gateway's address, if you have one
  (OPENAI_BASE_URL), and makes no retries of its own: when the API fails, the
  attempt fails, and Restate retries it, resuming the conversation from the
  agent's database. Its replies are short (``max_completion_tokens``).
- ``creative``: a model of its own settings, here a high temperature.

::

    uv run python -m restate serve examples.models:app
    curl localhost:8080/precise/alice/chat -d 'Name a color.'
    curl localhost:8080/creative/alice/chat -d 'Name a color.'
"""

import os

import restate
from langchain_openai import ChatOpenAI
from restate.agents import langgraph

precise = langgraph.agent(
    "precise",
    model=ChatOpenAI(
        model="gpt-6-sol", base_url=os.environ.get("OPENAI_BASE_URL"), max_retries=0, max_completion_tokens=512
    ),
    system="Answer in as few words as you can.",
)

creative = langgraph.agent(
    "creative",
    model=ChatOpenAI(model="gpt-6-sol", temperature=1),
    system="Answer with imagination.",
)

app = restate.app([precise, creative])
