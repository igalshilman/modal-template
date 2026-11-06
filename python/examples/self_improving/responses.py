"""
OpenAI's Responses API, for an agent loop of your own: the model's calls, and
the conversation's items as the loop stores them.

This is the plumbing a framework would otherwise hide; ``agent.py`` is the agent.
"""

import functools
import json
import os
from collections.abc import Sequence
from typing import Any, cast

import restate
from openai import AsyncOpenAI
from openai.types.responses import ResponseInputParam
from pydantic import BaseModel
from restate.agents import Tool
from restate.agents.internal import Call, Parsed, Result

MODEL = os.environ.get("RESTATE_AGENT_MODEL", "openai/gpt-6-sol").removeprefix("openai/")

Item = dict[str, Any]
"""An item of the conversation, as the Responses API has it: a message, a tool call, its output, reasoning…"""


@functools.cache
def client() -> AsyncOpenAI:
    return AsyncOpenAI()


async def complete(instructions: str, items: list[Item], tools: Sequence[Tool]) -> list[Item]:
    """Ask the model to go on from ``items``, and return its reply: text, tool calls, reasoning."""
    response = await client().responses.create(
        model=MODEL,
        instructions=instructions,
        input=cast(ResponseInputParam, items),  # the items, stored as plain dicts
        tools=[
            {
                "type": "function",
                "name": t.name,
                "description": t.description,
                "parameters": t.input_schema,
                "strict": False,
            }
            for t in tools
        ],
        # The conversation is kept in Restate, not by OpenAI: each reasoning item carries its own (encrypted) content.
        store=False,
        include=["reasoning.encrypted_content"],
    )
    return [item.model_dump(exclude_none=True, by_alias=True) for item in response.output]


async def parse[T: BaseModel](instructions: str, text: str, answer: type[T]) -> T:
    """Ask the model once, for an answer of the shape ``answer``, checked against it."""
    response = await client().responses.parse(
        model=MODEL, instructions=instructions, input=text, text_format=answer, store=False
    )
    if response.output_parsed is None:
        raise restate.TerminalError("The model gave no answer")
    return response.output_parsed


def calls_tools(reply: list[Item]) -> bool:
    return any(item.get("type") == "function_call" for item in reply)


def output(call_id: str, text: str) -> Item:
    """The item that gives tool call ``call_id`` its output."""
    return {"type": "function_call_output", "call_id": call_id, "output": text}


class Items:
    """How the conversation stores, reads and makes these items (``restate.agents.internal.Items``)."""

    def dump(self, item: Item) -> str:
        return json.dumps(item)

    def load(self, stored: str) -> Item:
        return json.loads(stored)

    def prompt(self, text: str) -> Item:
        return {"role": "user", "content": text}

    def reply(self, text: str) -> Item:
        return {"role": "assistant", "content": text}

    def results(self, results: Sequence[tuple[Call, str]]) -> list[Item]:
        return [output(call.id, text) for call, text in results]

    def read(self, item: Item) -> Parsed:
        match item.get("type", "message"):
            case "message":
                return Parsed(said=(item["role"], _text(item["content"])))
            case "function_call":
                return Parsed(calls=[Call(item["call_id"], item["name"], _arguments(item["arguments"]))])
            case "function_call_output":
                return Parsed(results=[Result(item["call_id"], item["output"])])
            case _:  # the model's reasoning, say
                return Parsed()


def _text(content: str | list[Item]) -> str:
    """A message's text: a string, or the text of its parts."""
    return content if isinstance(content, str) else "".join(str(part.get("text", "")) for part in content)


def _arguments(arguments: str) -> Any:
    try:
        return json.loads(arguments)
    except ValueError:
        return {}  # the tool then tells the model that its arguments don't fit
