"""The tasks: an evolve set that selection scores on, and a held-out set that checks transfer."""

import re
from dataclasses import dataclass

from .harness import Harness, added_text, arithmetic


@dataclass(frozen=True)
class Task:
    id: str
    question: str
    answer: str
    subject: str  # the task-specific text that must not show up in a harness


def arithmetic_task(id: str, expression: str) -> Task:
    return Task(id, f"What is {expression}?", answer=str(int(arithmetic(expression))), subject=expression)


def letters_task(id: str, text: str, letter: str) -> Task:
    question = f"How many times does the letter {letter} appear in '{text}'?"
    return Task(id, question, answer=str(text.count(letter)), subject=text)


EVOLVE = [
    arithmetic_task("mul", "347 * 29"),
    arithmetic_task("sum", "1234 + 5678 + 91011"),
    arithmetic_task("mixed", "7 * 8 * 9 - 123"),
    letters_task("berries", "strawberry raspberry", "r"),
    letters_task("banana", "banana bandana", "a"),
]

HELD_OUT = [
    arithmetic_task("mul2", "613 * 47"),
    arithmetic_task("mixed2", "12 * 13 * 14 - 999"),
    letters_task("mississippi", "mississippi missouri", "s"),
]

QUESTIONS = {task.id: task.question for task in EVOLVE + HELD_OUT}


def reward(task: Task, reply: str) -> float:
    """1 if the last number in the reply is the answer, else 0."""
    numbers = re.findall(r"-?\d[\d,]*", reply)
    return 1.0 if numbers and numbers[-1].replace(",", "") == task.answer else 0.0


MAX_INSTRUCTIONS = 4000


def leak(old: Harness, new: Harness, tasks: list[Task]) -> str | None:
    """The deterministic leakage guard: why ``new`` must not be evaluated, or ``None`` if it may.

    It rejects an edit that adds a task's answer (as a number of its own) or its subject, and a
    harness whose instructions grow past ``MAX_INSTRUCTIONS``.
    """
    added = added_text(old, new)
    for task in tasks:
        answer = rf"(?<![\d.]){re.escape(task.answer)}(?![\d.])"
        if re.search(answer, added) or task.subject in added:
            return f"carries task {task.id}'s answer or subject"
    if len(new.instructions()) > MAX_INSTRUCTIONS:
        return f"instructions over {MAX_INSTRUCTIONS} characters"
    return None
