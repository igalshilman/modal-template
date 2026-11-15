"""
GitHub's webhook, into the coders: which coder an event on a pull request is
for, and what of it the coder reads. The events: a comment on a pull request
(in its conversation, or on a line of its code), a review, and a CI run that
failed. The agents' own comments are dropped (signatures.py). GitHub's events:
https://docs.github.com/en/webhooks/webhook-events-and-payloads
"""

import re
from typing import Any

from restate.agents import Event

from examples.factory.signatures import by_an_agent
from examples.factory.workspace import coder_of_branch


def pull_request_mark(key: str) -> str:
    """The mark of the coder ``key`` (``ENG-1.parser``), hidden at the end of its pull request's description.

    A comment's event has the pull request's description, not its branch.
    """
    return f"<!-- coder: {key} -->"


def _marked_in(pull_request: dict[str, Any] | None) -> str | None:
    found = re.search(r"<!-- coder: ([\w.-]+) -->", str((pull_request or {}).get("body") or ""))
    return found[1] if found else None


def coder_of(event: Event) -> str | None:
    """The coder an event is for (its key, ``ENG-1.parser``), or None to drop it.

    A person's new comment on a coder's pull request, or review of it; or a CI run on its branch that failed.
    """
    action = event.get("action")
    issue: dict[str, Any] = event.get("issue") or {}
    # A comment on a pull request comes as a comment on an issue: one that is a pull request.
    pull_request = event.get("pull_request") or (issue if issue.get("pull_request") else None)
    comment: dict[str, Any] | None = event.get("comment")
    review: dict[str, Any] | None = event.get("review")
    run: dict[str, Any] | None = event.get("workflow_run")
    if comment and action == "created" and not by_an_agent(str(comment.get("body") or "")):
        return _marked_in(pull_request)
    # A review with no text, only comments on lines, comes as those comments too.
    if (
        review
        and action == "submitted"
        and (review.get("body") or review.get("state") != "commented")
        and not by_an_agent(str(review.get("body") or ""))
    ):
        return _marked_in(pull_request)
    if run and action == "completed" and run.get("conclusion") == "failure":
        return coder_of_branch(str(run.get("head_branch") or ""))
    return None


def what_happened(event: Event) -> dict[str, Any]:
    """What a coder reads of an event: what happened, on which pull request, and who did it.

    Not the rest of the event: GitHub sends the whole repository with each one.
    """
    comment: dict[str, Any] | None = event.get("comment")
    review: dict[str, Any] | None = event.get("review")
    run: dict[str, Any] = event.get("workflow_run") or {}
    found: dict[str, Any] | None = (
        event.get("pull_request") or event.get("issue") or next(iter(run.get("pull_requests") or []), None)
    )
    pull_request = (
        {"number": found.get("number"), "title": found.get("title"), "url": found.get("html_url")} if found else None
    )
    sender: dict[str, Any] = event.get("sender") or {}
    by = sender.get("login")
    if review:
        return {
            "event": "a review",
            "pull_request": pull_request,
            "by": by,
            "state": review.get("state"),
            "body": review.get("body"),
        }
    if comment and comment.get("path"):
        return {
            "event": "a comment on a line",
            "pull_request": pull_request,
            "by": by,
            "body": comment.get("body"),
            "file": comment.get("path"),
            "line": comment.get("line"),
            "code": comment.get("diff_hunk"),
        }
    if comment:
        return {"event": "a comment", "pull_request": pull_request, "by": by, "body": comment.get("body")}
    return {
        "event": "a CI run that failed",
        "pull_request": pull_request,
        "workflow": run.get("name"),
        "branch": run.get("head_branch"),
        "url": run.get("html_url"),
    }
