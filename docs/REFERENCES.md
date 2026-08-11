# Authoritative references

**Document state:** `research_only`

References use APA 7 style where the source provides sufficient metadata.
Research motivates hypotheses and evaluation; it does not make this repository
an implementation of a trained system or establish product superiority.

## Orchestration, routing, and test-time compute

Chen, L., Zaharia, M., & Zou, J. (2023). *FrugalGPT: How to use large
language models while reducing cost and improving performance* [Preprint].
arXiv. https://doi.org/10.48550/arXiv.2305.05176

Ding, D., Mallick, A., Wang, C., Sim, R., Mukherjee, S., Rühle, V.,
Lakshmanan, L. V. S., & Awadallah, A. H. (2024). Hybrid LLM: Cost-efficient
and quality-aware query routing. In *The Twelfth International Conference on
Learning Representations*. https://openreview.net/forum?id=02f3mUtqnM
Source-license authority: https://arxiv.org/abs/2404.14618

Ding, D., Mallick, A., Zhang, S., Wang, C., Madrigal, D., Garcia, M. D. C. H.,
Xia, M., Lakshmanan, L. V. S., Wu, Q., & Rühle, V. (2025). *BEST-Route:
Adaptive LLM routing with test-time optimal compute* [Preprint]. arXiv.
https://doi.org/10.48550/arXiv.2506.22716

Hu, Q. J., Bieker, J., Li, X., Jiang, N., Keigwin, B., Ranganath, G.,
Keutzer, K., & Upadhyay, S. K. (2024). *RouterBench: A benchmark for multi-LLM
routing system* [Preprint]. arXiv.
https://doi.org/10.48550/arXiv.2403.12031

Nielsen, S., Cetin, E., Schwendeman, P., Sun, Q., Xu, J., & Tang, Y. (2026).
Learning to orchestrate agents in natural language with the Conductor. In *The
Fourteenth International Conference on Learning Representations*.
https://openreview.net/forum?id=U23A2BUKYt

Ong, I., Almahairi, A., Wu, V., Chiang, W.-L., Wu, T., Gonzalez, J. E.,
Kadous, M. W., & Stoica, I. (2024). *RouteLLM: Learning to route LLMs with
preference data* [Preprint]. arXiv.
https://doi.org/10.48550/arXiv.2406.18665

Sakana AI. (2026). *Sakana Fugu technical report* [Preprint]. arXiv.
https://doi.org/10.48550/arXiv.2606.21228

Snell, C., Lee, J., Xu, K., & Kumar, A. (2024). *Scaling LLM test-time compute
optimally can be more effective than scaling model parameters* [Preprint].
arXiv. https://doi.org/10.48550/arXiv.2408.03314

Xu, J., Sun, Q., Schwendeman, P., Nielsen, S., Cetin, E., & Tang, Y. (2026).
TRINITY: An evolved LLM coordinator. In *The Fourteenth International
Conference on Learning Representations*.
https://openreview.net/forum?id=5HaRjXai12

Hybrid LLM supports small/large-model difficulty routing, not a paper claim
about interactive-versus-batch channels. The repository's sync/batch policy is
a product inference and requires its own evidence.

## HTTP, API, and observability contracts

Bray, T. (2017). *The JavaScript Object Notation (JSON) data interchange
format* (RFC 8259). RFC Editor. https://doi.org/10.17487/RFC8259

Fielding, R., Nottingham, M., & Reschke, J. (2022). *HTTP semantics* (RFC
9110). RFC Editor. https://doi.org/10.17487/RFC9110

Nottingham, M., Wilde, E., & Dalal, S. (2023). *Problem details for HTTP APIs*
(RFC 9457). RFC Editor. https://doi.org/10.17487/RFC9457

OpenAPI Initiative. (2021, February 15). *OpenAPI Specification, Version
3.1.0*. https://spec.openapis.org/oas/v3.1.0.html

OpenAI. (n.d.-a). *API reference overview*. Retrieved August 9, 2026, from
https://developers.openai.com/api/reference/overview/

OpenAI. (n.d.-b). *Chat Completions*. Retrieved August 9, 2026, from
https://developers.openai.com/api/reference/chat-completions/overview/

OpenAI. (n.d.-c). *Error codes*. Retrieved August 9, 2026, from
https://developers.openai.com/api/docs/guides/error-codes

OpenAI. (n.d.-d). *Streaming API responses*. Retrieved August 9, 2026, from
https://developers.openai.com/api/docs/guides/streaming-responses

Rescorla, E. (2018). *The Transport Layer Security (TLS) protocol version 1.3*
(RFC 8446). RFC Editor. https://doi.org/10.17487/RFC8446

WHATWG. (n.d.). *HTML living standard: Server-sent events*. Retrieved August 9,
2026, from
https://html.spec.whatwg.org/multipage/server-sent-events.html

World Wide Web Consortium. (2021, November 23). *Trace context*.
https://www.w3.org/TR/trace-context/

“OpenAI-compatible” is a tested vendor-subset label, not standards-body
certification. Admin errors may adopt RFC 9457, but compatible endpoints must
retain their explicitly tested vendor envelope. The implemented OpenAPI object
declares 3.1.0; newer specifications are not silently claimed.

## AI, secure-development, and secrets governance

Autio, C., Schwartz, R., Dunietz, J., Jain, S., Stanley, M., Tabassi, E.,
Hall, P., & Roberts, K. (2024). *Artificial intelligence risk management
framework: Generative artificial intelligence profile* (NIST AI 600-1).
National Institute of Standards and Technology.
https://doi.org/10.6028/NIST.AI.600-1

Barker, E. (2020). *Recommendation for key management: Part 1—General* (NIST
SP 800-57 Part 1 Rev. 5). National Institute of Standards and Technology.
https://doi.org/10.6028/NIST.SP.800-57pt1r5

Booth, H., Souppaya, M., Vassilev, A., Ogata, M., Stanley, M., & Scarfone, K.
(2024). *Secure software development practices for generative AI and dual-use
foundation models: An SSDF community profile* (NIST SP 800-218A). National
Institute of Standards and Technology.
https://doi.org/10.6028/NIST.SP.800-218A

International Organization for Standardization. (2022). *Information security,
cybersecurity and privacy protection—Information security management systems—
Requirements* (ISO/IEC Standard No. 27001:2022).
https://www.iso.org/standard/27001

International Organization for Standardization. (2023a). *Artificial
intelligence—Guidance on risk management* (ISO/IEC Standard No. 23894:2023).
https://www.iso.org/standard/77304.html

International Organization for Standardization. (2023b). *Information
technology—Artificial intelligence—Management system* (ISO/IEC Standard No.
42001:2023). https://www.iso.org/standard/81230.html

OWASP Foundation. (n.d.-a). *Secrets management cheat sheet*. Retrieved August
9, 2026, from
https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html

OWASP Foundation. (n.d.-b). *Server side request forgery prevention cheat
sheet*. Retrieved August 9, 2026, from
https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html

OWASP Foundation. (2025). *OWASP Top 10 for large language model applications
2025*. https://genai.owasp.org/llm-top-10/

Souppaya, M., Scarfone, K., & Dodson, D. (2022). *Secure software development
framework (SSDF) version 1.1: Recommendations for mitigating the risk of
software vulnerabilities* (NIST SP 800-218). National Institute of Standards
and Technology. https://doi.org/10.6028/NIST.SP.800-218

Tabassi, E. (2023). *Artificial intelligence risk management framework (AI RMF
1.0)* (NIST AI 100-1). National Institute of Standards and Technology.
https://doi.org/10.6028/NIST.AI.100-1

The pgcrypto registry is an optional encrypted database backend, not a managed
KMS claim. Production evidence still requires root-key separation, rotation,
revocation, least privilege, tenant scope, audit, backup protection, and
redaction.

## SOC 2 and Korean CSAP evidence framing

American Institute of Certified Public Accountants. (2022a). *2017 Trust
Services Criteria for security, availability, processing integrity,
confidentiality, and privacy (with revised points of focus—2022)*.
https://www.aicpa-cima.com/resources/download/2017-trust-services-criteria-with-revised-points-of-focus-2022

American Institute of Certified Public Accountants. (2022b). *2018 description
criteria for a description of a service organization's system in a SOC 2
report (with revised implementation guidance—2022)*.
https://www.aicpa.org/resources/download/get-description-criteria-for-your-organizations-soc-2-r-report

과학기술정보통신부. (2023). *클라우드컴퓨팅서비스 보안인증에 관한 고시*
(과학기술정보통신부고시 제2023-4호). 국가법령정보센터.
https://law.go.kr/LSW/admRulInfoP.do?admRulSeq=2100000218804

대한민국. (2025). *클라우드컴퓨팅 발전 및 이용자 보호에 관한 법률* (법률
제21066호). 국가법령정보센터.
https://law.go.kr/lsInfoP.do?lsId=012266

한국인터넷진흥원. (2026, March 12). *클라우드서비스 보안인증(CSAP)*.
https://www.kisa.or.kr/1050603

SOC 2 is an independent CPA examination/report, not a certification badge.
CSAP applicability depends on the deployed cloud-service boundary and current
KISA assessment materials. Repository controls can provide readiness evidence
but cannot establish either external result.

## Source-license authority

arXiv. (n.d.). *License and copyright*. Retrieved August 9, 2026, from
https://info.arxiv.org/help/license/index.html

Creative Commons. (n.d.). *Attribution-NonCommercial-NoDerivatives 4.0
International*. Retrieved August 9, 2026, from
https://creativecommons.org/licenses/by-nc-nd/4.0/

An author's non-exclusive grant to arXiv does not automatically grant this
repository downstream redistribution rights. Hybrid LLM is marked CC
BY-NC-ND 4.0, which does not authorize commercial distribution. The repository
links to authoritative sources and does not vendor those PDFs without separate
permission or legal review.
