# Serving-time replica selection and first-response races

## Citation (APA 7th)

Yu, G.-I., Jeong, J. S., Kim, G.-W., Kim, S., & Chun, B.-G. (2022). Orca: A
distributed serving system for Transformer-based generative models. In
*16th USENIX Symposium on Operating Systems Design and Implementation (OSDI 22)*
(pp. 521–538). USENIX Association.
https://www.usenix.org/conference/osdi22/presentation/yu

## Relevance

`model_group` racing returns the first valid completion among operationally
equivalent replicas so healthy-but-slow endpoints do not serialize the entire
role step (issue #102). This is replica tail-latency mitigation within one
equivalence class — not a substitute for multi-agent conduct depth or
cross-role diversity (thinker / worker / verifier / synthesizer).
