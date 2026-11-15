"""
The agents' signatures. They all write as one user, in Linear and on GitHub,
so what each one writes opens with its name and its part
(``**🛠️ Coder · parser**``). That is also how the factory tells their comments
from people's: the agents' own comments come back as webhooks too, and are not
for them.
"""

from collections.abc import Callable

TRIAGE = "🧭 Triage"
CODER = "🛠️ Coder"
REVIEWER = "🔍 Reviewer"

WRITERS = (TRIAGE, CODER, REVIEWER)
"""The agents that write, by the name they sign with."""


def signer(who: str) -> Callable[[str, str], str]:
    """The signature of ``who``: ``sign(key, text)`` is ``text``, opening with its name, and its task's part, if any.

    The part is the second half of the agent's key: ``coder/ENG-1.parser`` signs as "🛠️ Coder · parser".
    """

    def sign(key: str, text: str) -> str:
        _, _, part = key.partition(".")
        return f"**{who}{f' · {part}' if part else ''}**\n\n{text}"

    return sign


def by_an_agent(text: str) -> bool:
    """Whether ``text``, a comment's body, is an agent's: it opens with a signature."""
    opening = text.lstrip().removeprefix("**")
    return any(opening.startswith(who) for who in WRITERS)
