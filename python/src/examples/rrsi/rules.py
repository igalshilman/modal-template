"""The regularizers, as plain functions of the search's settings: what keeps the search from overfitting."""

import math

from pydantic import BaseModel

from .harness import STRUCTURAL, Component, Edit


class Settings(BaseModel):
    """The search's settings: the paper's symbols, with small defaults (the paper's coding setup in brackets)."""

    rounds: int = 4  # T [20]
    trials: int = 2  # k, trials per task [2]
    noise_repeats: int = 3  # evaluations of the base harness that measure delta
    min_delta: float = 0.02  # delta's floor [0.017]
    candidates: int = 3  # candidates per round
    b_min: int = 1  # the last round's edit budget [1]
    b_max: int = 3  # the first round's edit budget [4]
    stall_window: int = 2  # w [3]
    m_draft: int = 1  # candidates reserved for untried components when stalled [1]
    prune_window: int = 2  # n_prune [4]
    beta0: float = 0.10  # cost allowance [0.10]
    beta1: float = 10.0  # cost allowance per point of gain [44.5]
    w_s: float = 1.0  # within the noise band: the weight of score,
    w_c: float = 0.5  # ... of cost,
    w_n: float = 0.05  # ... and of novelty


def edit_budget(t: int, s: Settings) -> int:
    """How many edits a candidate of round ``t`` may make: from ``b_max`` down to ``b_min`` on a cosine (Eq. 4)."""
    annealed = 0.5 * (1 + math.cos(math.pi * t / s.rounds))
    return math.ceil(s.b_min + (s.b_max - s.b_min) * annealed)


def noise_band(scores: list[float], s: Settings) -> float:
    """``delta``: how much the score of an unchanged harness varies from one evaluation to the next."""
    return max(max(scores) - min(scores), s.min_delta)


def is_stalled(score: float, earlier: float | None, delta: float) -> bool:
    """Whether the score has gained no more than the noise since ``stall_window`` rounds ago."""
    return earlier is not None and score - earlier <= delta


def novelty(edits: list[Edit], accepted: set[Component]) -> int:
    """How many structural components the edits add that no accepted edit has added before."""
    return len({e.component for e in edits if e.component in STRUCTURAL and e.op == "add"} - accepted)


def rejection(
    *, score: float, gain: float, cost_change: float, novel: int, best: float, delta: float, s: Settings
) -> str | None:
    """Why an evaluated candidate is not admissible, or ``None`` if it is (Eq. 5, 7 and 17).

    Args:
        score: The candidate's score.
        gain: Its score minus the incumbent's (dS).
        cost_change: Its cost's change relative to the incumbent's (dC).
        novel: Its novelty (see ``novelty``).
        best: The best score so far (S*).
        delta: The noise band.
        s: The settings.
    """
    if score < best - delta:
        return "below the best"
    if gain > delta:
        # A real gain may cost more, in proportion to it.
        affordable = cost_change <= s.beta0 + s.beta1 * gain
    else:
        # Within the noise, it must pay for itself: cheaper, or new structure.
        affordable = s.w_s * gain - s.w_c * cost_change + s.w_n * novel > 0
    return None if affordable else "cost"
