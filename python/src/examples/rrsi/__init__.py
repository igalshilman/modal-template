"""
RRSI, simplified: regularized recursive self-improvement of an agent's harness.

After "RRSI: Regularized Recursive Self-Improvement of Agent Harnesses"
(https://arxiv.org/abs/2609.24972). An agent is a fixed model plus a harness: its prompt, its
skills and its tools. RRSI improves the harness in rounds, on a small set of tasks (the evolve
set): an analyst explains the failures, a proposer suggests edits, and a candidate replaces the
incumbent only if it passes regularizers that keep the search from overfitting that set:

- An edit budget that anneals from ``b_max`` edits per candidate down to ``b_min`` (cosine).
- A leakage screen before evaluation: a deterministic guard, then a critic model, reject edits
  that carry the tasks' answers or task-specific values.
- A noise band ``delta``, measured by evaluating the unchanged base harness several times: a
  candidate must score at least the best score so far minus ``delta``; above the band, its cost
  may grow only in proportion to its gain (``dC <= beta0 + beta1 * dS``); within the band, it must
  pay for itself (``w_s * dS - w_c * dC + w_n * novelty > 0``), so a simpler harness wins a tie.
- Every edit is recorded with its hypothesis and its effect, rejected ones too. When the score
  stalls, the proposer must try components it hasn't tried; components whose recent edits
  didn't help are offered for removal.

A held-out set, never used for selection, then shows whether the gains transfer.

Simplifications: a harness is a system prompt, named skills and tools from a fixed registry; the
tasks have exact answers, so the reward is deterministic; the cost is an estimate of tokens
from text lengths, not the model's usage.

How it runs on Restate: ``rrsi`` is a session object, one key per run, whose database holds the
harnesses, every trial, the rounds and the edit history. Each round is one ``step``: it computes
everything, then commits the round's records and sends the next ``step`` in one transaction, so
the loop advances once per round, whatever crashes. Every model call is a Restate call with a
stable idempotency key (the trials, and the analyst, proposer and critic, each an agent with a
conversation per round), so a retried round gets the same answers rather than asking again.

The package, one concern per module: ``harness`` (the harness, its edits and the tools),
``tasks`` (the tasks, the reward and the leakage guard), ``rules`` (the settings and the
regularizers), ``roles`` (the policy, analyst, proposer and critic, and their prompts) and
``search`` (the ``rrsi`` session object and its rounds).

To serve it, add ``rrsi.services`` to ``services`` in src/app.py (see src/examples/__init__.py).
It needs OPENAI_API_KEY, and makes many model calls: with the defaults, about 50 per round::

    curl localhost:8080/rrsi/run1/start/send --json '{}'          # measure the noise band, then run the rounds
    curl localhost:8080/rrsi/run1/status                          # the round, the scores, the incumbent harness
    curl localhost:8080/rrsi/run1/history                         # every edit: its hypothesis, verdict and effect
    curl localhost:8080/rrsi/run1/held_out                        # once done: base and final harness on unseen tasks
    curl localhost:8080/rrsi_proposer/run1.r0/messages            # what the proposer was asked, and answered, in round 0

``start`` takes the settings (see ``Settings``), such as ``{"rounds": 2, "trials": 1}``.
"""

from .roles import analyst, critic, proposer, trial
from .search import rrsi

services = [rrsi, trial, analyst, proposer, critic]
