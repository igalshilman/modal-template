"""
Linear's webhook, into triage: which issue an event is for. The events: a new
issue (not a sub-issue, which triage makes itself), and a person's comment on
one. The agents' own comments are dropped (signatures.py). Linear's events:
https://linear.app/developers/webhooks
"""

from typing import Any

from restate.agents import Event

from examples.factory.signatures import by_an_agent


def issue_of(event: Event) -> str | None:
    """The issue a Linear event is for (its triage's key, ``ENG-1``), or None to drop it."""
    if event.get("action") != "create":
        return None
    data: dict[str, Any] = event.get("data") or {}
    if event.get("type") == "Issue" and not data.get("parentId"):
        return data.get("identifier")
    if event.get("type") == "Comment" and not by_an_agent(str(data.get("body") or "")):
        issue: dict[str, Any] = data.get("issue") or {}
        return issue.get("identifier")
    return None
