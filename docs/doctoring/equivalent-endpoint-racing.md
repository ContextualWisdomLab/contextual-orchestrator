# Equivalent endpoint racing evidence

## Decision boundary

Replica racing is permitted only after an operator supplies a complete, reviewed
equivalence contract. Provider or model names are never identity evidence. The
contract must agree on revision, reasoning effort, capability set, structured
output, accuracy class, residency, retention, context limit, and pricing evidence.
Missing or different fields preserve sequential failover.

The executor accepts only a completed response that passes the modality validator.
It bounds concurrency by configured provider concurrency and uses the transport
deadline. A valid response is published once; later results are safely ignored.
Attempt and winner identifiers, completion time, and cancellation/drain outcomes
enter the audit stream without prompts, credentials, or hidden reasoning.

Dean and Barroso distinguish hedged requests from model selection: duplicate work
is sent to equivalent replicas to reduce latency tails. Their evidence motivates
this mechanism but does not prove LLM endpoint equivalence, determine a hedge
delay, or justify unbounded duplicate spend. This implementation therefore has no
name similarity, hand-authored score, or inferred equivalence.

## References

Dean, J., & Barroso, L. A. (2013). The tail at scale. *Communications of the ACM,
56*(2), 74–80. https://doi.org/10.1145/2408776.2408794

Gardner, K., Harchol-Balter, M., Scheller-Wolf, A., & Van Houdt, B. (2017).
Redundancy-d: The power of d choices for redundancy. *Operations Research,
65*(4), 1078–1094. https://doi.org/10.1287/opre.2016.1582
