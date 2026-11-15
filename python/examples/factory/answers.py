"""
The planner's answer, structured: a ``Plan``, which ``openai.prompt(..., output=Plan)``
asks the model for, and returns checked. The descriptions of its fields are the
model's instructions for each.
"""

from typing import Annotated

from pydantic import BaseModel, Field


class Issue(BaseModel):
    """What the planner plans from: an issue's title and description."""

    title: str
    description: str


class Part(BaseModel):
    name: Annotated[str, Field(pattern=r"^[a-z0-9-]+$", description='A short name, such as "parser"')]
    title: Annotated[str, Field(description="The part, in a line: the title of its sub-issue")]
    description: Annotated[
        str, Field(description="The part, for the people following the issue: two or three plain sentences")
    ]
    files: Annotated[list[str], Field(description="The files the part owns: no other part changes them")]
    task: Annotated[str, Field(description="What to build, in full: its coder sees nothing else")]


class Plan(BaseModel):
    """A plan the parent can act on, part by part."""

    summary: Annotated[
        str, Field(description="What will be built, and how its parts fit together: a short paragraph, for people")
    ]
    parts: Annotated[list[Part], Field(min_length=1, description="Parts that can be built at the same time")]
