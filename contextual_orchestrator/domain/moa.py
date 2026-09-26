"""Mixture-of-Agents aggregation prompt (Wang et al., 2024, arXiv:2406.04692).

In Mixture-of-Agents, several *proposer* models answer the query
independently and an *aggregator* model receives their responses with an
"Aggregate-and-Synthesize" instruction (the paper's Table 1) and writes the
final answer. This module builds only the aggregator's messages. It does not
call a model; the application layer sends the messages to the chosen
aggregator.

Differences from the paper, stated so no reader mistakes this for a full
reproduction:

- One proposer layer and one aggregator (the paper's two-layer "MoA-Lite"
  shape), not the multi-layer default.
- Proposer responses are shown without model names, so the aggregator
  cannot favour a provider by identity. The paper does not specify this.
- Empty proposer responses are dropped rather than shown as blanks.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import copy
from typing import Any

from .candidates import CandidateSet

AGGREGATE_AND_SYNTHESIZE_INSTRUCTION = (
    "You have been provided with a set of responses from various models to "
    "the latest user query. Your task is to synthesize these responses into a "
    "single, high-quality response. It is crucial to critically evaluate the "
    "information provided in these responses, recognizing that some of it may "
    "be biased or incorrect. Your response should not simply replicate the "
    "given answers but should offer a refined, accurate, and comprehensive "
    "reply to the instruction. Ensure your response is well-structured, "
    "coherent, and adheres to the highest standards of accuracy and "
    "reliability."
)
"""Aggregator instruction adapted from Wang et al. (2024), Table 1.

The only wording change is "various models" in place of "various
open-source models", because the proposer pool here may include hosted
proprietary models.
"""


def aggregate_and_synthesize_messages(
    original_messages: Sequence[Mapping[str, Any]],
    candidates: CandidateSet,
) -> list[dict[str, Any]]:
    """Build the aggregator's chat messages from the proposers' answers.

    Args:
        original_messages: The caller's chat messages. They are deep-copied
            and appended after the aggregator system message, so the
            aggregator answers the same conversation the proposers saw.
        candidates: The proposers' answers. Empty answers are dropped;
            the remaining ones are numbered in rank order.

    Returns:
        A new message list: one system message carrying the instruction and
        the numbered responses, followed by the original messages.

    Raises:
        ValueError: If there are no original messages or no nonempty
            proposer answers.
    """
    if not original_messages:
        raise ValueError("aggregation needs the original conversation messages")
    proposals = candidates.nonempty()
    if not proposals:
        raise ValueError("aggregation needs at least one nonempty proposer answer")
    numbered = "\n".join(
        f"{index}. {member.text.strip()}" for index, member in enumerate(proposals, 1)
    )
    system = f"{AGGREGATE_AND_SYNTHESIZE_INSTRUCTION}\n\nResponses from models:\n{numbered}"
    return [
        {"role": "system", "content": system},
        *(dict(copy.deepcopy(message)) for message in original_messages),
    ]
