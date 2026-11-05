"""The harness: what the policy runs with, the edits that change it, and the tools it can give the policy."""

import ast
import difflib
import json
from collections.abc import Callable
from typing import Literal

import restate
from pydantic import BaseModel
from restate.agents import tool

Component = Literal["prompt", "skill", "client_tool"]
COMPONENTS: tuple[Component, ...] = ("prompt", "skill", "client_tool")

STRUCTURAL: frozenset[Component] = frozenset({"skill", "client_tool"})
"""The components whose first accepted use counts as novelty (the paper's nu)."""


class Harness(BaseModel):
    """A system prompt, named skills (instructions appended to it), and tools from ``TOOLS``."""

    system: str
    skills: dict[str, str] = {}
    tools: list[str] = []

    def instructions(self) -> str:
        skills = [f"Skill ({name}): {text}" for name, text in sorted(self.skills.items())]
        return "\n\n".join([self.system, *skills])


BASE = Harness(system="Answer the question.")


class Edit(BaseModel):
    """One atomic edit to a harness, with the hypothesis behind it."""

    component: Component
    op: Literal["set", "add", "remove"]
    name: str | None = None  # the skill's or the tool's name
    value: str | None = None  # the prompt's or the skill's text
    hypothesis: str = ""


class Candidate(BaseModel):
    edits: list[Edit]


class Proposal(BaseModel):
    """What the proposer answers with."""

    candidates: list[Candidate]


def apply_edit(harness: Harness, edit: Edit) -> Harness:
    """Return a copy of ``harness`` with ``edit`` applied; raise ``ValueError`` if it doesn't apply."""
    h = harness.model_copy(deep=True)
    match edit.component, edit.op:
        case "prompt", "set" if edit.value:
            h.system = edit.value
        case "prompt", "add" if edit.value:
            h.system = f"{h.system}\n{edit.value}"
        case "prompt", "remove" if edit.value and edit.value in h.system:
            h.system = h.system.replace(edit.value, "").strip()
        case "skill", "add" | "set" if edit.name and edit.value:
            h.skills[edit.name] = edit.value
        case "skill", "remove" if edit.name in h.skills:
            del h.skills[edit.name]
        case "client_tool", "add" if edit.name in TOOLS and edit.name not in h.tools:
            h.tools.append(edit.name)
        case "client_tool", "remove" if edit.name in h.tools:
            h.tools.remove(edit.name)
        case _:
            raise ValueError(f"does not apply: {edit.component} {edit.op} {edit.name or edit.value!r}")
    return h


def apply_edits(harness: Harness, edits: list[Edit]) -> Harness:
    for edit in edits:
        harness = apply_edit(harness, edit)
    return harness


def diff(old: Harness, new: Harness) -> str:
    """A unified diff of the two harnesses, as JSON: what the critic reads."""

    def lines(h: Harness) -> list[str]:
        return json.dumps(h.model_dump(), indent=2).splitlines()

    return "\n".join(difflib.unified_diff(lines(old), lines(new), "incumbent", "candidate", lineterm=""))


def added_text(old: Harness, new: Harness) -> str:
    """The lines that ``new`` adds to ``old``."""
    added = [line[1:] for line in diff(old, new).splitlines() if line.startswith("+") and not line.startswith("+++")]
    return "\n".join(added)


# --- The tools ---------------------------------------------------------------------------------------

_OPERATORS: dict[type[ast.operator], Callable[[float, float], float]] = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
}


def arithmetic(expression: str) -> float:
    """The value of an expression of numbers, + - * / and parentheses; ``TerminalError`` for anything else."""

    def value(node: ast.expr) -> float:
        if isinstance(node, ast.Constant) and isinstance(node.value, int | float):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _OPERATORS:
            return _OPERATORS[type(node.op)](value(node.left), value(node.right))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return -value(node.operand)
        raise restate.TerminalError("Only numbers, + - * / and parentheses")

    try:
        return value(ast.parse(expression, mode="eval").body)
    except SyntaxError as error:
        raise restate.TerminalError(f"Not an expression: {error.msg}") from error


@tool
def calculator(expression: str) -> str:
    """Evaluate an arithmetic expression: numbers, + - * / and parentheses."""
    result = arithmetic(expression)
    return str(int(result)) if float(result).is_integer() else f"{result:g}"


@tool
def count_letter(text: str, letter: str) -> int:
    """Count how many times a letter appears in a text (ignoring case)."""
    return text.lower().count(letter.lower())


TOOLS = {t.name: t for t in (calculator, count_letter)}
